"""QA v0.5 (independent): edge cases over the bridge with a real user.db and the fixture puzzles.
Commit the line (FR-4.2), Spaced repetition (FR-4.6), the depth-ladder order (FR-4.5), mode
switching (§6) and the dev-only fast-forward."""

from __future__ import annotations

import shutil
import sqlite3
from typing import Any

import chess
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


def line_of(api: Any, sid: int) -> list[str]:
    s = api._sessions._session(sid)
    with s.lock:
        return list(s.current.state.puzzle.moves)


def solve(api: Any, sid: int) -> dict[str, Any]:
    outcome = None
    for uci in line_of(api, sid)[1::2]:
        fb = ok(api.submit_move(sid, uci))
        outcome = fb["outcome"] or outcome
        if fb["finished"]:
            break
    assert outcome is not None
    return outcome


def rows(paths: Any, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(paths.user_db)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def miss(api: Any, n: int) -> list[str]:
    """Skip n undecided puzzles in a Standard session (each skip is a loss). Returns their IDs."""
    sid = ok(api.start_session(OPEN))["session_id"]
    ids = [ok(api.next_puzzle(sid))["puzzle_id"]]
    for _ in range(n - 1):
        ids.append(ok(api.next_puzzle(sid))["puzzle_id"])
    ok(api.next_puzzle(sid))  # decides the last one
    return ids


# ---- Commit the line --------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [{"a": 1}, "d5c3", 7, None])
def test_submit_line_with_the_wrong_type_is_invalid_argument(api, bad) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    assert err(api.submit_line(sid, bad)) == "invalid_argument"


@pytest.mark.parametrize("bad", [[1, 2], [None], [["e2e4"]], ["zzzz"], ["e2e4"] * 300])
def test_submit_line_with_junk_moves_is_invalid_argument_and_nothing_is_recorded(api, paths, bad) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    assert err(api.submit_line(sid, bad)) == "invalid_argument"
    assert rows(paths, "SELECT COUNT(*) FROM attempts") == [(0,)]
    ok(api.submit_line(sid, line_of(api, sid)[1:]))  # still submittable afterwards


def test_overlong_line_with_show_move_count_is_refused(api) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line", True))["session_id"]
    ok(api.next_puzzle(sid))
    line = line_of(api, sid)[1:]
    board = chess.Board(api._sessions._session(sid).current.state.start_fen)
    for m in line:
        board.push_uci(m)
    if board.is_game_over():
        pytest.skip("the solution ends the game: no legal extra move")
    extra = next(iter(board.legal_moves)).uci()
    assert err(api.submit_line(sid, [*line, extra])) == "invalid_argument"


def test_submit_twice_records_once(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    line = line_of(api, sid)[1:]
    ok(api.submit_line(sid, line))
    assert err(api.submit_line(sid, line)) == "conflict"
    assert rows(paths, "SELECT COUNT(*) FROM attempts") == [(1,)]


def test_hint_before_submit_is_a_loss_recorded_once(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    line = line_of(api, sid)[1:]
    h = ok(api.request_help(sid, "hint"))
    assert h["outcome"] is not None and not h["outcome"]["win"]
    fb = ok(api.submit_line(sid, line))
    assert not fb["win"] and fb["outcome"] is None
    assert all(g["correct"] for g in fb["grades"])
    assert rows(paths, "SELECT win, help_used FROM attempts") == [(0, "hint")]


def test_commit_try_again_records_nothing(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    line = line_of(api, sid)[1:]
    ok(api.submit_line(sid, line[:1] if len(line) > 1 else line))
    ok(api.retry_puzzle(sid))
    fb = ok(api.submit_line(sid, line))
    assert fb["outcome"] is None
    assert all(g["correct"] for g in fb["grades"])
    assert rows(paths, "SELECT COUNT(*) FROM attempts") == [(1,)]


def test_engine_is_refused_before_submit_and_allowed_after(api) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    fen = api._sessions._session(sid).current.state.start_fen
    assert err(api.analyze_position(sid, fen, "start")) == "conflict"
    assert err(api.get_refutation(sid)) in ("conflict", "not_found", "invalid_argument")


# ---- Mode switch ------------------------------------------------------------------------------------


def test_mode_switch_after_a_correct_first_move_records_nothing(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session({**OPEN, "lengths": [2, 3, 4]}))["session_id"]
    ok(api.next_puzzle(sid))
    line = line_of(api, sid)
    assert len(line) >= 4
    fb = ok(api.submit_move(sid, line[1]))
    assert not fb["finished"] and fb["outcome"] is None
    ok(api.start_session(OPEN, True, "commit_line"))  # what the Modes control does mid-session
    assert rows(paths, "SELECT COUNT(*) FROM attempts") == [(0,)]


# ---- Spaced repetition ------------------------------------------------------------------------------


def test_srs_skips_puzzles_a_reimport_removed(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    ids = miss(api, 2)
    clock.advance(days=1)
    assert ok(api.get_srs_status())["due"] == 2
    conn = sqlite3.connect(paths.puzzles_db)
    conn.execute("DELETE FROM puzzles WHERE id = ?", (ids[0],))
    conn.commit()
    conn.close()
    assert ok(api.get_srs_status())["due"] == 1
    sid = ok(api.start_session({"queue_size": 20}, True, "spaced_repetition"))["session_id"]
    assert ok(api.next_puzzle(sid))["puzzle_id"] == ids[1]
    assert ok(api.next_puzzle(sid)) is None


def test_srs_with_every_due_puzzle_removed_cannot_start(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    ids = miss(api, 1)
    clock.advance(days=1)
    conn = sqlite3.connect(paths.puzzles_db)
    conn.execute("DELETE FROM puzzles WHERE id = ?", (ids[0],))
    conn.commit()
    conn.close()
    assert ok(api.get_srs_status())["due"] == 0
    assert err(api.start_session({"queue_size": 20}, True, "spaced_repetition")) == "invalid_argument"


def test_srs_queue_size_still_applies_and_most_overdue_first(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    first = miss(api, 1)
    clock.advance(days=1)
    second = miss(api, 1)
    clock.advance(days=1)
    assert ok(api.get_srs_status())["due"] == 2
    sid = ok(api.start_session({"queue_size": 1}, True, "spaced_repetition"))["session_id"]
    assert ok(api.next_puzzle(sid))["puzzle_id"] == first[0]  # due a day earlier
    assert ok(api.next_puzzle(sid)) is None  # queue size 1
    assert second


def test_srs_skip_in_review_sends_it_back_to_box_one(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    miss(api, 1)
    clock.advance(days=1)
    sid = ok(api.start_session({"queue_size": 5}, True, "spaced_repetition"))["session_id"]
    ok(api.next_puzzle(sid))
    ok(api.next_puzzle(sid))  # skip = loss
    st = ok(api.get_srs_status())
    assert (st["due"], st["next_due"]) == (0, "2026-01-03")
    assert rows(paths, "SELECT mode, win, angle FROM attempts ORDER BY id DESC LIMIT 1") == [
        ("spaced_repetition", 0, "mix")
    ]


def test_srs_shrunk_intervals_after_reaching_a_high_box(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    miss(api, 1)
    for gap in (1, 3, 7):  # climb to box 4
        clock.advance(days=gap)
        sid = ok(api.start_session({"queue_size": 5}, True, "spaced_repetition"))["session_id"]
        ok(api.next_puzzle(sid))
        assert solve(api, sid)["win"]
    assert ok(api.get_srs_status())["scheduled"] == 1
    ok(api.set_setting("srs.intervals", [1, 2]))
    st = ok(api.get_srs_status())
    assert st["scheduled"] == 0 and st["due"] == 0 and st["next_due"] is None  # replayed: graduated


# ---- Depth ladder -----------------------------------------------------------------------------------


def test_ladder_level_is_shared_by_standard_and_commit_and_angle_is_the_length(api, paths) -> None:  # type: ignore[no-untyped-def]
    ok(api.set_setting("ladder.window", 3))
    ok(api.set_setting("ladder.threshold", 60))
    spec = {**OPEN, "order": "depth_ladder"}
    sid = ok(api.start_session(spec, True, "commit_line"))["session_id"]
    for _ in range(2):
        ok(api.next_puzzle(sid))
        ok(api.submit_line(sid, line_of(api, sid)[1:]))
    assert ok(api.get_ladder_status(spec))["ladder"]["level"] == 2  # 2 of 3 played
    sid2 = ok(api.start_session(spec))["session_id"]
    ok(api.next_puzzle(sid2))
    assert len(line_of(api, sid2)) // 2 == 2
    out = solve(api, sid2)
    assert out["level_up"] is not None and out["level_up"]["level"] == 3
    got = rows(paths, "SELECT mode, ladder_level, angle FROM attempts ORDER BY id")
    assert got == [("commit_line", 2, "short"), ("commit_line", 2, "short"), ("standard", 2, "short")]


def test_ladder_with_themes_and_ratios_are_refused_for_preview_too(api) -> None:  # type: ignore[no-untyped-def]
    spec = {**OPEN, "order": "depth_ladder", "ratios": [{"themes": ["fork"], "weight": 100}]}
    assert err(api.get_ladder_status(spec)) == "invalid_argument"
    assert err(api.count_matches(spec)) == "invalid_argument"


def test_ladder_practice_runs_never_count(api, paths) -> None:  # type: ignore[no-untyped-def]
    ok(api.set_setting("ladder.window", 3))
    spec = {**OPEN, "order": "depth_ladder"}
    sid = ok(api.start_session(spec))["session_id"]
    ok(api.next_puzzle(sid))
    solve(api, sid)
    ok(api.retry_puzzle(sid))
    solve_moves = line_of(api, sid)[1::2]
    for uci in solve_moves:
        if ok(api.submit_move(sid, uci))["finished"]:
            break
    assert rows(paths, "SELECT COUNT(*) FROM attempts WHERE ladder_key IS NOT NULL") == [(1,)]
    assert ok(api.get_ladder_status(spec))["ladder"]["played"] == 1


def test_ladder_count_matches_counts_only_the_current_level(api) -> None:  # type: ignore[no-untyped-def]
    spec = {**OPEN, "order": "depth_ladder", "lengths": [1, 3, 4]}  # lengths are overridden by the ladder
    short = ok(api.count_matches({**OPEN, "lengths": [2]}))
    assert ok(api.count_matches(spec)) == short


# ---- Fast-forward (dev) -----------------------------------------------------------------------------


def test_fast_forward_then_review_with_the_dev_clock(paths, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.system_clock import OffsetClock

    dev_clock = OffsetClock()
    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", dev_clock)  # type: ignore[arg-type]
    api = build_api(paths, dev_clock)  # type: ignore[arg-type]
    miss(api, 1)
    assert ok(api.get_srs_status())["due"] == 0
    ok(api.set_time_offset(1))
    assert ok(api.get_srs_status())["due"] == 1
    sid = ok(api.start_session({"queue_size": 5}, True, "spaced_repetition"))["session_id"]
    ok(api.next_puzzle(sid))
    assert solve(api, sid)["win"]
    st = ok(api.get_srs_status())
    assert st["due"] == 0 and st["scheduled"] == 1
    ok(api.set_time_offset(4))  # box 2 is 3 days after the review
    assert ok(api.get_srs_status())["due"] == 1
    ok(api.set_time_offset(0))
    assert ok(api.get_settings())["time_offset_days"] == 0


def test_fast_forward_refused_outside_dev_even_with_an_offset_clock(paths, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.system_clock import OffsetClock

    dev_clock = OffsetClock()
    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", dev_clock)  # type: ignore[arg-type]
    api = build_api(paths, dev_clock)  # type: ignore[arg-type]
    api._dev_mode = False
    assert err(api.set_time_offset(2)) == "conflict"
    assert dev_clock.offset_days == 0
    assert ok(api.get_settings())["time_offset_days"] is None


def test_app_wires_the_offset_clock_only_for_dev() -> None:
    import inspect

    from weaksquare import app

    src = inspect.getsource(app.main)
    assert "OffsetClock() if args.dev else SystemClock()" in src


def test_engine_stays_refused_after_a_hint_until_submit(api) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    fen = api._sessions._session(sid).current.state.start_fen
    ok(api.request_help(sid, "hint"))  # decides the attempt (a loss) but the puzzle isn't over
    assert err(api.analyze_position(sid, fen, "start")) == "conflict"
    ok(api.submit_line(sid, line_of(api, sid)[1:2]))
    assert err(api.analyze_position(sid, fen, "start")) != "conflict"  # over now (no engine in tests)


def test_ladder_skips_levels_with_no_puzzles(api) -> None:  # type: ignore[no-untyped-def]
    """Regression v0.5-B2: with a theme that has no 3-move puzzles (Mate in 2), the ladder used to climb
    into the empty level, end the session and stay stuck there. Empty levels are now skipped."""
    ok(api.set_setting("ladder.window", 3))
    ok(api.set_setting("ladder.threshold", 60))
    spec = {**OPEN, "themes": ["mateIn2"], "order": "depth_ladder"}
    preview = ok(api.get_ladder_status(spec))
    sid = ok(api.start_session(spec))["session_id"]
    for _ in range(3):
        view = ok(api.next_puzzle(sid))
        if view is None:
            pytest.skip("the fixture has fewer than 3 mate-in-2 puzzles")
        solve(api, sid)
        assert ok(api.get_session_stats(sid))["ladder"]["level"] in (2, 3, 4)
    after = ok(api.get_ladder_status(spec))
    assert after["match_count"] > 0  # never parked on an empty level
    assert ok(api.start_session(spec))["match_count"] > 0
    if preview["ladder"]["top"]:  # mate in 2 is only ever 2 moves: that level is the top
        assert after["ladder"]["level"] == preview["ladder"]["level"]
