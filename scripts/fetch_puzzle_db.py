"""Download (or take a local copy of) the Lichess puzzle database and import it (FR-2.1–2.3).

A thin CLI over services/puzzle_db.py: the same code the app's Import button runs.

Usage (from the repo root):
    uv run python scripts/fetch_puzzle_db.py                  # download, verify, import (real data folder)
    uv run python scripts/fetch_puzzle_db.py --dev            # into the dev data folder
    uv run python scripts/fetch_puzzle_db.py --file PATH      # import a .csv.zst (or .csv) you already have
    uv run python scripts/fetch_puzzle_db.py --skip-if-present

WeakSquare must be closed while this runs (it replaces puzzles.db). Your attempts and settings in
user.db are never touched.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weaksquare import config  # noqa: E402
from weaksquare.adapters import instance_lock  # noqa: E402
from weaksquare.adapters.db.migrate import NewerSchemaError, migrate  # noqa: E402
from weaksquare.adapters.system_clock import SystemClock  # noqa: E402
from weaksquare.app import build_services  # noqa: E402
from weaksquare.jobs.runner import JobRunner, JobStatus  # noqa: E402


class ConsoleProgress:
    def __init__(self) -> None:
        self._last = ""

    def job_changed(self, status: JobStatus) -> None:
        pct = f"{status.progress * 100:5.1f}%" if status.progress is not None else "   … "
        line = f"\r   {pct}  {status.message}"[:110]
        if line != self._last:
            print(line.ljust(len(self._last)), end="", flush=True)
            self._last = line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", metavar="PATH", help="import this lichess_db_puzzle.csv.zst instead of downloading")
    ap.add_argument("--dev", action="store_true", help="use the dev data folder (%%LOCALAPPDATA%%\\WeakSquare-dev)")
    ap.add_argument(
        "--skip-if-present", action="store_true", help="do nothing if a puzzle database is already imported"
    )
    args = ap.parse_args()

    paths = config.resolve_paths(dev=args.dev)
    paths.ensure()
    lock = instance_lock.acquire(paths.lock_file)
    if lock is None:
        print("WeakSquare is running. Close it first, or use Import puzzles inside the app.", file=sys.stderr)
        return 1
    clock = SystemClock()
    progress = ConsoleProgress()
    runner = JobRunner(progress)
    try:
        migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock, paths.backups_dir)
        services = build_services(paths, clock, runner)
        status = services.puzzle_db.status()
        if args.skip_if_present and status.installed:
            print(f"   puzzle database already imported ({status.puzzle_count:,} puzzles); skipping")
            return 0
        print(f"   data folder: {paths.data_dir}")
        started = time.monotonic()
        job = services.puzzle_db.start_import(args.file)
        try:
            final = runner.wait(job)
        except KeyboardInterrupt:
            print("\n   cancelling…")
            runner.cancel(job)
            final = runner.wait(job)
        print()
        services.close()
        if final is None or final.state != "done":
            print(f"   import {final.state if final else 'failed'}: {final.message if final else ''}", file=sys.stderr)
            return 1
        st = build_services(paths, clock, runner).puzzle_db.status()
        print(f"   imported {st.puzzle_count:,} puzzles in {time.monotonic() - started:,.0f} s"
              + (f" (Lichess export of {st.export_date})" if st.export_date else ""))  # fmt: skip
        return 0
    except NewerSchemaError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
