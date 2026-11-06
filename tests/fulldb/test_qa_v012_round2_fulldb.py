"""QA v0.12 round 2 on the full puzzle DB, read-only with a throwaway user.db: Swap and the plan's puzzle checks have
real puzzle counts to work with here (the fixture DB is small, so most tasks fall back to general puzzles)."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.engine import plant_managed_install
from tests.helpers import FakeDesktop, build_api
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_qa_v011_coach import _games
from tests.integration.test_qa_v012_plan import EVERY_DAY, _ok, _svc
from weaksquare.adapters.db.migrate import migrate
from weaksquare.bridge.api import Api
from weaksquare.config import MIGRATIONS_DIR, Paths

pytestmark = pytest.mark.fulldb


@dataclass(frozen=True)
class _FullPaths(Paths):
    full: Path = Path()

    @property
    def puzzles_db(self) -> Path:
        return self.full


@pytest.fixture
def api(paths: Any, clock: Any, fulldb_path: Path) -> Api:
    p = _FullPaths(paths.data_dir, fulldb_path)
    migrate(p.user_db, MIGRATIONS_DIR / "user", clock)
    return build_api(p, clock, FakeDesktop())


def test_qa2_swap_chain_on_the_full_db_moves_on_and_never_doubles(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _games(_svc(api), 6)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    plan = _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))
    n = len(plan["days"][0]["tasks"])
    chains: list[list[str]] = []
    doubled: list[list[str]] = []
    for k in range(n):
        current = _ok(api.get_current_plan())["days"][0]["tasks"][k]
        seen, tid = [current["title"]], current["id"]
        for _ in range(12):
            tid = _ok(api.swap_plan_task(tid))
            day = _ok(api.get_current_plan())["days"][0]["tasks"]
            titles = [t["title"] for t in day]
            if len(titles) != len(set(titles)):
                doubled.append(titles)
            assert sum(t["minutes"] for t in day) == 40
            seen.append(next(t for t in day if t["id"] == tid)["title"])
        chains.append(seen)
    for seen in chains:
        # Three different tasks before anything repeats, and no bouncing between two: B11 holds here.
        assert len(set(seen[:3])) == 3, seen
        assert not any(seen[i] == seen[i + 2] != seen[i + 1] for i in range(len(seen) - 2)), seen
    assert doubled == []  # never the same task twice on a day
    assert all(a != b for seen in chains for a, b in itertools.pairwise(seen)), chains  # a Swap always changes


def test_qa2_preview_and_reads_stay_fast_with_the_puzzle_check(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    _games(_svc(api), 6)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    t0 = time.perf_counter()
    _ok(api.preview_plan({"weeks": 4, "weekdays": EVERY_DAY, "minutes": 120}))
    took = time.perf_counter() - t0
    assert took < 30
