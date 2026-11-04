"""Composition root: the only place concrete adapters are built and wired (ARCHITECTURE §1)."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import platform
import random
import secrets as secrets_module
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from weaksquare import config
from weaksquare.adapters import instance_lock
from weaksquare.adapters.chesscom import ChesscomGames, classify_game_error
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import NewerSchemaError, load_migrations, migrate, read_version
from weaksquare.adapters.db.repos.custom_puzzles import CustomPuzzlesRepo, RetryRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.adapters.db.repos.games import AccountSyncRepo, GamesRepo
from weaksquare.adapters.db.repos.lichess import LichessHistoryRepo, SyncRepo
from weaksquare.adapters.db.repos.llm import LlmCacheRepo, LlmPricesRepo, LlmUsageRepo
from weaksquare.adapters.db.repos.presets import PresetsRepo
from weaksquare.adapters.db.repos.puzzle_import import ExistingPuzzleDb, PuzzleDbWriter
from weaksquare.adapters.db.repos.puzzle_meta import PuzzleMetaRepo
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.stats import StatsRepo
from weaksquare.adapters.db.repos.user_data import (
    AttemptsRepo,
    MistakeReasonsRepo,
    ModeFields,
    SessionsRepo,
    SettingsRepo,
    SyncFields,
)
from weaksquare.adapters.desktop import (
    Desktop,
    set_app_user_model_id,
    set_window_icon,
    show_fatal,
    system_prefers_dark,
)
from weaksquare.adapters.files import PuzzleCsv, extract_member, rename_with_retry, sha256_file, zip_names
from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.lichess import (
    LichessHttp,
    is_network_error,
    is_rate_limited,
    is_unauthorized,
    retry_after,
)
from weaksquare.adapters.lichess_games import LichessGames
from weaksquare.adapters.llm.anthropic import AnthropicProvider
from weaksquare.adapters.llm.openai import OpenAIProvider
from weaksquare.adapters.logging_setup import setup_logging
from weaksquare.adapters.oauth_loopback import LoopbackCancelled, LoopbackListener, LoopbackTimeout
from weaksquare.adapters.scheduler import TimerScheduler
from weaksquare.adapters.secret_store import KeyringSecretStore, MemorySecretStore, SecretStore, service_name
from weaksquare.adapters.stockfish import StockfishEngine, probe_engine
from weaksquare.adapters.system_clock import OffsetClock, SystemClock, make_rng
from weaksquare.bridge import dto
from weaksquare.bridge.api import Api, attempt_rating
from weaksquare.bridge.events import EventSink
from weaksquare.core.clock import Clock
from weaksquare.core.engine import EngineClient, EngineProbe, parse_manifest, platform_key
from weaksquare.core.games import ChesscomClient, LichessGamesClient
from weaksquare.core.lichess import LichessClient
from weaksquare.core.llm.provider import LLMProvider
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.account import AccountDeps, AccountService, AccountStatus, ListenerErrors
from weaksquare.services.analysis import AnalysisService
from weaksquare.services.db_update import UpdateCheckService, Urls
from weaksquare.services.engine import EngineService
from weaksquare.services.engine_install import EngineInstaller, InstallDeps
from weaksquare.services.explain import ExplainService
from weaksquare.services.games import GameLibraryService
from weaksquare.services.lichess_history import HistoryService
from weaksquare.services.llm_settings import LlmSettingsService
from weaksquare.services.llm_usage import LlmUsageService
from weaksquare.services.mixer import MixerService
from weaksquare.services.presets import PresetService
from weaksquare.services.puzzle_db import ImportDeps, PuzzleDbService
from weaksquare.services.reasons import ReasonsService
from weaksquare.services.review import ReviewService
from weaksquare.services.session import SessionService
from weaksquare.services.stats import StatsService
from weaksquare.services.sync import SyncDeps, SyncService, SyncUpdate
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


def build_engine_installer(
    paths: config.Paths, http: HttpClient | None, clock: Clock, probe: EngineProbe = probe_engine
) -> EngineInstaller:
    """The one Stockfish installer (FR-7.5), shared by the app, fetch_stockfish.py and setup.py."""
    manifest = parse_manifest(json.loads(config.ENGINE_MANIFEST.read_text(encoding="utf-8")))
    return EngineInstaller(
        InstallDeps(
            http=http,
            manifest=manifest,
            platform=platform_key(platform.system(), platform.machine()),
            engines_dir=paths.engines_dir,
            downloads_dir=paths.downloads_dir,
            sha256=sha256_file,
            zip_names=zip_names,
            extract=extract_member,
            probe=probe,
            clock=clock,
            rename=rename_with_retry,
        )
    )


def engine_log_line(status: Any) -> str:
    """NFR-4 (v0.4-B6): the banner can only see the managed install (it's written before user.db is
    open), so the engine actually in use, a custom one included, is logged right after start-up."""
    if status.state == "ready":
        kind = "your own engine" if status.source == "custom" else f"managed, {status.tag}"
        return f"Engine in use: {status.name} ({kind}) at {status.path}"
    if status.state == "custom_invalid":
        return f"Engine in use: none (custom engine missing: {status.path})"
    return f"Engine in use: none ({status.state})"


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
    db_update: UpdateCheckService
    account: AccountService
    sync: SyncService
    history: HistoryService
    scheduler: Any
    engine: EngineService
    reasons: ReasonsService
    llm_settings: LlmSettingsService
    llm_usage: LlmUsageService
    explain: ExplainService
    games: GameLibraryService
    analysis: AnalysisService
    review: ReviewService

    def close(self) -> None:
        self.engine.close()  # NFR-6: stop the engine process
        close = getattr(self.scheduler, "close", None)
        if close:
            close()
        self.http.close()
        self.db.close_all()


def build_services(
    paths: config.Paths,
    clock: Clock,
    runner: JobRunner,
    rng: random.Random,
    http: HttpClient | None = None,
    *,
    secrets: SecretStore | None = None,
    lichess: LichessClient | None = None,
    scheduler: Any = None,
    browser: Any = None,
    make_listener: Callable[..., Any] | None = None,
    emit: Callable[[str, Any], None] = lambda name, payload: None,
    make_engine: Callable[[str, int, int], EngineClient] | None = None,
    engine_probe: EngineProbe | None = None,
    cpu_count: int | None = None,
    llm_providers: dict[str, LLMProvider] | None = None,
    lichess_games: LichessGamesClient | None = None,
    chesscom: ChesscomClient | None = None,
) -> Services:
    """Wire the concrete adapters into the services. Also used by the scripts/ CLIs and tests.

    `secrets` defaults to an in-memory store, so only `main()` (which passes the keyring store) ever
    touches Windows Credential Manager; scripts and tests never do."""
    db = Database(paths.user_db, paths.puzzles_db)
    http = http or HttpClient()
    secrets = secrets or MemorySecretStore()
    lichess = lichess or LichessHttp(http)
    scheduler = scheduler or TimerScheduler()
    browser = browser or Desktop()
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
    sync_repo = SyncRepo(db)
    history_repo = LichessHistoryRepo(db)

    def account_changed(st: AccountStatus) -> None:
        emit("account", dto.AccountStatus(st.state, st.username, st.rating, st.provisional))

    account = AccountService(
        AccountDeps(
            lichess=lichess,
            secrets=secrets,
            settings=SettingsRepo(db),
            runner=runner,
            make_listener=make_listener or (lambda accept: LoopbackListener(accept)),
            listener_errors=ListenerErrors(LoopbackTimeout, LoopbackCancelled),
            browser=browser,
            scheduler=scheduler,
            new_secret=lambda: secrets_module.token_urlsafe(48),
            is_network_error=is_network_error,
            is_unauthorized=is_unauthorized,
        ),
        notify=account_changed,
    )

    def sync_changed(u: SyncUpdate) -> None:
        status = dto.SyncStatus(u.status.state, u.status.pending, history_repo.count())
        emit("sync", dto.SyncEvent(status, [r for r in (attempt_rating(a) for a in u.attempts) if r is not None]))

    sync = SyncService(
        SyncDeps(
            repo=sync_repo,
            history=history_repo,
            account=account,
            lichess=lichess,
            runner=runner,
            scheduler=scheduler,
            clock=clock,
            is_network_error=is_network_error,
            is_unauthorized=is_unauthorized,
            retry_after=retry_after,
            is_rate_limited=is_rate_limited,
        ),
        notify=sync_changed,
    )
    history = HistoryService(account, lichess, history_repo, SettingsRepo(db), runner,
                             is_network_error, is_unauthorized, on_done=sync.announce)  # fmt: skip

    def after_sign_in() -> None:
        history.start_import()
        sync.kick(force=True)  # a fresh sign-in may cut a network backoff short (never a 429 wait)

    account.on_signed_in(after_sign_in)
    probe = engine_probe or probe_engine
    engine = EngineService(
        build_engine_installer(paths, http, clock, probe),
        SettingsRepo(db),
        runner,
        make_engine or (lambda path, threads, hash_mb: StockfishEngine(path, threads, hash_mb)),
        probe,
        cpu_count or os.cpu_count() or 1,
    )
    sessions = SessionService(puzzles, attempts, SessionsRepo(db), clock, rng, sync=sync, queue_fields=SyncFields,
                              engine=engine, prefs=ui_settings, mode_fields=ModeFields)  # fmt: skip
    reasons = ReasonsService(attempts, MistakeReasonsRepo(db), clock, sessions.suggestion_for)
    presets = PresetService(PresetsRepo(db), clock)
    stats = StatsService(StatsRepo(db), attempts, sync_repo, clock)
    db_update = UpdateCheckService(
        http, clock, SettingsRepo(db), meta.read, runner,
        Urls(file=config.PUZZLE_DB_URL, sums=config.PUZZLE_SUMS_URL, page=config.PUZZLE_PAGE_URL),
    )  # fmt: skip
    llm_settings = LlmSettingsService(
        SettingsRepo(db),
        secrets,
        LlmPricesRepo(db),
        llm_providers or {"anthropic": AnthropicProvider(http), "openai": OpenAIProvider(http)},
        runner,
        lambda: clock.local_date(clock.now()),
    )
    llm_usage = LlmUsageService(llm_settings, LlmUsageRepo(db), clock)
    explain = ExplainService(sessions, llm_settings, llm_usage, LlmCacheRepo(db), runner, clock)
    games_repo = GamesRepo(db)
    games = GameLibraryService(
        games_repo, AccountSyncRepo(db), SettingsRepo(db), runner, clock, account,
        lichess_games or LichessGames(http), chesscom or ChesscomGames(http), classify_game_error,
    )  # fmt: skip
    analysis_repo = GameAnalysisRepo(db)
    analysis = AnalysisService(games_repo, analysis_repo, engine, SettingsRepo(db), runner)
    review = ReviewService(
        games_repo, analysis_repo, analysis, analysis.is_current, engine, CustomPuzzlesRepo(db), RetryRepo(db),
        MistakeReasonsRepo(db), ui_settings, clock,
    )  # fmt: skip
    return Services(
        db=db,
        http=http,
        puzzle_db=puzzle_db,
        mixer=mixer,
        sessions=sessions,
        presets=presets,
        stats=stats,
        ui_settings=ui_settings,
        db_update=db_update,
        account=account,
        sync=sync,
        history=history,
        scheduler=scheduler,
        engine=engine,
        reasons=reasons,
        llm_settings=llm_settings,
        llm_usage=llm_usage,
        explain=explain,
        games=games,
        analysis=analysis,
        review=review,
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

    # FR-4.6 fast-forward time exists only in --dev runs (the dev data folder): the real app's clock is never moved.
    clock: SystemClock = OffsetClock() if args.dev else SystemClock()
    try:  # NFR-4: the banner names the engine; a custom engine is logged when it starts
        stockfish = build_engine_installer(paths, None, clock).describe()
    except Exception:
        stockfish = "unknown"
    file_handler = setup_logging(paths.logs_dir, config.APP_VERSION, stockfish=stockfish)
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
    desktop = Desktop(title)
    services = build_services(
        paths, clock, runner, rng,
        # A sign-in belongs to its data folder: dev and test runs never see your real one.
        secrets=KeyringSecretStore(
            service_name(paths.data_dir, config.default_data_dir(False), config.default_data_dir(True))
        ),
        browser=desktop,
        emit=events.emit,
    )  # fmt: skip
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
        db_update=services.db_update,
        account=services.account,
        sync=services.sync,
        history=services.history,
        engine=services.engine,
        reasons=services.reasons,
        llm_settings=services.llm_settings,
        llm_usage=services.llm_usage,
        explain=services.explain,
    )
    if isinstance(clock, OffsetClock):
        clock.set_offset_days(services.ui_settings.time_offset_days())
        if clock.offset_days:
            log.info("dev clock fast-forwarded by %d days", clock.offset_days)
    log.info("%s", engine_log_line(services.engine.status()))
    services.account.check()  # FR-1.6: validate a stored sign-in in the background
    services.llm_settings.start_launch_check()  # FR-1.6: and a stored AI key, with the free model lookup

    scheme = services.ui_settings.get().color_scheme
    set_app_user_model_id()  # NFR-8a: its own taskbar button and icon, not python.exe's
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
    window.events.shown += lambda: log.info(
        "window icon %s", "set" if set_window_icon(title, config.ICON_FILE) else "not set"
    )

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
