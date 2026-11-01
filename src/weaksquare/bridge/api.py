"""The JS-facing API (pywebview `js_api`). Thin: validate, delegate to services, return DTOs.

pywebview exposes every public method and every public nested object to JavaScript, so all
dependencies live in underscore attributes, and every public method is wrapped by `@bridge_call`.
`tests/contract/test_bridge_allowlist.py` pins the exact set of public names: adding a method
means updating that allowlist in the same commit (ARCHITECTURE §3 decision 13).
"""

from __future__ import annotations

import logging
from typing import Literal

from weaksquare.adapters.desktop import Desktop
from weaksquare.bridge.dto import AppInfo
from weaksquare.bridge.errors import bridge_call
from weaksquare.config import APP_VERSION, LICENSE_NAME, REPO_URL, Paths
from weaksquare.core.clock import Clock

log = logging.getLogger("weaksquare.frontend")

FRONTEND_ERRORS_PER_MINUTE = 20


class Api:
    def __init__(self, *, paths: Paths, desktop: Desktop, clock: Clock, dev_mode: bool) -> None:
        self._paths = paths
        self._desktop = desktop
        self._clock = clock
        self._dev_mode = dev_mode
        self._fe_window_start = 0
        self._fe_count = 0

    @bridge_call
    def get_app_info(self) -> AppInfo:
        return AppInfo(
            version=APP_VERSION,
            data_dir=str(self._paths.data_dir),
            logs_dir=str(self._paths.logs_dir),
            dev_mode=self._dev_mode,
            license=LICENSE_NAME,
            source_url=REPO_URL,
            puzzle_db_export_date=None,
            puzzle_count=None,
        )

    @bridge_call
    def open_folder(self, kind: Literal["data", "logs"]) -> None:
        self._desktop.open_folder(self._paths.data_dir if kind == "data" else self._paths.logs_dir)

    @bridge_call
    def log_frontend_error(self, message: str, source: str) -> None:
        """Front-end errors (window.onerror, unhandled rejections), rate-limited (NFR-4)."""
        now = self._clock.monotonic_ms()
        if now - self._fe_window_start > 60_000:
            self._fe_window_start, self._fe_count = now, 0
        self._fe_count += 1
        if self._fe_count <= FRONTEND_ERRORS_PER_MINUTE:
            log.error("front end [%s]: %s", source[:200], message[:2000])
        elif self._fe_count == FRONTEND_ERRORS_PER_MINUTE + 1:
            log.error("front end: more errors this minute were dropped")
