"""QA v0.5 round 2: the B2 fix adds one count per ladder level to every ladder preview and start.
Time the whole preview path (levels + pool) for the filter shapes the mixer sends most."""

from __future__ import annotations

import random
import time

import pytest

from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, ModeFields, SessionsRepo
from weaksquare.core.clock import FixedClock
from weaksquare.core.filters import FilterSpec
from weaksquare.services.session import SessionService

pytestmark = pytest.mark.fulldb

SPECS = {
    "all themes, defaults": FilterSpec(order="depth_ladder", min_popularity=50, min_plays=100),
    "all themes, open": FilterSpec(order="depth_ladder", min_popularity=None, min_plays=None),
    "fork+pin ALL": FilterSpec(themes=("fork", "pin"), match="all", order="depth_ladder"),
    "mate in 2": FilterSpec(themes=("mateIn2",), order="depth_ladder"),
    "narrow rating": FilterSpec(themes=("skewer",), rating_min=2400, rating_max=2500, order="depth_ladder"),
}


@pytest.mark.parametrize("name", list(SPECS))
def test_ladder_preview_with_level_counts_is_fast(full_source: LichessDbSource, name: str) -> None:
    service = SessionService(full_source, AttemptsRepo(full_source._db), SessionsRepo(full_source._db),
                             FixedClock(), random.Random(5), mode_fields=ModeFields)  # fmt: skip
    spec = SPECS[name]
    t0 = time.perf_counter()
    st, levels, n = service.ladder_preview(spec)  # the whole live-count request (v0.5-B7 fix)
    elapsed = time.perf_counter() - t0
    print(f"\n{name}: levels={levels} level={st.level} top={st.top} pool={n:,} {elapsed * 1000:.0f} ms")
    assert n > 0 or not levels
    if name == "mate in 2":
        assert levels == [2] and st.top
    assert elapsed < 0.5, f"{name}: {elapsed:.3f}s (the live-count target is 500 ms)"
