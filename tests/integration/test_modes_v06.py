"""v0.6 over the bridge, with a real user.db, the fixture puzzles and the fake engine: Name the idea first
(FR-4.3), Danger spotting (FR-4.4), mistake reasons (§7.3, FR-5.6–5.10) and the new settings."""

from __future__ import annotations

import shutil
import sqlite3
from typing import Any

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api
from tests.integration.test_qa_v03_edges import Wired, _check_in
from weaksquare.core.clock import FixedClock
from weaksquare.core.modes.danger import DangerState

OPEN = {"min_popularity": None, "min_plays": None, "exclude_played_on_lichess": False, "queue_size": 20}


@pytest.fixture
def api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    FakeEngine.instances.clear()
    return build_api(paths, clock)


def ok(r: dict[str, Any]) -> Any:
    assert r["ok"], r
    return r["data"]


def err(r: dict[str, Any]) -> str:
    assert not r["ok"], r
    return str(r["error"]["code"])


def state(api: Any, sid: int) -> Any:
    s = api._sessions._session(sid)
    with s.lock:
        return s.current.state


def rows(paths: Any, sql: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(paths.user_db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def wrong_move(fen: str, right: str) -> str:
    board = chess.Board(fen)
    for m in board.legal_moves:
        if m.uci() != right:
            board.push(m)
            mate = board.is_checkmate()
            board.pop()
            if not mate:
                return m.uci()
    raise AssertionError("no wrong move")


# ---- Name the idea first (FR-4.3) -------------------------------------------------------------------


def test_name_the_idea_tags_then_solves_and_grades_the_tags(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "name_idea"))["session_id"]
    view = ok(api.next_puzzle(sid))
    assert view["mode"] == "name_idea" and view["opponent_move"]
    st = state(api, sid)
    first = st.puzzle.moves[1]
    assert err(api.submit_move(sid, first)) == "conflict"  # tag first
    assert err(api.set_idea_tags(sid, [], [])) == "invalid_argument"
    assert err(api.set_idea_tags(sid, ["fork"], [])) == "invalid_argument"  # fork is a payoff motif
    ok(api.set_idea_tags(sid, ["deflection"], ["fork"]))
    outcome = None
    for uci in st.puzzle.moves[1::2]:
        fb = ok(api.submit_move(sid, uci))
        outcome = fb["outcome"] or outcome
    assert outcome is not None and outcome["win"]
    idea = outcome["idea"]
    themes = set(st.puzzle.themes)
    expected_found = len({"deflection", "fork"} & themes)
    assert idea["found"] == expected_found and idea["extra"] == 2 - expected_found
    row = rows(paths, "SELECT mode, idea_tags, idea_total, sync_status FROM attempts")[0]
    assert row[0] == "name_idea" and '"payoff": ["fork"]' in row[1] and row[3] != "local"


def test_name_the_idea_works_without_a_depth_ladder(api) -> None:  # type: ignore[no-untyped-def]
    assert err(api.start_session({**OPEN, "order": "depth_ladder"}, True, "name_idea")) == "invalid_argument"
    assert err(api.set_idea_tags(999, [], ["fork"])) == "not_found"


# ---- Danger spotting (FR-4.4) -----------------------------------------------------------------------


def test_danger_spotting_needs_the_engine(api) -> None:  # type: ignore[no-untyped-def]
    assert err(api.start_session(OPEN, True, "danger_spotting")) == "engine_not_installed"


def _danger_session(api: Any, paths: Any) -> int:
    plant_managed_install(paths)
    return int(ok(api.start_session(OPEN, True, "danger_spotting"))["session_id"])


def test_the_blunder_never_reaches_the_front_end_before_the_end(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    for _ in range(8):
        view = ok(api.next_puzzle(sid))
        st: DangerState = state(api, sid)
        assert view["opponent_move"] == "" and view["opponent_sound"] is None
        assert view["candidate"] == st.candidate and view["fen"] == st.puzzle.fen
        assert view["player_color"] == ("white" if chess.Board(st.puzzle.fen).turn else "black")
        assert set(view) >= {"candidate"} and st.puzzle.moves[0] not in str(
            {k: v for k, v in view.items() if k != "candidate"}
        )
        assert err(api.analyze_position(sid, view["fen"], "panel")) == "conflict"  # FR-7.3


def test_about_half_the_candidates_are_safe_and_each_is_verified(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    kinds = []
    for _ in range(20):
        if ok(api.next_puzzle(sid)) is None:
            break
        st: DangerState = state(api, sid)
        kinds.append(st.is_safe)
        if st.is_safe:
            assert st.candidate != st.puzzle.moves[0]
            assert chess.Move.from_uci(st.candidate) in chess.Board(st.puzzle.fen).legal_moves
    assert len(kinds) == 20
    assert 5 <= sum(kinds) <= 15  # roughly half (seeded rng; fixture positions without a safe move are owed)
    engine = FakeEngine.instances[-1]
    assert all(multipv == 5 for _, _, multipv in engine.calls)  # MultiPV 5 from the blunderer's side


def _until(api: Any, sid: int, safe: bool) -> DangerState:
    for _ in range(30):
        ok(api.next_puzzle(sid))
        st: DangerState = state(api, sid)
        if st.is_safe == safe:
            return st
    raise AssertionError("no such candidate in 30 puzzles")


def test_calls_are_scored_and_stay_local(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, True)
    fb = ok(api.call_danger(sid, "safe"))
    assert fb["correct"] and not fb["refute"] and fb["outcome"]["win"]
    reveal = fb["outcome"]["danger"]
    assert reveal["is_safe"] and reveal["call"] == "safe" and reveal["best_score"] and reveal["candidate_score"]

    st = _until(api, sid, False)
    fb = ok(api.call_danger(sid, "unsafe"))
    assert fb["correct"] and fb["refute"] and fb["outcome"] is None and fb["blunder_sound"]
    assert err(api.call_danger(sid, "unsafe")) == "conflict"
    move = ok(api.submit_move(sid, st.puzzle.moves[1]))
    assert move["kind"] == "solved" and move["outcome"]["win"]
    assert move["outcome"]["danger"]["line"] == list(st.puzzle.moves[1:])

    _until(api, sid, False)
    fb = ok(api.call_danger(sid, "safe"))
    assert not fb["correct"] and not fb["outcome"]["win"]

    got = rows(paths, "SELECT mode, win, danger_safe, danger_call, sync_status, rated FROM attempts ORDER BY id")
    assert [g[:4] for g in got if g[1] is not None and g[3] is not None] == [
        ("danger_spotting", 1, 1, "safe"),
        ("danger_spotting", 1, 0, "unsafe"),
        ("danger_spotting", 0, 0, "safe"),
    ]
    assert {g[4] for g in got} == {"local"}  # never synced (FR-4.4)


def test_danger_results_skip_srs_and_the_history_filters(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, False)
    ok(api.call_danger(sid, "safe"))  # a Danger miss
    clock.advance(days=2)
    assert ok(api.get_srs_status())["scheduled"] == 0
    missed_only = {**OPEN, "only_my_misses": True}
    assert ok(api.count_matches(missed_only)) == 0


def test_practice_keeps_the_candidate(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    st = _until(api, sid, True)
    ok(api.call_danger(sid, "safe"))
    ok(api.retry_puzzle(sid))
    again: DangerState = state(api, sid)
    assert again.practice and again.candidate == st.candidate and again.is_safe
    fb = ok(api.call_danger(sid, "unsafe"))
    assert fb["outcome"] is None
    assert len(rows(paths, "SELECT id FROM attempts")) <= 1 + 30  # nothing new for the practice run


# ---- mistake reasons (§7.3) -------------------------------------------------------------------------


def _lose_by_wrong_first_move(api: Any, sid: int, clock: FixedClock, think_s: float) -> dict[str, Any]:
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=think_s)
    fb = ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    assert fb["outcome"] and not fb["outcome"]["win"]
    ok(api.request_help(sid, "hint"))  # free now; then play the line out
    for uci in st.puzzle.moves[st.next_index :: 2]:
        last = ok(api.submit_move(sid, uci))
        if last["finished"]:
            break
    return fb["outcome"]


def test_reason_prompt_after_a_loss_with_a_suggestion(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    out = _lose_by_wrong_first_move(api, sid, clock, 1)
    prompt = ok(api.get_reason_prompt(sid))
    assert prompt["attempt_id"] == out["attempt_id"] and prompt["source"] == "puzzle"
    assert prompt["suggested"] == "rushed"  # 1 s < 3 s
    assert [r["key"] for r in prompt["reasons"]] == [
        "didntLook", "missedResource", "miscalculated", "unknownPattern", "rushed", "misclick",
    ]  # fmt: skip
    ok(api.set_mistake_reason(out["attempt_id"], "didntLook", "  missed the knight  "))
    ok(api.set_mistake_reason(out["attempt_id"], "unknownPattern"))  # changed: the latest counts
    got = rows(paths, "SELECT source, ref_id, reason, suggested_reason, note FROM mistake_reasons ORDER BY id")
    assert got == [
        ("puzzle", str(out["attempt_id"]), "didntLook", "rushed", "missed the knight"),
        ("puzzle", str(out["attempt_id"]), "unknownPattern", "rushed", None),
    ]


def test_no_prompt_after_a_win_while_playing_on_or_when_off(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    for uci in st.puzzle.moves[1::2]:
        fb = ok(api.submit_move(sid, uci))
    assert fb["outcome"]["win"] or fb["finished"]
    assert ok(api.get_reason_prompt(sid)) is None
    assert err(api.set_mistake_reason(rows_id(api), "rushed")) == "conflict"  # a win

    ok(api.next_puzzle(sid))
    st = state(api, sid)
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    if not st.finished:
        assert ok(api.get_reason_prompt(sid)) is None  # still playing the line through
    ok(api.set_setting("reasons.ask", "off"))
    ok(api.request_help(sid, "answer")) if not st.finished else None
    assert ok(api.get_reason_prompt(sid)) is None
    assert ok(api.get_settings())["reasons_ask"] == "off"
    assert err(api.set_setting("reasons.ask", "game_review")) == "invalid_argument"


def rows_id(api: Any) -> int:
    with api._sessions._attempts._db.session() as c:
        return int(c.execute("SELECT MAX(id) FROM attempts").fetchone()[0])


def test_reason_validation(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    out = _lose_by_wrong_first_move(api, sid, clock, 10)
    aid = out["attempt_id"]
    assert err(api.set_mistake_reason(aid, "bored")) == "invalid_argument"
    assert err(api.set_mistake_reason(aid, "rushed", "x" * 201)) == "invalid_argument"
    assert err(api.set_mistake_reason(0, "rushed")) == "invalid_argument"
    assert err(api.set_mistake_reason(aid + 1000, "rushed")) == "not_found"
    assert err(api.set_mistake_reason(True, "rushed")) == "invalid_argument"


def test_rushed_threshold_setting(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    ok(api.set_setting("reasons.rushed_s", 20))
    assert ok(api.get_settings())["rushed_s"] == 20
    assert err(api.set_setting("reasons.rushed_s", 0)) == "invalid_argument"
    sid = ok(api.start_session(OPEN))["session_id"]
    _lose_by_wrong_first_move(api, sid, clock, 10)
    assert ok(api.get_reason_prompt(sid))["suggested"] == "rushed"  # 10 s < 20 s


def test_miscalculated_when_the_first_move_was_right(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    for _ in range(20):
        ok(api.next_puzzle(sid))
        st = state(api, sid)
        if len(st.puzzle.moves) >= 4:
            break
    clock.advance(seconds=10)
    ok(api.submit_move(sid, st.puzzle.moves[1]))
    clock.advance(seconds=10)
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[3])))
    ok(api.request_help(sid, "answer"))
    assert ok(api.get_reason_prompt(sid))["suggested"] == "miscalculated"


def test_missed_resource_from_the_engines_refutation(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid = ok(api.start_session(OPEN))["session_id"]
    _lose_by_wrong_first_move(api, sid, clock, 10)
    prompt = ok(api.get_reason_prompt(sid))
    ref = ok(api.get_refutation(sid))
    s = api._sessions._session(sid)
    fen, uci = s.current.reason.first_wrong
    board = chess.Board(fen)
    board.push_uci(uci)
    reply = chess.Move.from_uci(ref["line"][0])
    forcing = board.is_capture(reply) or board.gives_check(reply)
    assert prompt["suggested"] == ("missedResource" if forcing else None)


def test_danger_blunder_called_safe_suggests_missed_resource(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, False)
    clock.advance(seconds=10)
    fb = ok(api.call_danger(sid, "safe"))
    prompt = ok(api.get_reason_prompt(sid))
    assert prompt["source"] == "danger" and prompt["suggested"] == "missedResource"
    ok(api.set_mistake_reason(fb["outcome"]["attempt_id"], "didntLook"))
    assert rows(paths, "SELECT source FROM mistake_reasons") == [("danger",)]


def test_misclick_is_left_out_of_the_session_bar_and_ladder(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    out = _lose_by_wrong_first_move(api, sid, clock, 10)
    before = ok(api.get_session_stats(sid))
    assert (before["failed"], before["misclicks"]) == (1, 0)
    ok(api.set_mistake_reason(out["attempt_id"], "misclick"))
    after = ok(api.get_session_stats(sid))
    assert (after["solved"], after["failed"], after["misclicks"], after["accuracy"]) == (0, 0, 1, None)
    assert (after["all_time_failed"]) == 0
    ok(api.set_mistake_reason(out["attempt_id"], "rushed"))  # changed back: it counts again
    assert ok(api.get_session_stats(sid))["failed"] == 1


def test_misclick_keeps_the_puzzle_in_spaced_repetition(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    out = _lose_by_wrong_first_move(api, sid, clock, 10)
    ok(api.set_mistake_reason(out["attempt_id"], "misclick"))
    assert ok(api.get_srs_status())["scheduled"] == 1


# ROADMAP v0.6 Done when: a misclick is excluded from local stats but still sent as a loss.
@pytest.fixture
def w(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    wired = Wired(paths, clock, fixture_puzzles_db)
    yield wired
    wired.close()


def test_misclick_is_excluded_locally_but_still_sent_to_lichess_as_a_loss(w: Wired, clock: FixedClock) -> None:
    _check_in(w)
    api = w.api
    sid = ok(api.start_session(OPEN, True))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=10)
    fb = ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    aid = fb["outcome"]["attempt_id"]
    ok(api.request_help(sid, "answer"))
    ok(api.set_mistake_reason(aid, "misclick"))
    w.settle()
    sent = [s for c in w.lichess.batch_calls for s in c.solutions]
    assert [(s.id, s.win) for s in sent] == [(st.puzzle.ref.id, False)]
    stats = ok(api.get_stats())
    assert stats["overall"]["attempts"] == 0 and stats["misclicks"] == 1
    assert ok(api.get_session_stats(sid))["misclicks"] == 1


def test_reason_stats_over_the_bridge(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    a = _lose_by_wrong_first_move(api, sid, clock, 10)
    b = _lose_by_wrong_first_move(api, sid, clock, 10)
    ok(api.set_mistake_reason(a["attempt_id"], "didntLook"))
    ok(api.set_mistake_reason(b["attempt_id"], "misclick"))
    r = ok(api.get_reason_stats())
    assert (r["tagged"], r["untagged"], r["misclicks"]) == (1, 0, 1)
    assert r["reasons"][0]["key"] == "didntLook" and r["reasons"][0]["share"] == 1.0
    assert r["trend"] == [{"week": "2025-12-29", "counts": [1, 0, 0, 0, 0]}]  # FixedClock starts Thu 1 Jan 2026
    assert ok(api.get_reason_stats(None, "danger_spotting"))["tagged"] == 0
    assert err(api.get_reason_stats("<b>", None)) == "invalid_argument"
    assert err(api.get_reason_stats(None, "blitz")) == "invalid_argument"


def test_misclicks_are_not_in_the_ladder_window(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    attempts = api._sessions._attempts
    ok(api.set_setting("ladder.window", 3))
    ok(api.set_setting("ladder.threshold", 50))
    sid = ok(api.start_session({**OPEN, "order": "depth_ladder"}))["session_id"]
    key = api._sessions._session(sid).ladder.key
    out = _lose_by_wrong_first_move(api, sid, clock, 10)
    level, recent = attempts.ladder_history(key, 3)
    assert recent == [False]
    ok(api.set_mistake_reason(out["attempt_id"], "misclick"))
    assert attempts.ladder_history(key, 3) == (level, [])
