"""Deviations, Build my repertoire, Practice and stats against a real database (v0.13, FR-12.8-12.11, 12.14)."""

from __future__ import annotations

from typing import Any

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from weaksquare.adapters.db.repos.openings import ExplorerCacheRepo
from weaksquare.core.engine import EngineNotInstalled
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.openings import STARTING_KEY, position_key
from weaksquare.core.repertoire import after

E4, E5, NF3, NC6, BC4 = "e2e4", "e7e5", "g1f3", "b8c6", "f1c4"


@pytest.fixture
def svc(services: Any, paths: Any) -> Any:
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    services.openings.import_now()
    services.openings.set_extend(False)
    return services


def add_italian(svc: Any, color: str = "white", subs: int = 0, moves: int = 4) -> None:
    svc.openings.set_scope("custom", subs, moves)
    svc.repertoire.add_lines(color, "Italian Game", list(range(subs + 1)))


def rows(svc: Any, color: str = "white") -> list[Any]:
    return list(svc.repertoire.view(color).rows)


def engine_calls() -> int:
    return sum(len(e.calls) for e in FakeEngine.instances)


# ---- "What if they play…?" (FR-12.8) ----------------------------------------------------------------------


def test_a_deviation_gets_the_engines_replies(svc: Any) -> None:
    d = svc.repertoire.what_if("white", [E4], "a6")
    assert d.their_uci == "a7a6" and d.their_san == "a6" and len(d.replies) == 3
    assert all(r.score for r in d.replies)


@pytest.mark.parametrize("move", ["e4", "Ke5", "banana", "", None])
def test_an_illegal_deviation_never_reaches_the_engine(svc: Any, move: Any) -> None:
    with pytest.raises(ValidationError):
        svc.repertoire.what_if("white", [E4], move)
    assert engine_calls() == 0


def test_a_deviation_is_for_the_other_side(svc: Any) -> None:
    with pytest.raises(ValidationError):
        svc.repertoire.what_if("white", [], "e4")
    with pytest.raises(ValidationError):
        svc.repertoire.add_deviation("white", [], "e4", "e7e5")


@pytest.mark.parametrize("moves", ["e2e4", ["e2e5"], ["bad"], [3]])
def test_a_bad_line_is_refused(svc: Any, moves: Any) -> None:
    with pytest.raises(ValidationError):
        svc.repertoire.what_if("white", moves, "a6")


def test_a_deviation_needs_stockfish(services: Any) -> None:
    services.openings.import_now()
    with pytest.raises(EngineNotInstalled):
        services.repertoire.what_if("white", [E4], "a6")


def test_the_branch_is_stored_connected_with_its_sources_and_is_drilled(svc: Any) -> None:
    d = svc.repertoire.what_if("white", [E4], "a6")
    svc.repertoire.add_deviation("white", [E4], "a6", d.replies[0].uci)
    by_san = {r.edge.san: r.edge for r in rows(svc)}
    assert by_san["e4"].source == "book" and by_san["a6"].source == "you"
    assert by_san[d.replies[0].san].source == "engine"
    state = svc.opening_practice.start("white", mode="all", limit=10)
    assert state.state == "your_move"
    state = svc.opening_practice.play(state.session_id, E4)
    assert " w " in state.fen and state.replies == (("a7a6", "a6"),)


def test_a_reply_you_chose_is_marked_as_yours(svc: Any) -> None:
    svc.repertoire.add_deviation("white", [E4], "a6", "h2h3")
    assert {r.edge.san: r.edge.source for r in rows(svc)}["h3"] == "you"


def test_an_illegal_reply_is_refused(svc: Any) -> None:
    with pytest.raises(ValidationError):
        svc.repertoire.add_deviation("white", [E4], "a6", "e2e5")
    assert rows(svc) == []


def test_revisiting_a_branch_costs_no_engine_time(svc: Any) -> None:
    svc.repertoire.what_if("white", [E4], "a6")
    calls = engine_calls()
    svc.repertoire.what_if("white", [E4], "a6")
    assert engine_calls() == calls


# ---- Build my repertoire (FR-12.14) ---------------------------------------------------------------------------

LIMITS = {"max_moves": 4, "min_share": 0.05, "max_replies": 2, "max_positions": 12}


def test_nothing_is_saved_before_you_review(svc: Any) -> None:
    p = svc.repertoire.build_now("white", "Italian Game", LIMITS)
    assert p.moves and rows(svc) == []
    assert svc.repertoire.view("white").openings == ()
    result = svc.repertoire.save_proposal(p.id)
    assert result.added > 0 and len(rows(svc)) == result.added
    assert [o.name for o in svc.repertoire.view("white").openings] == ["Italian Game"]


