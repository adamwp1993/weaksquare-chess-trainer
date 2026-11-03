"""QA v0.5 round 2: stricter checks of the round-1 fixes over the bridge (fixture DB, real user.db)."""

from __future__ import annotations

from typing import Any

from tests.integration.test_qa_v05_edges import OPEN, api, err, line_of, ok, solve  # noqa: F401

MATE2 = {**OPEN, "themes": ["mateIn2"], "order": "depth_ladder"}


def test_b2_mate_in_two_short_is_the_top_and_the_session_carries_on(api: Any) -> None:  # noqa: F811
    ok(api.set_setting("ladder.window", 3))
    ok(api.set_setting("ladder.threshold", 60))
    preview = ok(api.get_ladder_status(MATE2))
    assert (preview["ladder"]["level"], preview["ladder"]["top"]) == (2, True)
    assert preview["match_count"] > 0
    sid = ok(api.start_session(MATE2))["session_id"]
    for _ in range(4):
        assert ok(api.next_puzzle(sid)) is not None  # never ends early
        assert solve(api, sid)["level_up"] is None  # nowhere to climb
    stats = ok(api.get_session_stats(sid))["ladder"]
    assert (stats["level"], stats["top"]) == (2, True)
    assert ok(api.count_matches(MATE2)) == preview["match_count"] - 4  # the 4 solved drop out (Exclude solved)


def test_b2_mate_in_one_ladder_still_refuses_to_start_with_a_reason(api: Any) -> None:  # noqa: F811
    spec = {**OPEN, "themes": ["mateIn1"], "order": "depth_ladder"}
    assert ok(api.count_matches(spec)) == 0
    assert err(api.start_session(spec)) == "invalid_argument"


def test_b3_hidden_cap_is_60_for_every_puzzle(api: Any) -> None:  # noqa: F811
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    caps = set()
    for _ in range(5):
        caps.add(ok(api.next_puzzle(sid))["max_plies"])
    assert caps == {60}
    sid2 = ok(api.start_session(OPEN, True, "commit_line", True))["session_id"]
    v = ok(api.next_puzzle(sid2))
    assert v["max_plies"] == v["solution_plies"] == len(line_of(api, sid2)) - 1
