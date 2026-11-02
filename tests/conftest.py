"""Shared fixtures. Every test runs with a temp data folder (NFR-2), a fixed clock and a seeded rng."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.core.clock import FixedClock


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv(config.DATA_DIR_ENV, str(data))
    return data


@pytest.fixture
def paths(temp_data_dir: Path) -> config.Paths:
    p = config.resolve_paths(dev=True)
    p.ensure()
    return p


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)


@pytest.fixture(scope="session")
def fixture_puzzles_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The anonymized fixture CSV imported once into a puzzles.db (the same code path as the app)."""
    import csv

    from weaksquare.adapters.db.repos.puzzle_import import PuzzleDbWriter
    from weaksquare.core.csv_rows import header_index, parse_row

    out = tmp_path_factory.mktemp("puzzles") / "puzzles.db"
    writer = PuzzleDbWriter(out, FixedClock())
    writer.open()
    src = Path(__file__).resolve().parent / "fixtures" / "puzzles_sample.csv"
    with src.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        idx = header_index(next(reader))
        writer.add([r for r in (parse_row(idx, row) for row in reader) if r is not None])
    writer.finish({"export_date": "2026-10-02", "source": "fixture"})
    return out


@pytest.fixture
def services(paths: config.Paths, clock: FixedClock, rng: random.Random, fixture_puzzles_db: Path):  # type: ignore[no-untyped-def]
    """Fully wired services on a temp data folder with the fixture puzzles imported."""
    import shutil

    from tests.helpers import fake_service_kwargs
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.app import build_services
    from weaksquare.jobs.runner import JobRunner

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    s = build_services(paths, clock, JobRunner(), rng, **fake_service_kwargs())
    yield s
    s.close()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--fulldb-path",
        default=None,
        help="puzzles.db for -m fulldb (default: the dev data folder's, read-only)",
    )


@pytest.fixture(scope="session")
def pw():  # type: ignore[no-untyped-def]
    """One sync Playwright for the whole run: e2e and smoke tests share it (two can't coexist)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as instance:
        yield instance
