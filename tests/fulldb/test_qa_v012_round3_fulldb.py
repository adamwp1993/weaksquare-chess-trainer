"""QA v0.12 round 3 on the full puzzle DB, read-only with a throwaway user.db: how long a Swap takes now that it checks
every choice against the puzzle DB, and that a pool task really finds puzzles there."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.engine import plant_managed_install
from tests.fulldb.test_qa_v012_round2_fulldb import api  # noqa: F401
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_qa_v011_coach import _games
from tests.integration.test_qa_v012_plan import EVERY_DAY, _ok, _svc
from weaksquare.bridge.api import Api

pytestmark = pytest.mark.fulldb
ART = Path("tests/e2e/artifacts")


def test_qa3_a_swap_stays_quick_on_the_full_db_and_every_pool_task_starts(api: Api, paths: Any) -> None:  # noqa: F811
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _games(_svc(api), 6)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    plan = _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))
    tid = plan["days"][0]["tasks"][0]["id"]
    times: list[float] = []
    modes: set[Any] = set()
    for _ in range(25):
        start = time.perf_counter()
        tid = _ok(api.swap_plan_task(tid))
        times.append(time.perf_counter() - start)
        got = _ok(api.start_plan_task(tid, False))
        if got["kind"] == "session":
            assert got["session"]["match_count"] > 0
            modes.add(got["mode"])
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "qa-v012-r3-swap-times.txt").write_text(
        f"max {max(times):.2f} s, all {[round(t, 2) for t in times]}\n", encoding="utf-8"
    )
    assert {"standard", "commit_line", "name_idea"} <= modes, modes
    assert max(times) < 3.0, times
