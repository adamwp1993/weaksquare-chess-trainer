"""Download, verify and import the Lichess puzzle database as a background job (FR-2.1–2.3, SR-6).

The import always builds a new `puzzles.new.db` and swaps it in only after the row-count and
integrity checks pass. Cancelling or failing at any point deletes the new file and leaves the
current `puzzles.db` (and all user data) untouched. Downloads resume; the import restarts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from weaksquare.core.checksums import find_sha256
from weaksquare.core.clock import Clock
from weaksquare.core.csv_rows import HeaderError, PuzzleRow, header_index, parse_row
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "puzzle_import"
DOWNLOAD_NAME = "lichess_db_puzzle.csv.zst"
BATCH = 20_000
MAX_SKIPPED_SHARE = 0.01


# ---- what this service needs from adapters -------------------------------------------------
class Downloader(Protocol):
    def get_text(self, url: str) -> str: ...

    def last_modified(self, url: str) -> str | None: ...

    def download(
        self,
        url: str,
        dest: Path,
        *,
        progress: Callable[[int, int | None], None] | None = None,
        cancelled: Callable[[], bool] = ...,
    ) -> DownloadInfo: ...


class DownloadInfo(Protocol):
    @property
    def last_modified(self) -> str | None: ...


class CsvSource(Protocol):
    def fraction(self) -> float: ...

    def rows(self) -> object: ...  # context manager yielding an iterator of rows


class Writer(Protocol):
    rows_written: int

    def open(self) -> None: ...

    def add(self, rows: list[PuzzleRow]) -> None: ...

    def finish(self, meta: dict[str, str]) -> object: ...

    def discard(self) -> None: ...


@dataclass(frozen=True)
class PuzzleDbStatus:
    installed: bool
    puzzle_count: int | None
    export_date: str | None
    imported_at: str | None
    rating_min: int | None
    rating_max: int | None
    import_job_id: str | None


@dataclass(frozen=True)
class ImportDeps:
    puzzles_db: Path
    new_db: Path
    downloads_dir: Path
    db_url: str
    sums_url: str
    http: Downloader
    open_csv: Callable[[Path], CsvSource]
    make_writer: Callable[[Path], Writer]
    sha256: Callable[[Path, Callable[[], bool]], str]
    swap: Callable[[Path], None]
    read_meta: Callable[[], dict[str, str] | None]


class PuzzleDbService:
    def __init__(self, deps: ImportDeps, runner: JobRunner, clock: Clock) -> None:
        self._d = deps
        self._runner = runner
        self._clock = clock

    # ---- queries ------------------------------------------------------------------------------
    def status(self) -> PuzzleDbStatus:
        meta = self._d.read_meta() or {}
        active = self._runner.active(JOB_KIND)

        def num(key: str) -> int | None:
            return int(meta[key]) if key in meta else None

        return PuzzleDbStatus(
            installed=bool(meta),
            puzzle_count=num("row_count"),
            export_date=meta.get("export_date"),
            imported_at=meta.get("imported_at"),
            rating_min=num("rating_min"),
            rating_max=num("rating_max"),
            import_job_id=active[0].id if active else None,
        )

    # ---- commands ------------------------------------------------------------------------------
    def start_import(self, local_file: str | None = None) -> str:
        if self._runner.active(JOB_KIND):
            raise ConflictError("A puzzle import is already running.")
        source = None
        if local_file is not None:
            source = Path(local_file)
            if not source.is_file():
                raise ValidationError("That file doesn't exist.")
            if not source.name.lower().endswith((".csv.zst", ".csv")):
                raise ValidationError("Choose the Lichess puzzle export: a .csv.zst (or unpacked .csv) file.")
        return self._runner.submit(JOB_KIND, lambda progress, token: self.run(progress, token, source))

    # ---- the job ---------------------------------------------------------------------------------
    def run(self, progress: ProgressFn, token: CancelToken, local_file: Path | None) -> None:
        if local_file is None:
            path, meta = self._fetch(lambda f, msg: progress(None if f is None else f * 0.4, msg), token)
            import_from, import_span = 0.4, 0.5
        else:
            path, meta = local_file, {"source": "local file"}
            import_from, import_span = 0.0, 0.9
        self._import(path, meta, progress, token, import_from, import_span)
        if local_file is None:
            path.unlink(missing_ok=True)  # only after a successful import; a restart reuses it
            self._sidecar(path).unlink(missing_ok=True)

    @staticmethod
    def _sidecar(path: Path) -> Path:
        return path.with_name(path.name + ".json")

    def _fetch(self, progress: ProgressFn, token: CancelToken) -> tuple[Path, dict[str, str]]:
        d = self._d
        dest = d.downloads_dir / DOWNLOAD_NAME
        progress(None, "Checking the published checksum…")
        try:
            expected = find_sha256(d.http.get_text(d.sums_url), DOWNLOAD_NAME)
        except Exception as e:
            raise JobFailed("network", f"Couldn't reach database.lichess.org ({e}). Check your connection.") from None
        if expected is None:
            log.warning("no published SHA-256 for %s; continuing without a hash check", DOWNLOAD_NAME)

        sidecar = self._sidecar(dest)
        export_date = None
        reuse = dest.is_file() and expected is not None and self._hash(dest, token, progress) == expected
        if reuse:
            if sidecar.is_file():
                export_date = json.loads(sidecar.read_text()).get("export_date")
            else:
                try:
                    export_date = d.http.last_modified(d.db_url)
                except Exception:
                    export_date = None
            log.info("reusing the already downloaded %s", DOWNLOAD_NAME)
        else:
            dest.unlink(missing_ok=True)

            def on_bytes(done: int, total: int | None) -> None:
                frac = done / total if total else None
                mb = done / 1_048_576
                progress(None if frac is None else frac * 0.9, f"Downloading the puzzle database… {mb:,.0f} MB")

            try:
                result = d.http.download(d.db_url, dest, progress=on_bytes, cancelled=lambda: token.cancelled)
            except Exception as e:
                token.raise_if_cancelled()
                raise JobFailed("download_failed", f"The download failed: {e}. Try again to resume it.") from None
            token.raise_if_cancelled()
            export_date = result.last_modified
            sidecar.write_text(json.dumps({"export_date": export_date}))
            if expected is not None:
                actual = self._hash(dest, token, progress)
                if actual != expected:
                    dest.unlink(missing_ok=True)
                    sidecar.unlink(missing_ok=True)
                    raise JobFailed(
                        "checksum_mismatch",
                        "The downloaded file doesn't match the checksum Lichess publishes, so it was deleted. "
                        "Try again later (Lichess may be mid-update).",
                    )
        meta = {"source": d.db_url}
        if export_date:
            meta["export_date"] = export_date
        if expected:
            meta["sha256"] = expected
        return dest, meta

    def _hash(self, path: Path, token: CancelToken, progress: ProgressFn) -> str:
        progress(0.95, "Verifying the download…")
        try:
            return self._d.sha256(path, lambda: token.cancelled)
        except Exception:
            token.raise_if_cancelled()
            raise

    def _import(
        self,
        path: Path,
        meta: dict[str, str],
        progress: ProgressFn,
        token: CancelToken,
        start: float,
        span: float,
    ) -> None:
        d = self._d
        writer = d.make_writer(d.new_db)
        csv_source = d.open_csv(path)
        skipped = 0
        try:
            writer.open()
            with csv_source.rows() as rows:  # type: ignore[attr-defined]
                try:
                    index = header_index(next(rows))
                except (StopIteration, HeaderError) as e:
                    raise JobFailed("bad_file", f"That isn't a Lichess puzzle export: {e}", retryable=False) from None
                batch: list[PuzzleRow] = []
                for raw in rows:
                    parsed = parse_row(index, raw)
                    if parsed is None:
                        skipped += 1
                        continue
                    batch.append(parsed)
                    if len(batch) >= BATCH:
                        token.raise_if_cancelled()
                        writer.add(batch)
                        batch = []
                        progress(
                            start + span * csv_source.fraction(),
                            f"Importing puzzles… {writer.rows_written:,}",
                        )
                if batch:
                    writer.add(batch)
            token.raise_if_cancelled()
            total = writer.rows_written + skipped
            if writer.rows_written == 0 or skipped > total * MAX_SKIPPED_SHARE + 10:
                raise JobFailed(
                    "bad_file", f"Too many unreadable rows ({skipped:,} of {total:,}). Is the file complete?"
                )
            progress(start + span, "Building indexes (this takes a minute)…")
            writer.finish({**meta, "skipped_rows": str(skipped)})
            token.raise_if_cancelled()
            progress(0.99, "Switching to the new database…")
            d.swap(d.new_db)
            log.info("puzzle import finished: %d puzzles, %d skipped rows", writer.rows_written, skipped)
        except JobCancelled:
            writer.discard()
            raise
        except JobFailed:
            writer.discard()
            raise
        except ValueError as e:
            writer.discard()
            raise JobFailed("bad_file", f"The file couldn't be read: {e}", retryable=False) from None
        except Exception:
            writer.discard()
            raise
