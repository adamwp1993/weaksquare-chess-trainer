"""QA v0.5 round 3: the fast ladder preview (v0.5-B7 fix) must decide exactly what the round-2 rule does
with a full count per level. Reference = core.ladder.status over every level that has puzzles, plus the
pool count at the chosen level; compared over filter shapes x recorded histories (fixture DB)."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from tests.integration.test_qa_v05_edges import OPEN, api, ok, solve  # noqa: F401
from weaksquare.adapters.db.repos.user_data import ModeFields
from weaksquare.core.filters import FilterSpec
from weaksquare.core.ladder import LEVELS, ladder_key
from weaksquare.core.ladder import status as core_status
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef

SPECS = [
    FilterSpec(order="depth_ladder", min_popularity=None, min_plays=None, exclude_played_on_lichess=False),
    FilterSpec(order="depth_ladder"),  # defaults: quality + exclude solved
    FilterSpec(themes=("fork",), order="depth_ladder", min_popularity=None, min_plays=None),
    FilterSpec(themes=("fork", "pin"), match="all", order="depth_ladder", min_popularity=None, min_plays=None),
    FilterSpec(themes=("mateIn2",), order="depth_ladder", min_popularity=None, min_plays=None),
    FilterSpec(themes=("mateIn1",), order="depth_ladder"),
    FilterSpec(themes=("fork",), rating_min=2000, rating_max=2400, side="black", order="depth_ladder"),
    FilterSpec(rating_min=600, rating_max=900, order="depth_ladder", min_popularity=None, min_plays=None),
    FilterSpec(only_my_misses=True, order="depth_ladder", min_popularity=None, min_plays=None),
]
HISTORIES = [None, (2, "wins"), (2, "mixed"), (3, "wins"), (3, "mixed"), (4, "wins")]


def _result(win: bool) -> AttemptResult:
    return AttemptResult(win=win, first_move_correct=win, line_correct=win, help_used="none", time_ms=1)


def reference(app: Any, spec: FilterSpec) -> tuple[Any, int]:
    s = app._sessions
    src = s._puzzles
    window, threshold = s._prefs.ladder_window(), s._prefs.ladder_threshold()
    recorded, recent = s._attempts.ladder_history(ladder_key(spec), window)
    levels = [lv for lv in LEVELS if src.count(spec.at_ladder_level(lv)) > 0]
    st = core_status(ladder_key(spec), recorded, recent, threshold, window, levels)
    return st, (src.count(spec.at_ladder_level(st.level)) if levels else 0)


@pytest.mark.parametrize(("si", "hi"), list(itertools.product(range(len(SPECS)), range(len(HISTORIES)))))
def test_fast_preview_matches_the_full_count_rule(api: Any, si: int, hi: int) -> None:  # noqa: F811
    ok(api.set_setting("ladder.window", 3))
    ok(api.set_setting("ladder.threshold", 60))
    # some real history first, so Exclude solved / Only my misses hide something
    sid = ok(api.start_session(OPEN))["session_id"]
    for _ in range(2):
        ok(api.next_puzzle(sid))
        solve(api, sid)
    ok(api.next_puzzle(sid))
    ok(api.next_puzzle(sid))  # a miss
    spec = SPECS[si]
    hist = HISTORIES[hi]
    if hist is not None:
        level, kind = hist
        results = [True, True, True] if kind == "wins" else [True, False, False]
        repo = api._sessions._attempts
        for i, win in enumerate(results):
            repo.append(PuzzleRef("lichess", f"QAX{i}"), sid, "standard", "t", "2026-01-01T12:00:00+00:00",
                        _result(win), 1500, None, ModeFields(ladder_key=ladder_key(spec), ladder_level=level))  # fmt: skip
    fast, levels, n = api._sessions.ladder_preview(spec)
    ref, ref_n = reference(api, spec)
    if ref_n == 0:  # nothing to play at any level: only the level and the 0 matter (the window isn't shown usefully)
        assert (fast.level, n) == (ref.level, 0)
        return
    assert (fast.level, fast.top, fast.played, fast.wins, n) == (ref.level, ref.top, ref.played, ref.wins, ref_n), (
        spec, hist, levels,
    )  # fmt: skip
    assert ok(api.count_matches(spec.to_json())) == n
    preview = ok(api.get_ladder_status(spec.to_json()))
    assert (preview["ladder"]["level"], preview["ladder"]["top"], preview["match_count"]) == (fast.level, fast.top, n)
