"""Import puzzles from your own files (v0.8, REQUIREMENTS §10.10, FR-10.46–10.50).

The file is read on this PC and never sent anywhere (FR-10.50). The import runs as a job with progress
and cancel (before anything is saved): it parses and validates every entry (`core.puzzle_files`), stores the good ones in
`custom_puzzles` with `origin = import`, the set label and strict checking (FR-10.49), and keeps a
report (entry number and reason for each skipped entry). Re-importing the same file adds nothing twice:
one puzzle per set, position and solution (FR-10.48). The app ships, links to and downloads no puzzle
collections.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.puzzle import NewCustomPuzzle
from weaksquare.core.puzzle_files import (
    MAX_FILE_BYTES,
    EntryError,
    FileError,
    ImportedPuzzle,
    parse_puzzle_file,
    validate_label,
)
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

JOB_KIND = "puzzle_file_import"
MAX_REPORTED = 500  # skipped entries listed in the report; the count is always exact


class Store(Protocol):
    def add_many(self, items: list[NewCustomPuzzle], created_at: str) -> int: ...

    def sets(self) -> list[tuple[str, int]]: ...


@dataclass(frozen=True)
class ImportReport:
    label: str
    file_name: str
    format: str
    entries: int
    added: int
    duplicates: int
    skipped: int
    errors: tuple[EntryError, ...]  # the first MAX_REPORTED skipped entries


class PuzzleImportService:
    def __init__(self, store: Store, runner: JobRunner, clock: Clock) -> None:
        self._store = store
        self._runner = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._reports: dict[str, ImportReport] = {}
        self._tickets: dict[str, str] = {}
        self._next = 0

    def sets(self) -> list[tuple[str, int]]:
        return self._store.sets()

    def start_import(self, path: Path, label: str) -> str:
        try:
            clean = validate_label(label)
        except ValueError as e:
            raise ValidationError(str(e)) from None
        try:
            size = path.stat().st_size
        except OSError:
            raise NotFoundError("That file can't be opened.") from None
        if size > MAX_FILE_BYTES:
            raise ValidationError(f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        with self._lock:
            self._next += 1
            ticket = f"import-{self._next}"

        def run(progress: ProgressFn, cancel: CancelToken) -> str:
            report = self._run(path, clean, progress, cancel)
            with self._lock:
                self._reports[ticket] = report
            return f"{report.added} added, {report.duplicates} already there, {report.skipped} skipped"

        job_id = self._runner.submit(JOB_KIND, run)
        with self._lock:
            self._tickets[job_id] = ticket
        return job_id

    def report(self, job_id: str) -> ImportReport | None:
        with self._lock:
            ticket = self._tickets.get(job_id)
            return self._reports.get(ticket) if ticket else None

    def _run(self, path: Path, label: str, progress: ProgressFn, cancel: CancelToken) -> ImportReport:
        progress(None, "Reading the file…")
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            raise JobFailed("unreadable", "That file can't be read.", retryable=False) from None
        try:
            fmt, entries = parse_puzzle_file(path.name, text)
        except FileError as e:
            raise JobFailed("bad_file", e.reason, retryable=False) from None
        good = [e for e in entries if isinstance(e, ImportedPuzzle)]
        bad = [e for e in entries if isinstance(e, EntryError)]
        now = self._clock.now().astimezone(UTC).isoformat(timespec="seconds")
        items = [
            NewCustomPuzzle(
                fen=p.fen,
                solution=p.solution,
                player_color=p.player_color,
                origin="import",
                strict=True,
                set_label=label,
                name=p.name,
            )
            for p in good
        ]
        cancel.raise_if_cancelled()
        progress(0.9, f"Saving {len(items):,} puzzles…")
        added = self._store.add_many(items, now)  # one transaction: a cancelled import leaves nothing behind
        return ImportReport(
            label=label,
            file_name=path.name,
            format=fmt,
            entries=len(entries),
            added=added,
            duplicates=len(good) - added,
            skipped=len(bad),
            errors=tuple(bad[:MAX_REPORTED]),
        )
