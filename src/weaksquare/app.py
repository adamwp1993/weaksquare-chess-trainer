"""Composition root: the only place concrete adapters are built and wired (ARCHITECTURE §1)."""

from __future__ import annotations

import argparse
import logging
import mimetypes
import os
import sys
from collections.abc import Mapping, Sequence

from weaksquare import config
from weaksquare.adapters import instance_lock
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import NewerSchemaError, migrate
from weaksquare.adapters.desktop import Desktop, show_fatal
from weaksquare.adapters.logging_setup import setup_logging
from weaksquare.adapters.system_clock import SystemClock, make_rng
from weaksquare.bridge.api import Api
from weaksquare.bridge.events import EventSink
from weaksquare.jobs.runner import JobRunner

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


def fix_mime_types() -> None:
    """The Windows registry often maps .js to text/plain, and WebView2 then refuses to run the
    module scripts that pywebview's local server sends. Pin the types the bundle needs."""
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")


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

    db = Database(paths.user_db, paths.puzzles_db)
    events = EventSink()
    runner = JobRunner(events)
    desktop = Desktop()
    api = Api(paths=paths, desktop=desktop, clock=clock, dev_mode=args.dev)
    _ = rng  # handed to services as they arrive

    window = webview.create_window(title, url, js_api=api, width=1280, height=860, min_size=(1000, 700))
    if window is None:  # pragma: no cover - pywebview returns None only if creation failed
        raise RuntimeError("could not create the window")
    events.attach(window)
    desktop.attach(window)

    try:
        webview.start(private_mode=True, http_server=not args.dev_server, debug=False)
    finally:
        log.info("Shutting down")
        runner.cancel_all()
        db.close_all()
        lock.release()
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
