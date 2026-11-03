"""v0.5 training modes over the bridge, with a real user.db and the fixture puzzles: Spaced repetition
(FR-4.6), Commit the line (FR-4.2), the depth-ladder order (FR-4.5), mode switching (§6) and the new
settings."""

from __future__ import annotations

import shutil
import sqlite3
from typing import Any

import pytest

from tests.helpers import build_api
from weaksquare.core.clock import FixedClock

OPEN = {"min_popularity": None, "min_plays": None, "exclude_played_on_lichess": False, "queue_size": 20}


@pytest.fixture
def api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    return build_api(paths, clock)


def ok(r: dict[str, Any]) -> Any:
    assert r["ok"], r
    return r["data"]


def err(r: dict[str, Any]) -> str:
    assert not r["ok"], r
    return str(r["error"]["code"])


def moves(api: Any, sid: int) -> list[str]:
    s = api._sessions._session(sid)
    with s.lock:
        return list(s.current.state.puzzle.moves)


def solve(api: Any, sid: int) -> dict[str, Any]:
    """Play the solution's player moves; returns the outcome."""
    line = moves(api, sid)
    outcome = None
    for uci in line[1::2]:
        fb = ok(api.submit_move(sid, uci))
        outcome = fb["outcome"] or outcome
        if fb["finished"]:
            break
    assert outcome is not None
    return outcome


