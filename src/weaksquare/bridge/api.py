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
from weaksquare.bridge.dto import AppInfo, Job, PuzzleDbStatus
from weaksquare.bridge.errors import bridge_call
from weaksquare.bridge.events import job_dto
from weaksquare.config import APP_VERSION, LICENSE_NAME, REPO_URL, Paths
from weaksquare.core.clock import Clock
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.puzzle_db import PuzzleDbService

log = logging.getLogger("weaksquare.frontend")

FRONTEND_ERRORS_PER_MINUTE = 20


class Api:
    def __init__(
        self,
        *,
        paths: Paths,
        desktop: Desktop,
        clock: Clock,
        dev_mode: bool,
        runner: JobRunner,
        puzzle_db: PuzzleDbService,
    ) -> None:
        self._paths = paths
        self._runner = runner
        self._puzzle_db = puzzle_db
        self._desktop = desktop
        self._clock = clock
        self._dev_mode = dev_mode
        self._fe_window_start = 0
        self._fe_count = 0

    @bridge_call
    def get_app_info(self) -> AppInfo:
        status = self._puzzle_db.status()
        return AppInfo(
            version=APP_VERSION,
            data_dir=str(self._paths.data_dir),
            logs_dir=str(self._paths.logs_dir),
            dev_mode=self._dev_mode,
            license=LICENSE_NAME,
            source_url=REPO_URL,
            puzzle_db_export_date=status.export_date,
            puzzle_count=status.puzzle_count,
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

    # ---- puzzle database (FR-2.1–2.3) -------------------------------------------------------
    @bridge_call
    def get_puzzle_db_status(self) -> PuzzleDbStatus:
        s = self._puzzle_db.status()
        return PuzzleDbStatus(
            s.installed, s.puzzle_count, s.export_date, s.imported_at, s.rating_min, s.rating_max, s.import_job_id
        )

    @bridge_call
    def choose_puzzle_file(self) -> str | None:
        return self._desktop.choose_puzzle_file()

    @bridge_call
    def start_puzzle_import(self, local_path: str | None = None) -> str:
        """Start the import job: download from Lichess, or import `local_path`. Returns the job ID."""
        if local_path is not None and (len(local_path) > 1000 or chr(0) in local_path):
            raise ValidationError("That isn't a valid file path.")
        return self._puzzle_db.start_import(local_path)

    # ---- jobs -----------------------------------------------------------------------------------
    @bridge_call
    def get_job(self, job_id: str) -> Job:
        status = self._runner.status(job_id)
        if status is None:
            raise NotFoundError("No such job.")
        return job_dto(status)

    @bridge_call
    def cancel_job(self, job_id: str) -> bool:
        return self._runner.cancel(job_id)
