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
        self.urls: list[str] = []
        self.next_file: str | None = None  # v0.8: what the Open dialogs return

    def open_folder(self, path: Path) -> None:
        self.opened.append(path)

    def open_in_browser(self, url: str) -> None:
        self.urls.append(url)

    def choose_pgn_file(self) -> str | None:
        return self.next_file

    def choose_puzzle_import_file(self) -> str | None:
        return self.next_file


def fake_service_kwargs(lichess: object | None = None) -> dict:
    """Fakes for everything that would reach Lichess, Credential Manager, a timer thread or an engine."""
    from tests.fakes.desktop import FakeBrowser, FakeScheduler
    from tests.fakes.engine import FakeEngine, fake_probe
    from tests.fakes.games import FakeChesscom, FakeLichessGames
    from tests.fakes.lichess import FakeLichess
    from tests.fakes.llm import fake_providers
    from weaksquare.adapters.secret_store import MemorySecretStore

    return {
        "secrets": MemorySecretStore(),
        "lichess": lichess or FakeLichess(),
        "scheduler": FakeScheduler(),
        "browser": FakeBrowser(),
        "make_engine": FakeEngine,  # never a real process: tests that want one build it themselves
        "engine_probe": fake_probe,
        "cpu_count": 8,
        "llm_providers": fake_providers(),  # never the real Anthropic or OpenAI
        "lichess_games": FakeLichessGames(),  # never the real Lichess or chess.com (v0.8)
        "chesscom": FakeChesscom(),
    }


def build_api(
    paths: Paths,
    clock: FixedClock,
    desktop: Desktop | None = None,
    http: object | None = None,
    lichess: object | None = None,
) -> Api:
    runner = JobRunner()
    services = build_services(paths, clock, runner, random.Random(1234), http=http,  # type: ignore[arg-type]
                              **fake_service_kwargs(lichess))  # fmt: skip
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
        games=services.games,
        analysis=services.analysis,
        review=services.review,
        puzzle_import=services.puzzle_import,
        game_explain=services.game_explain,
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
