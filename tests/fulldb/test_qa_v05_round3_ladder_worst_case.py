"""QA v0.5 round 3: ladder_preview timing on the full DB in its slower branches (v0.5-B7 fix):
a window full of wins (the exact next open level is looked up) and a recorded level that the current
filters leave empty (several levels are tried). On its own user.db, with history to hide."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, ModeFields, SessionsRepo
from weaksquare.core.clock import FixedClock
from weaksquare.core.filters import FilterSpec
from weaksquare.core.ladder import ladder_key
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef
from weaksquare.services.session import SessionService

pytestmark = pytest.mark.fulldb
WIN = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)

CASES = {
    # (spec, recorded level, results) ; window 20 of wins promotes
    "all themes, promote 2->3": (FilterSpec(order="depth_ladder"), 2, [True] * 20),
    "fork, promote 3->4": (FilterSpec(themes=("fork",), order="depth_ladder"), 3, [True] * 20),
    "mate in 2, recorded 4 (empty)": (FilterSpec(themes=("mateIn2",), order="depth_ladder"), 4, [True] * 5),
    "all themes, recorded 4, top": (FilterSpec(order="depth_ladder"), 4, [True] * 20),
}


SLOW = {"all themes, promote 2->3", "mate in 2, recorded 4 (empty)"}  # v0.5-B10 (QA round 3): ~530 / ~790 ms


@pytest.mark.parametrize(
    "name",
    [pytest.param(n, marks=pytest.mark.xfail(reason="v0.5-B10: over 500 ms", strict=False)) if n in SLOW else n
     for n in CASES],
)  # fmt: skip
def test_ladder_preview_slow_branches_are_within_target(fulldb_path: Path, tmp_path: Path, name: str) -> None:
    clock = FixedClock()
    migrate(tmp_path / "user.db", config.MIGRATIONS_DIR / "user", clock)
    source = LichessDbSource(Database(tmp_path / "user.db", fulldb_path))
    attempts = AttemptsRepo(source._db)
    sid = SessionsRepo(source._db).create("2026-01-01T00:00:00+00:00", "standard", {}, None)
    spec, level, results = CASES[name]
    with source._db.session() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM pz.puzzles LIMIT 500")]
    for i, pid in enumerate(ids):  # 500 solved puzzles to hide (Exclude solved)
        extra = ModeFields(ladder_key=ladder_key(spec), ladder_level=level) if i < len(results) else None
        win = results[i] if i < len(results) else True
        res = WIN if win else AttemptResult(False, False, False, "none", 1)
        attempts.append(PuzzleRef("lichess", pid), sid, "standard", "t", "2026-01-01T10:00:00+00:00", res, 1500,
                        None, extra)  # fmt: skip
    service = SessionService(
        source, attempts, SessionsRepo(source._db), clock, random.Random(1), mode_fields=ModeFields
    )
    t0 = time.perf_counter()
    st, levels, n = service.ladder_preview(spec)
    elapsed = time.perf_counter() - t0
    print(f"\n{name}: levels={levels} level={st.level} top={st.top} pool={n:,} {elapsed * 1000:.0f} ms")
    assert n > 0
    if name.startswith("mate in 2"):
        assert (st.level, st.top) == (2, True)
    if "promote 2->3" in name:
        assert st.level == 3
    if "promote 3->4" in name:
        assert st.level == 4 and st.top
    assert elapsed < 0.5, f"{name}: {elapsed:.3f}s"
    source._db.close_all()
