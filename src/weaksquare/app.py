"""Composition root: the only place concrete adapters are built and wired (ARCHITECTURE §1)."""

from __future__ import annotations

import argparse
import logging
import mimetypes
import os
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from weaksquare import config
from weaksquare.adapters import instance_lock
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import NewerSchemaError, load_migrations, migrate, read_version
from weaksquare.adapters.db.repos.presets import PresetsRepo
from weaksquare.adapters.db.repos.puzzle_import import ExistingPuzzleDb, PuzzleDbWriter
from weaksquare.adapters.db.repos.puzzle_meta import PuzzleMetaRepo
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.stats import StatsRepo
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, SessionsRepo, SettingsRepo
from weaksquare.adapters.desktop import Desktop, show_fatal, system_prefers_dark
from weaksquare.adapters.files import PuzzleCsv, sha256_file
from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.logging_setup import setup_logging
from weaksquare.adapters.system_clock import SystemClock, make_rng
from weaksquare.bridge.api import Api
from weaksquare.bridge.events import EventSink
from weaksquare.core.clock import Clock
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.mixer import MixerService
from weaksquare.services.presets import PresetService
from weaksquare.services.puzzle_db import ImportDeps, PuzzleDbService
from weaksquare.services.session import SessionService
from weaksquare.services.stats import StatsService
from weaksquare.services.ui_settings import UiSettingsService

log = logging.getLogger("weaksquare")

DEBUG_PORT_ENV = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
VITE_DEV_URL = "http://localhost:5173"


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="weaksquare", description=config.APP_TITLE)
    ap.add_argument("--dev", action="store_true", help="development run: uses the WeakSquare-dev data folder")
    ap.add_argument(
        "--dev-server", action="store_true", help=f"load the front end from the Vite dev server ({VITE_DEV_URL})"
    )
    args = ap.parse_args(argv)
    if args.dev_server:
        args.dev = True
    return args


def debug_port_refusal(env: Mapping[str, str], dev: bool) -> str | None:
    """SR-16: the WebView2 debugging port may only be enabled by the test harness (dev runs)."""
    if "--remote-debugging-port" in env.get(DEBUG_PORT_ENV, "") and not dev:
        return (
            f"{DEBUG_PORT_ENV} enables a remote-debugging port, which would let any program on this PC "
            "control the app. WeakSquare refuses to start like this. Remove the variable and try again."
        )
    return None


def window_title(dev: bool) -> str:
    return config.APP_TITLE + (" (dev)" if dev else "")


def front_end_url(dev_server: bool) -> str | None:
    if dev_server:
        return VITE_DEV_URL
    index = config.WEB_DIST / "index.html"
    return str(index) if index.is_file() else None


# The page background of each scheme (Mantine's body colors), so the window never flashes the
# other scheme while the front end loads (FR-1.12).
WINDOW_BACKGROUND = {"light": "#FFFFFF", "dark": "#242424"}


def window_background(scheme: str, system_dark: bool) -> str:
    dark = scheme == "dark" or (scheme == "auto" and system_dark)
    return WINDOW_BACKGROUND["dark" if dark else "light"]


def fix_mime_types() -> None:
    """The Windows registry often maps .js to text/plain, and WebView2 then refuses to run the
    module scripts that pywebview's local server sends. Pin the types the bundle needs."""
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")


@dataclass
class Services:
    db: Database
    http: HttpClient
    puzzle_db: PuzzleDbService
    mixer: MixerService
    sessions: SessionService
    presets: PresetService
    stats: StatsService
    ui_settings: UiSettingsService

    def close(self) -> None:
        self.http.close()
        self.db.close_all()


def build_services(
    paths: config.Paths, clock: Clock, runner: JobRunner, rng: random.Random, http: HttpClient | None = None
) -> Services:
    """Wire the concrete adapters into the services. Also used by the scripts/ CLIs."""
    db = Database(paths.user_db, paths.puzzles_db)
    http = http or HttpClient()
    meta = PuzzleMetaRepo(db)
    puzzle_db = PuzzleDbService(
        ImportDeps(
            puzzles_db=paths.puzzles_db,
            new_db=paths.puzzles_new_db,
            downloads_dir=paths.downloads_dir,
            db_url=config.PUZZLE_DB_URL,
            sums_url=config.PUZZLE_SUMS_URL,
            http=http,
            open_csv=PuzzleCsv,
            make_writer=lambda path: PuzzleDbWriter(path, clock),
            sha256=sha256_file,
            swap=db.swap_puzzles_db,
            read_meta=meta.read,
            open_existing=ExistingPuzzleDb,
            schema_version=read_version,
            latest_schema=load_migrations(config.MIGRATIONS_DIR / "puzzles")[-1].version,
        ),
        runner,
        clock,
    )
    puzzles = LichessDbSource(db)
    attempts = AttemptsRepo(db)
    mixer = MixerService(puzzles)
    ui_settings = UiSettingsService(SettingsRepo(db))
    sessions = SessionService(puzzles, attempts, SessionsRepo(db), clock, rng)
    presets = PresetService(PresetsRepo(db), clock)
    stats = StatsService(StatsRepo(db), attempts)
    return Services(
        db=db,
        http=http,
        puzzle_db=puzzle_db,
        mixer=mixer,
        sessions=sessions,
        presets=presets,
        stats=stats,
        ui_settings=ui_settings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    title = window_title(args.dev)

    refusal = debug_port_refusal(os.environ, args.dev)
    if refusal:
        show_fatal(title, refusal)
        return 2

    paths = config.resolve_paths(dev=args.dev)
    paths.ensure()

    lock = instance_lock.acquire(paths.lock_file)
    if lock is None:
        instance_lock.bring_existing_to_front(title)
        return 0
    instance_lock.write_pid(lock)
    fix_mime_types()

    import webview  # imported late: a second launch exits without loading the GUI stack

    file_handler = setup_logging(paths.logs_dir, config.APP_VERSION)
    clock = SystemClock()
    rng = make_rng()
    log.info("Data folder: %s (dev=%s)", paths.data_dir, args.dev)

    try:
        migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock, paths.backups_dir)
    except NewerSchemaError as e:
        log.error("%s", e)
        show_fatal(title, str(e))
        lock.release()
        return 1

    url = front_end_url(args.dev_server)
    if url is None:
        msg = "The front end isn't built. Run `python scripts/setup.py` (or `npm.cmd --prefix web run build`)."
        log.error(msg)
        show_fatal(title, msg)
        lock.release()
        return 1

    events = EventSink()
    runner = JobRunner(events)
    services = build_services(paths, clock, runner, rng)
    desktop = Desktop()
    api = Api(
        paths=paths,
        desktop=desktop,
        clock=clock,
        dev_mode=args.dev,
        runner=runner,
        puzzle_db=services.puzzle_db,
        mixer=services.mixer,
        sessions=services.sessions,
        presets=services.presets,
        stats=services.stats,
        ui_settings=services.ui_settings,
    )

    scheme = services.ui_settings.get().color_scheme
    window = webview.create_window(
        title,
        url,
        js_api=api,
        width=1280,
        height=860,
        min_size=(1000, 700),
        background_color=window_background(scheme, system_prefers_dark()),
    )
    if window is None:  # pragma: no cover - pywebview returns None only if creation failed
        raise RuntimeError("could not create the window")
    events.attach(window)
    desktop.attach(window)
    window.events.closing += events.detach

    try:
        webview.start(private_mode=True, http_server=not args.dev_server, debug=False)
    finally:
        log.info("Shutting down")
        runner.cancel_all()
        services.close()
        lock.release()
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