def rows(paths: Any, sql: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(paths.user_db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---- Spaced repetition (FR-4.6) ---------------------------------------------------------------------


def test_a_miss_comes_back_the_next_day_and_climbs_a_box(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    missed = ok(api.next_puzzle(sid))["puzzle_id"]
    ok(api.next_puzzle(sid))  # skipping an undecided puzzle records it as a loss

    status = ok(api.get_srs_status())
    assert (status["due"], status["next_due"], status["scheduled"]) == (0, "2026-01-02", 1)
    assert err(api.start_session(OPEN, True, "spaced_repetition")) == "invalid_argument"

    clock.advance(days=1)
    assert ok(api.get_srs_status())["due"] == 1
    info = ok(api.start_session({"queue_size": 20}, True, "spaced_repetition"))
    assert (info["mode"], info["match_count"]) == ("spaced_repetition", 1)
    view = ok(api.next_puzzle(info["session_id"]))
    assert (view["puzzle_id"], view["mode"]) == (missed, "spaced_repetition")
    assert solve(api, info["session_id"])["win"]
    assert ok(api.next_puzzle(info["session_id"])) is None  # only what's due

    status = ok(api.get_srs_status())
    assert (status["due"], status["next_due"]) == (0, "2026-01-05")  # box 2: three days later
    assert rows(paths, "SELECT mode, win, angle FROM attempts ORDER BY id DESC LIMIT 1") == [
        ("spaced_repetition", 1, "mix")
    ]


def test_srs_ignores_the_filters(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    ok(api.next_puzzle(sid))
    clock.advance(days=1)
    # Filters nothing could match: the due puzzle is still served.
    info = ok(api.start_session({"rating_min": 3900, "queue_size": 5}, True, "spaced_repetition"))
    assert ok(api.next_puzzle(info["session_id"])) is not None


# ---- Commit the line (FR-4.2) -----------------------------------------------------------------------


def test_commit_the_line_grades_and_records_calculation_accuracy(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    view = ok(api.next_puzzle(sid))
    assert view["mode"] == "commit_line" and view["solution_plies"] is None  # hidden by default
    line = moves(api, sid)[1:]
    assert view["max_plies"] >= len(line)
    assert err(api.submit_move(sid, line[0])) == "conflict"  # nothing is checked move by move

    fb = ok(api.submit_line(sid, line))
    assert fb["win"] and fb["outcome"]["win"]
    assert fb["replies_correct"] == fb["replies_total"] == len(line) // 2
    assert all(g["correct"] for g in fb["grades"])
    assert rows(paths, "SELECT mode, win, replies_correct, replies_total FROM attempts") == [
        ("commit_line", 1, len(line) // 2, len(line) // 2)
    ]
    assert err(api.submit_line(sid, line)) == "conflict"  # once


def test_commit_show_move_count_reveals_the_length_and_reports_the_length_theme(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line", True))["session_id"]
    view = ok(api.next_puzzle(sid))
    line = moves(api, sid)[1:]
    assert view["solution_plies"] == view["max_plies"] == len(line)
    ok(api.submit_line(sid, line))
    angle = rows(paths, "SELECT angle FROM attempts")[0][0]
    assert angle in ("oneMove", "short", "long", "veryLong")


def test_commit_wrong_line_is_a_loss_and_engine_waits_for_submit(api, paths) -> None:  # type: ignore[no-untyped-def]
    import chess

    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    view = ok(api.next_puzzle(sid))
    board = chess.Board(view["fen"])
    board.push_uci(view["opponent_move"])
    right = moves(api, sid)[1]
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != right and not board.gives_check(m))
    assert err(api.analyze_position(sid, board.fen(), "start")) == "conflict"  # FR-7.3 before Submit
    fb = ok(api.submit_line(sid, [wrong]))
    assert not fb["win"] and fb["outcome"] is not None and not fb["outcome"]["win"]
    assert rows(paths, "SELECT win, first_move_correct FROM attempts") == [(0, 0)]


def test_submit_line_is_only_for_commit_mode(api) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    assert err(api.submit_line(sid, moves(api, sid)[1:])) == "conflict"


# ---- Depth ladder (FR-4.5) --------------------------------------------------------------------------


def test_depth_ladder_climbs_from_short_to_long(api, paths) -> None:  # type: ignore[no-untyped-def]
    ok(api.set_setting("ladder.window", 3))
    ok(api.set_setting("ladder.threshold", 100))
    spec = {**OPEN, "order": "depth_ladder"}
    preview = ok(api.get_ladder_status(spec))
    assert (preview["ladder"]["level"], preview["ladder"]["label"], preview["ladder"]["step"]) == (2, "Short", 1)
    assert preview["match_count"] == ok(api.count_matches(spec)) > 0

    sid = ok(api.start_session(spec))["session_id"]
    level_up = None
    for _ in range(3):
        ok(api.next_puzzle(sid))
        assert len(moves(api, sid)) // 2 == 2  # short puzzles only
        level_up = solve(api, sid)["level_up"]
    assert level_up is not None and (level_up["level"], level_up["label"]) == (3, "Long")
    stats = ok(api.get_session_stats(sid))
    assert stats["ladder"]["level"] == 3 and stats["ladder"]["played"] == 0

    ok(api.next_puzzle(sid))
    assert len(moves(api, sid)) // 2 == 3  # the session continues at the new level
    assert rows(paths, "SELECT DISTINCT ladder_level FROM attempts WHERE ladder_key IS NOT NULL") == [(2,)]
    # The level carries over to the next session, and the angle is the length theme (§8.3).
    assert ok(api.get_ladder_status(spec))["ladder"]["level"] == 3
    assert {r[0] for r in rows(paths, "SELECT angle FROM attempts")} == {"short"}


def test_depth_ladder_and_ratios_dont_combine(api) -> None:  # type: ignore[no-untyped-def]
    spec = {**OPEN, "order": "depth_ladder", "ratios": [{"themes": ["fork"], "weight": 50},
                                                        {"themes": ["pin"], "weight": 50}]}  # fmt: skip
    assert err(api.start_session(spec)) == "invalid_argument"


# ---- Mode switching, settings, fast-forward ---------------------------------------------------------


def test_switching_mode_starts_a_new_session_like_start_does(api, paths) -> None:  # type: ignore[no-untyped-def]
    """§6: the puzzle in progress is handled exactly as pressing Start handles it (pinned here):
    the old session is left as it was, and nothing is recorded for its undecided puzzle."""
    first = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(first))
    second = ok(api.start_session(OPEN, True, "commit_line"))
    assert second["session_id"] != first and second["mode"] == "commit_line"
    assert rows(paths, "SELECT COUNT(*) FROM attempts") == [(0,)]
    assert rows(paths, "SELECT mode FROM sessions ORDER BY id") == [("standard",), ("commit_line",)]


def test_new_settings_round_trip_through_the_bridge(api) -> None:  # type: ignore[no-untyped-def]
    before = ok(api.get_settings())
    assert (before["mode"], before["show_length"], before["filters_collapsed"]) == ("standard", False, False)
    assert before["srs_intervals"] == [1, 3, 7, 14, 30]
    assert (before["ladder_threshold"], before["ladder_window"]) == (80, 20)
    ok(api.set_setting("trainer.mode", "spaced_repetition"))
    ok(api.set_setting("commit.show_length", True))
    ok(api.set_setting("srs.intervals", [2, 4, 8]))
    ok(api.set_setting("ui.filters_collapsed", True))
    after = ok(api.get_settings())
    assert (after["mode"], after["show_length"], after["filters_collapsed"]) == ("spaced_repetition", True, True)
    assert after["srs_intervals"] == [2, 4, 8]
    for key, bad in (("trainer.mode", "danger"), ("srs.intervals", [3, 1]), ("ladder.window", 0),
                     ("ladder.threshold", 120), ("ui.filters_collapsed", "yes")):  # fmt: skip
        assert err(api.set_setting(key, bad)) == "invalid_argument"
    assert err(api.set_setting("debug.time_offset_days", 3)) == "invalid_argument"  # only via set_time_offset


def test_fast_forward_is_refused_without_a_dev_clock(api) -> None:  # type: ignore[no-untyped-def]
    assert err(api.set_time_offset(1)) == "conflict"  # a FixedClock can't be moved this way
    api._dev_mode = False
    assert err(api.set_time_offset(1)) == "conflict"
    assert ok(api.get_settings())["time_offset_days"] is None


def test_fast_forward_moves_the_dev_clock_and_persists(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.system_clock import OffsetClock

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    dev_clock = OffsetClock()
    api = build_api(paths, dev_clock)  # type: ignore[arg-type]
    ok(api.set_time_offset(4))
    assert dev_clock.offset_days == 4
    assert ok(api.get_settings())["time_offset_days"] == 4
    assert api._ui_settings.time_offset_days() == 4  # app.py restores it on the next --dev launch
    assert err(api.set_time_offset(-1)) == "invalid_argument"
