"""Everything that crosses to JavaScript (ARCHITECTURE §3 decision 8).

`web/src/api/types.ts` is generated from this module by `scripts/gen_types.py`; a contract test
fails if the two drift. Only the classes in EXPORTED are generated, in that order. Never put a
secret in a DTO (SR-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class AppInfo:
    version: str
    data_dir: str
    logs_dir: str
    dev_mode: bool
    license: str
    source_url: str
    puzzle_db_export_date: str | None
    puzzle_count: int | None


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    state: Literal["running", "done", "failed", "cancelled"]
    progress: float | None
    message: str
    error_code: str | None


@dataclass(frozen=True)
class PuzzleDbStatus:
    installed: bool
    puzzle_count: int | None
    export_date: str | None
    imported_at: str | None
    rating_min: int | None
    rating_max: int | None
    import_job_id: str | None


EXPORTED: list[type] = [ApiError, AppInfo, Job, PuzzleDbStatus]
