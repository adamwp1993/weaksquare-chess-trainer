"""Rotating local logs, secret redaction and crash hooks (NFR-4, SR-5, SR-10)."""

from __future__ import annotations

import logging
import platform
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

log = logging.getLogger("weaksquare")

_REDACTIONS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,'\"]+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.~+/=]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\bli[a-z]?_[A-Za-z0-9]{8,}"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "[REDACTED]"),
    (re.compile(r"(?i)\b(code|code_verifier|access_token|api_key|token)=([^&\s]+)"), r"\1=[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Defense in depth: scrub token-like values from every record before it's written."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        record.msg = redact(message)
        record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_version() -> str:
    """The installed WebView2 Runtime version, from where Microsoft documents it in the registry."""
    if sys.platform != "win32":  # pragma: no cover
        return "n/a"
    import winreg

    places = [
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + WEBVIEW2_CLIENT),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + WEBVIEW2_CLIENT),
        (winreg.HKEY_CURRENT_USER, "Software\\" + WEBVIEW2_CLIENT),
    ]
    for hive, key in places:
        try:
            with winreg.OpenKey(hive, key) as k:
                value, _ = winreg.QueryValueEx(k, "pv")
                if value and value != "0.0.0.0":
                    return str(value)
        except OSError:
            continue
    return "not found"


def setup_logging(logs_dir: Path, app_version: str, *, webview_version: str | None = None) -> RotatingFileHandler:
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs_dir / "weaksquare.log", maxBytes=2 * 1024 * 1024, backupCount=4, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log.info(
        "WeakSquare %s starting | Python %s | %s | WebView2 %s | Stockfish: not used in this version",
        app_version,
        platform.python_version(),
        platform.platform(),
        webview_version or webview2_version(),
    )
    install_crash_hooks()
    return handler


def install_crash_hooks() -> None:
    def excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        log.critical("Uncaught exception in thread %s", name, exc_info=args.exc_value or True)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