def test_a_proposal_is_connected_from_the_start(svc: Any) -> None:
    p = svc.repertoire.build_now("white", "Italian Game", LIMITS)
    assert [m.san for m in p.moves][:5] == ["e4", "e5", "Nf3", "Nc6", "Bc4"]
    svc.repertoire.save_proposal(p.id)
    assert rows(svc)[0].edge.san == "e4"
    state = svc.opening_practice.start("white", mode="all", limit=50)
    assert state.remaining >= 3


def test_your_stored_moves_stay(svc: Any) -> None:
    line = [E4, E5, NF3, NC6, BC4]
    key = after(after(after(after(after(STARTING_KEY, E4), E5), NF3), NC6), BC4)
    after_bc5 = after(key, "f8c5")
    svc.repertoire.add_deviation("white", line, "Bc5", "b1c3")  # yours, not what the book would pick
    before = {(r.edge.san, r.edge.source) for r in rows(svc)}
    p = svc.repertoire.build_now("white", "Italian Game", {**LIMITS, "max_moves": 6})
    answers = [m for m in p.moves if m.position_key == after_bc5]
    assert [m.san for m in answers] == ["Nc3"] and answers[0].already_yours
    svc.repertoire.save_proposal(p.id)
    assert before <= {(r.edge.san, r.edge.source) for r in rows(svc)}


def test_signed_out_uses_book_replies(svc: Any) -> None:
    p = svc.repertoire.build_now("black", "Italian Game", LIMITS)
    assert {m.source for m in p.moves if not m.yours} == {"book"}


def test_signed_in_uses_popular_replies(svc: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    key = after(after(after(after(after(STARTING_KEY, E4), E5), NF3), NC6), BC4)
    params = svc.opening_sources.explorer_settings().params
    body = {
        "white": 500, "draws": 0, "black": 500,
        "moves": [{"uci": "f8c5", "white": 300, "draws": 0, "black": 300}, {"uci": "g8f6", "white": 200, "draws": 0, "black": 200}],
    }  # fmt: skip
    ExplorerCacheRepo(svc.db).put(key, params, body, "2026-01-01T12:00:00+00:00")
    p = svc.repertoire.build_now("white", "Italian Game", LIMITS)
    replies = {m.san: m for m in p.moves if m.position_key == key}
    assert set(replies) == {"Bc5", "Nf6"}
    assert replies["Bc5"].source == "explorer" and replies["Bc5"].share == pytest.approx(0.6)


def test_book_answers_win_over_the_engine_and_a_fallback_is_flagged(svc: Any) -> None:
    limits = {"max_moves": 12, "max_replies": 1, "max_positions": 60}
    yours = [
        m for c in ("white", "black") for m in svc.repertoire.build_now(c, "Italian Game", limits).moves if m.yours
    ]
    assert any(m.source == "book" for m in yours)
    # The book ends on one side's move, so past it that side's opponent, you, gets Stockfish's best.
    assert any(m.source == "engine" and "engine_answer" in m.flags for m in yours)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_moves": 1},
        {"max_replies": 0},
        {"max_positions": 1000},
        {"min_share": 0.9},
        {"max_moves": True},
        {"nonsense": 1},
        "x",
    ],
)
def test_bad_limits_are_refused(svc: Any, limits: Any) -> None:
    with pytest.raises(ValidationError):
        svc.repertoire.build_now("white", "Italian Game", limits)


def test_discarding_saves_nothing(svc: Any) -> None:
    p = svc.repertoire.build_now("white", "Italian Game", LIMITS)
    svc.repertoire.discard_proposal(p.id)
    with pytest.raises(NotFoundError):
        svc.repertoire.save_proposal(p.id)
    assert rows(svc) == []


def test_the_job_runs_on_the_background_engine(svc: Any) -> None:
    job = svc.repertoire.start_build("white", "Italian Game", LIMITS)
    st = svc.repertoire._runner.wait(job, 30)
    assert st.state == "done"
    assert svc.repertoire.proposal(st.message).moves
    assert svc.engine._engine is None and svc.engine._bg is not None


# ---- Practice (FR-12.9, 12.10) ---------------------------------------------------------------------------------


def session(svc: Any, color: str = "white", **kw: Any) -> Any:
    return svc.opening_practice.start(color, **{"mode": "due", "limit": 20, **kw})


