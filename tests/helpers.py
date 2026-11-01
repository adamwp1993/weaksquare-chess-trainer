"""Test-side composition: builds an Api the way app.py does, with fakes where needed."""

from __future__ import annotations

import csv
import random
import shutil
from collections.abc import Callable
from pathlib import Path

from weaksquare.adapters.desktop import Desktop
from weaksquare.adapters.http import DownloadResult
from weaksquare.app import build_services
from weaksquare.bridge.api import Api
from weaksquare.config import Paths
from weaksquare.core.clock import FixedClock
from weaksquare.jobs.runner import JobRunner


class FakeDesktop(Desktop):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[Path] = []

    def open_folder(self, path: Path) -> None:
        self.opened.append(path)


def build_api(paths: Paths, clock: FixedClock, desktop: Desktop | None = None, http: object | None = None) -> Api:
    runner = JobRunner()
    services = build_services(paths, clock, runner, random.Random(1234), http=http)  # type: ignore[arg-type]
    return Api(
        paths=paths,
        desktop=desktop or FakeDesktop(),
        clock=clock,
        dev_mode=True,
        runner=runner,
        puzzle_db=services.puzzle_db,
        mixer=services.mixer,
        sessions=services.sessions,
        presets=services.presets,
    )


FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "puzzles_sample.csv"


def fixture_rows() -> list[dict[str, str]]:
    with FIXTURE_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class FakeHttp:
    """Stands in for HttpClient: serves a local file as the puzzle download, plus a sums list."""

    def __init__(self, file: Path, sha256: str, last_modified: str = "2026-10-02") -> None:
        self.file = file
        self.sha256 = sha256
        self.last_modified_date = last_modified
        self.downloads = 0

    def get_text(self, url: str) -> str:
        lines = [f"{'1' * 64}  lichess_db_eval.json.zst", f"{self.sha256}  lichess_db_puzzle.csv.zst"]
        return "\n".join(lines) + "\n"

    def last_modified(self, url: str) -> str | None:
        return self.last_modified_date

    def download(
        self,
        url: str,
        dest: Path,
        *,
        progress: Callable[[int, int | None], None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> DownloadResult:
        self.downloads += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.file, dest)
        size = dest.stat().st_size
        if progress:
            progress(size, size)
        return DownloadResult(dest, size, self.last_modified_date)

    def close(self) -> None:
        pass