def test_an_empty_repertoire_says_so(svc: Any) -> None:
    with pytest.raises(ConflictError):
        session(svc)


def test_a_line_plays_through_with_the_opponent_replying(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    assert s.state == "your_move" and s.target_reason == "new"
    s = svc.opening_practice.play(s.session_id, E4)
    assert s.replies == ((E5, "e5"),) and s.correct == 1


def test_as_black_the_app_moves_first(svc: Any) -> None:
    add_italian(svc, "black")
    s = session(svc, "black")
    assert " b " in s.fen and s.replies == ((E4, "e4"),)


def test_a_wrong_move_shows_the_answer_and_records_a_loss(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    assert s.state == "wrong" and s.correct_moves == ((E4, "e4"),) and s.wrong == 1
    assert s.attempt_id is not None and s.wrong_fen is not None
    s = svc.opening_practice.proceed(s.session_id)
    assert s.state == "your_move" and s.replies == ((E5, "e5"),)


def test_help_is_a_loss(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    s = svc.opening_practice.show_answer(s.session_id)
    assert s.state == "helped" and s.correct_moves == ((E4, "e4"),) and s.wrong == 1
    rows_ = svc.opening_practice._attempts.for_color("white")
    assert [r.outcome for r in rows_] == ["helped"]


def test_a_line_with_a_miss_counts_as_lost(svc: Any) -> None:
    add_italian(svc, moves=2)
    sid = session(svc).session_id
    s = svc.opening_practice.play(sid, "d2d4")
    s = svc.opening_practice.proceed(sid)
    while s.state == "your_move":
        answer = svc.repertoire.edges("white")
        key = position_key(chess.Board(s.fen))
        s = svc.opening_practice.play(sid, next(e.move_uci for e in answer if e.position_key == key))
    assert s.state == "line_end" and s.lines_lost == 1 and s.lines_clean == 0


@pytest.mark.parametrize("uci", ["e2e5", "banana", None, 3])
def test_an_illegal_move_is_refused_and_not_counted(svc: Any, uci: Any) -> None:
    add_italian(svc)
    s = session(svc)
    with pytest.raises(ValidationError):
        svc.opening_practice.play(s.session_id, uci)
    assert svc.opening_practice._attempts.for_color("white") == []


def test_moving_when_its_not_your_turn_is_refused(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    with pytest.raises(ConflictError):
        svc.opening_practice.play(s.session_id, E4)


def test_an_ended_session_says_so(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    svc.opening_practice.end(s.session_id)
    with pytest.raises(NotFoundError):
        svc.opening_practice.play(s.session_id, E4)


def test_the_tolerance_is_off_by_default_and_counts_when_on(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    assert svc.opening_practice.tolerance_on() is False
    assert svc.opening_practice.play(s.session_id, "d2d4").state == "wrong"
    svc.opening_practice.set_tolerance(True)
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    assert s.state == "your_move" and "Close enough" in (s.message or "")
    assert s.replies == ((E5, "e5"),)  # your line goes on from your own move


# ---- the schedule, with the injected clock -------------------------------------------------------------------


def play_all_correct(svc: Any, color: str = "white", **kw: Any) -> Any:
    s = session(svc, color, **kw)
    while s.state != "finished":
        if s.state == "your_move":
            key = position_key(chess.Board(s.fen))
            answer = next(e.move_uci for e in svc.repertoire.edges(color) if e.position_key == key)
            s = svc.opening_practice.play(s.session_id, answer)
        else:
            s = svc.opening_practice.proceed(s.session_id)
    return s


def test_nothing_is_due_until_tomorrow_then_it_is(svc: Any, clock: Any) -> None:
    add_italian(svc, moves=2)
    positions = svc.opening_practice.summary("white")["positions"]
    assert svc.opening_practice.summary("white")["new"] == positions > 0
    play_all_correct(svc)
    summary = svc.opening_practice.summary("white")
    assert summary == {"due": 0, "new": 0, "positions": positions}
    assert session(svc).state == "finished"
    clock.advance(days=1)
    assert svc.opening_practice.summary("white")["due"] == positions


def test_a_miss_comes_back_tomorrow(svc: Any, clock: Any) -> None:
    add_italian(svc, moves=2)
    s = session(svc)
    svc.opening_practice.play(s.session_id, "d2d4")
    clock.advance(days=1)
    assert svc.opening_practice.summary("white")["due"] >= 1


def test_new_lines_come_a_few_at_a_time(svc: Any) -> None:
    add_italian(svc, subs=3, moves=8)
    s = session(svc, new_limit=2)
    assert s.remaining == 2


def test_a_session_can_be_limited_to_one_opening(svc: Any) -> None:
    add_italian(svc)
    opening = svc.repertoire.view("white").openings[0]
    assert session(svc, opening_id=opening.id).state == "your_move"
    with pytest.raises(NotFoundError):
        session(svc, opening_id=999)


def test_a_session_can_be_limited_to_one_branch(svc: Any) -> None:
    add_italian(svc)
    e4 = after(STARTING_KEY, E4)
    s = session(svc, branch=after(e4, E5))
    assert s.state == "your_move" and s.replies == ()
    s = svc.opening_practice.play(s.session_id, E4)  # the walk there is still played
    with pytest.raises(NotFoundError):
        session(svc, branch="nowhere")


def test_walking_through_a_position_doesnt_move_it_up(svc: Any, clock: Any) -> None:
    add_italian(svc, moves=2)
    play_all_correct(svc)
    clock.advance(days=1)
    play_all_correct(svc)
    before = svc.opening_practice._cards("white", svc.repertoire.edges("white"))
    e5 = after(after(STARTING_KEY, E4), E5)
    assert before[e5].box == 2
    # Only the later position is due now; the first move is walked through, not reviewed.
    clock.advance(days=3)
    s = session(svc, branch=e5)
    s = svc.opening_practice.play(s.session_id, E4)
    assert s.correct == 1


@pytest.mark.parametrize(
    ("kw", "bad"), [({"mode": "x"}, 1), ({"limit": 0}, 1), ({"limit": True}, 1), ({"new_limit": -1}, 1)]
)
def test_bad_session_options_are_refused(svc: Any, kw: dict[str, Any], bad: int) -> None:
    add_italian(svc)
    with pytest.raises(ValidationError):
        session(svc, **kw)


# ---- mistake reasons and isolation -----------------------------------------------------------------------------


def test_a_reason_is_stored_under_its_own_source(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    svc.opening_practice.set_reason(s.attempt_id, "rushed", "too fast")
    with svc.db.session() as conn:
        row = conn.execute("SELECT source, ref_id, reason, note FROM mistake_reasons").fetchone()
    assert tuple(row) == ("opening", str(s.attempt_id), "rushed", "too fast")


def test_a_reason_on_a_correct_move_is_refused(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, E4)
    with pytest.raises(ConflictError):
        svc.opening_practice.set_reason(s.attempt_id, "rushed")
    with pytest.raises(ValidationError):
        svc.opening_practice.set_reason(s.attempt_id, "nonsense")
    with pytest.raises(NotFoundError):
        svc.opening_practice.set_reason(9999, "rushed")


def test_practice_leaves_puzzles_ratings_sync_and_the_coach_alone(svc: Any) -> None:
    add_italian(svc)
    tables = ("attempts", "sync_queue", "game_analysis", "coach_reports", "training_plans", "journal_entries")

    def counts() -> dict[str, int]:
        out: dict[str, int] = {}
        with svc.db.session() as conn:
            existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for t in tables:
                if t in existing:
                    out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out

    before = counts()
    assert "attempts" in before
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    svc.opening_practice.set_reason(s.attempt_id, "rushed")
    svc.opening_practice.proceed(s.session_id)
    assert counts() == before


def test_a_reason_here_doesnt_reach_the_puzzle_reason_stats(svc: Any) -> None:
    add_italian(svc)
    before = svc.stats.reason_stats() if hasattr(svc.stats, "reason_stats") else None
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    svc.opening_practice.set_reason(s.attempt_id, "rushed")
    if before is not None:
        assert svc.stats.reason_stats() == before


# ---- stats (FR-12.11) ---------------------------------------------------------------------------------------------


def test_stats_per_opening_and_line(svc: Any, clock: Any) -> None:
    add_italian(svc, subs=1, moves=4)
    s = session(svc, new_limit=1)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    stat = svc.opening_practice.stats("white")[0]
    assert stat.name == "Italian Game" and stat.positions >= 2
    assert stat.attempts == 1 and stat.correct == 0  # v0.13-B26: its own first moves count
    assert stat.lines and all(ln.name.startswith("Italian Game") for ln in stat.lines)


def test_stats_name_the_weakest_positions(svc: Any) -> None:
    add_italian(svc, "black")
    root = svc.repertoire.view("black").openings[0].root_key  # after 3.Bc4: Black's move
    s = session(svc, "black", branch=root, new_limit=1)
    while position_key(chess.Board(s.fen)) != root:
        key = position_key(chess.Board(s.fen))
        s = svc.opening_practice.play(
            s.session_id, next(e.move_uci for e in svc.repertoire.edges("black") if e.position_key == key)
        )
    s = svc.opening_practice.play(s.session_id, "h7h6")
    stat = svc.opening_practice.stats("black")[0]
    assert stat.attempts == 1 and stat.correct == 0
    assert stat.weakest[0].position_key == root and "Bc4" in stat.weakest[0].label


def test_stats_are_per_color(svc: Any) -> None:
    add_italian(svc)
    assert svc.opening_practice.stats("black") == []


# ---- through the bridge --------------------------------------------------------------------------------------------


@pytest.fixture
def api(svc: Any, paths: Any, clock: Any) -> Any:
    from tests.helpers import build_api

    a = build_api(paths, clock)
    a._openings.set_extend(False)
    a._openings.set_scope("custom", 0, 4)
    a._repertoire.add_lines("white", "Italian Game", [0])
    return a


def ok(response: dict[str, Any]) -> Any:
    assert response["ok"], response
    return response["data"]


def test_a_wrong_move_brings_the_reason_prompt(api: Any) -> None:
    s = ok(api.start_practice("white", "due"))
    assert s["reason_prompt"] is None
    s = ok(api.play_practice_move(s["session_id"], "d2d4"))
    prompt = s["reason_prompt"]
    assert prompt["source"] == "opening" and prompt["attempt_id"] == s["attempt_id"] and len(prompt["reasons"]) == 6
    ok(api.set_practice_reason(s["attempt_id"], "rushed", None))


def test_a_build_goes_through_the_job_and_needs_saving(api: Any) -> None:
    before = len(ok(api.get_repertoire("black"))["rows"])
    job = ok(
        api.start_repertoire_build("black", "Italian Game", {"max_moves": 4, "max_replies": 2, "max_positions": 10})
    )
    st = api._runner.wait(job, 30)
    assert st.state == "done"
    p = ok(api.get_repertoire_proposal(st.message))
    assert p["moves"] and p["color"] == "black"
    assert len(ok(api.get_repertoire("black"))["rows"]) == before
    assert ok(api.save_repertoire_proposal(p["id"]))["added"] > 0


def test_a_games_opening_finds_its_family_for_the_coach_link(api: Any) -> None:
    assert ok(api.match_opening_family("Italian Game: Giuoco Piano")) == "Italian Game"
    assert ok(api.match_opening_family("Nothing Like It")) is None


# ---- gaps found reviewing against FR-12.8, 12.9 and the plan ------------------------------------------------------


def test_all_doesnt_move_a_position_through_the_schedule(svc: Any, clock: Any) -> None:
    add_italian(svc)
    play_all_correct(svc)
    edges = svc.repertoire.edges("white")
    before = svc.opening_practice._cards("white", edges)
    attempts = len(svc.opening_practice._attempts.for_color("white"))
    assert all(c is not None and c.box == 1 for c in before.values())
    s = play_all_correct(svc, mode="all")  # nothing's due yet: it's all review
    assert s.correct > 0
    assert len(svc.opening_practice._attempts.for_color("white")) == attempts
    assert svc.opening_practice._cards("white", edges) == before


def test_all_still_counts_what_was_due(svc: Any, clock: Any) -> None:
    add_italian(svc)
    play_all_correct(svc)
    clock.advance(days=1)
    edges = svc.repertoire.edges("white")
    play_all_correct(svc, mode="all")
    assert all(c is not None and c.box == 2 for c in svc.opening_practice._cards("white", edges).values())


def test_a_miss_in_all_still_counts(svc: Any, clock: Any) -> None:
    add_italian(svc)
    play_all_correct(svc)
    s = session(svc, mode="all")
    s = svc.opening_practice.play(s.session_id, "d2d4")
    assert s.state == "wrong" and s.attempt_id is not None
    assert svc.opening_practice.summary("white")["due"] == 0  # back in box 1, due tomorrow
    clock.advance(days=1)
    assert svc.opening_practice.summary("white")["due"] >= 1


def test_a_miss_says_which_position_to_find_its_note(svc: Any) -> None:
    add_italian(svc)
    s = session(svc)
    s = svc.opening_practice.play(s.session_id, "d2d4")
    assert s.position_key == STARTING_KEY and s.correct_moves[0][0] == E4
