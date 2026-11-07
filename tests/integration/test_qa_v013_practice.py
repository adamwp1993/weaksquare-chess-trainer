"""QA v0.13: Practice's schedule and session walk, deviations and Build my repertoire (FR-12.4, 12.8-12.11, 12.14).

Real database, real services, the fake engine, and a real clock path (`FixedClock.advance`). A test exposing an open bug
is marked xfail with its ID.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from weaksquare.adapters.db.repos.openings import OpeningAttemptsRepo
from weaksquare.core.opening_practice import BuildLimits, Popular, Sources, propose, schedule_position
from weaksquare.core.openings import STARTING_KEY, position_key
from weaksquare.core.repertoire import NewMove, after, reachable

E4, E5, NF3, NC6, BC4, D4, D5, NF6, C4 = "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "d2d4", "d7d5", "g8f6", "c2c4"
FAMILY = "Italian Game"


@pytest.fixture
def svc(services: Any, paths: Any) -> Any:
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    services.openings.import_now()
    services.openings.set_extend(False)
    return services


def store(svc: Any, color: str, *lines: list[str], source: str = "you") -> None:
    """Moves into the repertoire, connected from the start, through the same repo the services use."""
    for line in lines:
        board = chess.Board()
        moves = []
        for uci in line:
            move = chess.Move.from_uci(uci)
            moves.append(NewMove(position_key(board), uci, board.san(move), source))
            board.push(move)
        svc.repertoire._repo.add_moves(color, moves, "2026-11-01T12:00:00+00:00")


def attempts(svc: Any, color: str = "white") -> list[Any]:
    return list(svc.opening_practice._attempts.for_color(color))


def key_after(*moves: str) -> str:
    b = chess.Board()
    for m in moves:
        b.push(chess.Move.from_uci(m))
    return position_key(b)


def card(svc: Any, key: str, color: str = "white") -> Any:
    edges = svc.repertoire.edges(color)
    return svc.opening_practice._cards(color, edges)[key]


def run_session(svc: Any, color: str = "white", mode: str = "due", **kw: Any) -> Any:
    """Play your stored main move at every question until the session ends."""
    practice = svc.opening_practice
    s = practice.start(color, mode=mode, **kw)
    for _ in range(200):
        if s.state == "finished":
            return s
        if s.state == "your_move":
            answer = next(e for e in svc.repertoire.edges(color) if e.position_key == s.position_key and e.is_main)
            s = practice.play(s.session_id, answer.move_uci)
        else:
            s = practice.proceed(s.session_id)
    raise AssertionError("the session never finished")


# ---- the schedule -------------------------------------------------------------------------------------------------


def test_the_boxes_run_all_the_way_to_graduation_with_the_injected_clock(svc: Any, clock: Any) -> None:
    """FR-12.10: first right answer -> box 1, then 3, 7, 14, 30 days; after box 5 it graduates and stops coming up."""
    store(svc, "white", [E4, E5])
    key = STARTING_KEY
    run_session(svc)
    c = card(svc, key)
    assert (c.box, c.graduated) == (1, False)
    today = clock.local_date(clock.now())
    assert c.due == today + timedelta(days=1)
    for wait, box in ((1, 2), (3, 3), (7, 4), (14, 5)):
        clock.advance(days=wait)
        assert svc.opening_practice.summary("white")["due"] == 1
        run_session(svc)
        assert card(svc, key).box == box
    clock.advance(days=30)
    run_session(svc)
    assert card(svc, key).graduated and card(svc, key).due is None
    clock.advance(days=400)
    assert svc.opening_practice.summary("white") == {"due": 0, "new": 0, "positions": 1}
    s = svc.opening_practice.start("white", mode="due")
    assert s.state == "finished" and s.decisions == 0


def test_a_position_not_yet_due_is_not_asked_for_and_not_recorded(svc: Any, clock: Any) -> None:
    store(svc, "white", [E4, E5])
    run_session(svc)
    n = len(attempts(svc))
    s = svc.opening_practice.start("white", mode="due")
    assert s.state == "finished" and len(attempts(svc)) == n


def test_right_answers_on_the_walk_to_something_due_stay_off_the_record(svc: Any, clock: Any) -> None:
    """e4 is not due; the deeper position is. Only the deeper position's answer is recorded and moves up."""
    store(svc, "white", [E4, E5, NF3, NC6])
    run_session(svc)
    assert len(attempts(svc)) == 2
    deep = key_after(E4, E5)
    # Today's walk: make only the deeper one due, by missing it.
    s = svc.opening_practice.start("white", mode="all")
    s = svc.opening_practice.play(s.session_id, E4)
    s = svc.opening_practice.play(s.session_id, "a2a3")
    assert s.state == "wrong"
    svc.opening_practice.end(s.session_id)
    clock.advance(days=1)
    # Both are due tomorrow: answer both; e4 box 2 (3 days), deep box 2 (the miss was box 1).
    run_session(svc)
    clock.advance(days=3)
    root_box = card(svc, STARTING_KEY).box
    deep_box = card(svc, deep).box
    assert root_box == 2 and deep_box == 2


def test_a_miss_on_the_walk_counts_even_if_the_position_wasnt_due(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6])
    run_session(svc)
    assert card(svc, STARTING_KEY).due is not None
    s = svc.opening_practice.start("white", mode="all")
    s = svc.opening_practice.play(s.session_id, D4)
    assert s.state == "wrong" and attempts(svc)[-1].outcome == "wrong"


def test_each_position_is_recorded_once_a_session(svc: Any) -> None:
    """All has the same position reached by two ways: one attempt, however many times it comes up."""
    store(svc, "white", [E4, E5, NF3, NC6], [NF3, NC6, E4, E5])  # both orders reach one position, and it's yours
    run_session(svc, mode="all")
    keys = [a.position_key for a in attempts(svc)]
    assert len(keys) == len(set(keys))


def test_a_wrong_answer_resets_a_high_box_and_a_right_one_climbs_again(clock: Any) -> None:
    from weaksquare.core.opening_practice import CORRECT, WRONG, Review

    t = clock.now()
    reviews = [Review(t, CORRECT), Review(t, CORRECT), Review(t, CORRECT), Review(t, WRONG), Review(t, CORRECT)]
    c = schedule_position(reviews, (1, 3, 7, 14, 30), clock.local_date)
    assert c is not None and c.box == 2 and c.due == clock.local_date(t) + timedelta(days=3)


def test_a_miss_after_graduating_puts_it_back_in_box_one(clock: Any) -> None:
    from weaksquare.core.opening_practice import CORRECT, WRONG, Review

    t = clock.now()
    c = schedule_position([Review(t, CORRECT)] * 6 + [Review(t, WRONG)], (1, 3, 7, 14, 30), clock.local_date)
    assert c is not None and c.box == 1 and not c.graduated


def test_new_lines_mode_takes_only_unseen_positions_nearest_the_root(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4])
    s = svc.opening_practice.start("white", mode="new", limit=1)
    assert s.target_reason == "new" and s.remaining == 1 and s.position_key == STARTING_KEY


def test_all_doesnt_record_a_right_answer_on_a_graduated_position(svc: Any, clock: Any) -> None:
    store(svc, "white", [E4, E5])
    for wait in (0, 1, 3, 7, 14, 30):
        clock.advance(days=wait)
        run_session(svc)
    n = len(attempts(svc))
    assert card(svc, STARTING_KEY).graduated
    run_session(svc, mode="all")
    assert len(attempts(svc)) == n and card(svc, STARTING_KEY).graduated


@pytest.mark.xfail(
    reason="v0.13-B13: the approved plan says Practice all drills graduated positions without changing the schedule; "
    "a miss there sends a graduated position back to box 1",
    strict=True,
)
def test_all_leaves_a_graduated_position_on_the_schedule_it_had(svc: Any, clock: Any) -> None:
    store(svc, "white", [E4, E5])
    for wait in (0, 1, 3, 7, 14, 30):
        clock.advance(days=wait)
        run_session(svc)
    assert card(svc, STARTING_KEY).graduated
    s = svc.opening_practice.start("white", mode="all")
    svc.opening_practice.play(s.session_id, D4)
    assert card(svc, STARTING_KEY).graduated


# ---- the walk ----------------------------------------------------------------------------------------------------


def test_a_line_that_ends_on_your_move_just_ends(svc: Any) -> None:
    store(svc, "white", [E4, E5])
    s = svc.opening_practice.start("white", mode="all")
    s = svc.opening_practice.play(s.session_id, E4)
    assert s.state == "line_end" and s.lines_clean == 1 and s.replies == ((E5, "e5"),)
    s = svc.opening_practice.proceed(s.session_id)
    assert s.state == "finished"


def test_a_line_that_ends_on_their_move_just_ends(svc: Any) -> None:
    store(svc, "white", [E4])
    s = svc.opening_practice.start("white", mode="all")
    s = svc.opening_practice.play(s.session_id, E4)
    assert s.state == "line_end" and s.replies == ()


def test_as_black_a_line_with_no_answer_at_the_first_reply_doesnt_ask(svc: Any) -> None:
    """Stored: only White's e4 (no answer). There's no decision point at all, so nothing to practise."""
    store(svc, "black", [E4])
    assert svc.opening_practice.summary("black")["positions"] == 0
    assert svc.opening_practice.start("black", mode="all").state == "finished"


def test_leaving_the_path_by_another_stored_move_reaches_the_target_on_a_later_walk(svc: Any) -> None:
    """Two stored answers at the start. The target hangs off e4; you play d4. The session goes back for it."""
    store(svc, "white", [E4, E5, NF3], [D4, D5, C4])
    target = key_after(E4, E5)
    practice = svc.opening_practice
    s = practice.start("white", mode="all", branch=target)
    assert s.position_key == STARTING_KEY
    s = practice.play(s.session_id, D4)
    # Off the path: the walk carries on down your other line, then returns.
    assert s.state == "your_move" and s.position_key == key_after(D4, D5)
    s = practice.play(s.session_id, C4)
    assert s.state == "line_end"
    assert s.remaining == 1
    s = practice.proceed(s.session_id)
    s = practice.play(s.session_id, E4)
    assert s.position_key == target


def test_continuing_after_a_miss_on_the_path_can_leave_it_without_losing_the_target(svc: Any) -> None:
    """Your main move at the start isn't the path's. After a miss, Continue plays your main move: the target stays."""
    store(svc, "white", [D4, D5, C4], [E4, E5, NF3])
    target = key_after(E4, E5)
    practice = svc.opening_practice
    s = practice.start("white", mode="all", branch=target)
    s = practice.play(s.session_id, "a2a3")
    assert s.state == "wrong"
    s = practice.proceed(s.session_id)
    assert s.position_key == key_after(D4, D5)
    s = practice.play(s.session_id, C4)
    s = practice.proceed(s.session_id)
    assert s.state == "your_move" and s.remaining == 1


def test_the_path_is_followed_through_the_opponents_choices(svc: Any) -> None:
    """Many replies stored, one leads to the target: the walk must take it every time, whatever the weights say."""
    store(svc, "white", [E4, E5, NF3], [E4, "c7c5", "b1c3"], [E4, "e7e6", D4], [E4, "c7c6", D4], [E4, D5, "e4d5"])
    target = key_after(E4, D5)
    for _ in range(10):
        s = svc.opening_practice.start("white", mode="all", branch=target)
        s = svc.opening_practice.play(s.session_id, E4)
        assert s.position_key == target


def test_a_transposition_is_one_position_and_is_drilled_from_either_order(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4], [NF3, NC6, E4, E5, BC4])
    same = key_after(E4, E5, NF3, NC6)
    assert same == key_after(NF3, NC6, E4, E5)
    assert sum(1 for e in svc.repertoire.edges("white") if e.position_key == same) == 1
    s = svc.opening_practice.start("white", mode="all", branch=same)
    assert s.remaining == 1


def test_a_session_ends_when_every_target_is_gone(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4])
    final = run_session(svc, mode="all")
    assert final.state == "finished" and final.remaining == 0 and final.correct == 3 and final.wrong == 0


def test_limit_stops_a_session_between_lines(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3], [D4, D5, C4])
    final = run_session(svc, mode="all", limit=1)
    assert final.state == "finished"


def test_a_session_never_asks_more_than_its_limit(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4, NF6, D4])
    final = run_session(svc, mode="all", limit=1)
    assert final.decisions <= 1


def test_a_position_whose_answer_was_removed_mid_session_doesnt_loop(svc: Any) -> None:
    """As Black, reaching it takes none of your moves, so the session's position limit never ends it either."""
    store(svc, "black", [E4, E5], [D4, D5])
    practice = svc.opening_practice
    s = practice.start("black", mode="all")
    assert s.position_key == key_after(D4) or s.position_key == key_after(E4)
    other = key_after(E4) if s.position_key == key_after(D4) else key_after(D4)
    gone = E5 if other == key_after(E4) else D5
    answer = D5 if gone == E5 else E5
    svc.repertoire.remove("black", other, gone)
    s = practice.play(s.session_id, answer)
    for _ in range(20):
        if s.state == "finished":
            break
        s = practice.proceed(s.session_id)
    assert s.state == "finished", (s.state, s.lines_clean)


def test_a_position_removed_entirely_mid_session_is_skipped(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4], [D4, D5, C4])
    practice = svc.opening_practice
    s = practice.start("white", mode="all")
    svc.repertoire.remove("white", STARTING_KEY, E4)
    assert s.state == "your_move"
    s = practice.play(s.session_id, D4)
    s = practice.play(s.session_id, C4)
    s = practice.proceed(s.session_id)
    assert s.state == "finished"


def test_a_move_that_was_right_until_it_was_removed_is_now_wrong(svc: Any) -> None:
    store(svc, "white", [E4, E5], [D4, D5])
    practice = svc.opening_practice
    s = practice.start("white", mode="all")
    svc.repertoire.remove("white", STARTING_KEY, E4)
    s = practice.play(s.session_id, E4)
    assert s.state == "wrong" and [m[0] for m in s.correct_moves] == [D4]


def test_help_then_continue_when_the_answer_has_gone_ends_the_line(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3])
    practice = svc.opening_practice
    s = practice.start("white", mode="all")
    s = practice.play(s.session_id, E4)
    s = practice.show_answer(s.session_id)
    assert s.state == "helped"
    svc.repertoire.remove("white", key_after(E4, E5), NF3)
    s = practice.proceed(s.session_id)
    assert s.state == "line_end" and s.lines_lost == 1


def test_show_answer_on_a_position_counts_as_a_miss_for_the_schedule(svc: Any) -> None:
    store(svc, "white", [E4, E5])
    s = svc.opening_practice.start("white", mode="all")
    svc.opening_practice.show_answer(s.session_id)
    assert attempts(svc)[-1].outcome == "helped" and card(svc, STARTING_KEY).box == 1


def test_a_failed_move_never_changes_the_session(svc: Any) -> None:
    from weaksquare.core.errors import ValidationError

    store(svc, "white", [E4, E5])
    s = svc.opening_practice.start("white", mode="all")
    for bad in ("e2e5", "x", "", None, 3):
        with pytest.raises(ValidationError):
            svc.opening_practice.play(s.session_id, bad)
    after_bad = svc.opening_practice.play(s.session_id, E4)
    assert after_bad.decisions == 1 and after_bad.correct == 1


def test_a_wrong_mate_is_handled_with_tolerance_on(svc: Any) -> None:
    """Tolerance on; a move that ends the game. The engine has nothing to say about a finished game."""
    store(svc, "white", [E4, "f7f6", D4, "g7g5", "b1c3"])
    practice = svc.opening_practice
    practice.set_tolerance(True)
    s = practice.start("white", mode="all")
    s = practice.play(s.session_id, E4)
    s = practice.play(s.session_id, D4)
    s = practice.play(s.session_id, "d1h5")  # mate: not your line
    assert s.state in ("wrong", "your_move", "line_end")


def test_tolerance_uses_your_side_of_the_eval_as_black(svc: Any) -> None:
    """A stored eval is White-relative. As Black, a move that gives the game away is not close."""
    from weaksquare.core.engine import EngineLine

    store(svc, "black", [E4, E5, NF3])
    practice = svc.opening_practice
    practice.set_tolerance(True)
    cp = {key_after(E4): -10, key_after(E4, "f7f6"): 500, key_after(E4, "c7c5"): -5}

    def lines(key: str) -> list[EngineLine]:
        return [EngineLine(cp[key], None, ("a2a3",))]

    practice._openings.interactive_lines = lines  # type: ignore[method-assign]
    s = practice.start("black", mode="all")
    assert s.state == "your_move"
    good = practice.play(s.session_id, "c7c5")
    assert good.state != "wrong" and "Close enough" in (good.message or "")
    s = practice.start("black", mode="all")
    bad = practice.play(s.session_id, "f7f6")
    assert bad.state == "wrong"


# ---- deviations (FR-12.8) ----------------------------------------------------------------------------------------


def test_a_deviation_is_connected_to_the_root_and_reaches_practice(svc: Any) -> None:
    svc.repertoire.add_deviation("white", [E4, E5, NF3], "f7f6", "f3e5")
    edges = svc.repertoire.edges("white")
    assert {(e.position_key, e.move_uci) for e in edges} == reachable(edges)
    assert key_after(E4, E5, NF3, "f7f6") in svc.opening_practice._cards("white", edges)


def test_a_deviation_never_overwrites_a_stored_move(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4], source="book")
    before = {(e.position_key, e.move_uci): e for e in svc.repertoire.edges("white")}
    svc.repertoire.add_deviation("white", [E4, E5, NF3], NC6, "f1b5")  # the same their-move, a different reply
    after_edges = {(e.position_key, e.move_uci): e for e in svc.repertoire.edges("white")}
    for k, e in before.items():
        assert after_edges[k] == e
    assert (key_after(E4, E5, NF3, NC6), "f1b5") in after_edges
    assert after_edges[(key_after(E4, E5, NF3, NC6), BC4)].is_main


def test_a_deviation_that_ends_the_game_has_no_replies_and_cant_be_added(svc: Any) -> None:
    from weaksquare.core.errors import ValidationError

    moves = [chess.Move.from_uci(m).uci() for m in ("f2f3", "e7e5", "g2g4")]
    d = svc.repertoire.what_if("white", moves, "Qh4#")
    assert d.replies == () and d.game_over
    with pytest.raises(ValidationError):
        svc.repertoire.add_deviation("white", moves, "d8h4", "a2a3")


def test_the_moves_leading_to_a_deviation_keep_their_true_source(svc: Any) -> None:
    """Extend on, a line past the book: a move there came from the engine, and stays labelled so."""
    from weaksquare.jobs.runner import CancelToken

    svc.openings.set_extend(True)
    svc.openings.set_scope("custom", 0, 20)
    book = svc.openings.lines(FAMILY, None, False).lines
    svc.openings.extend_now(book, 20, CancelToken(), lambda *_: None)
    line = svc.openings.lines(FAMILY).lines[0]
    past = [i for i, m in enumerate(line.moves) if m.source == "engine"]
    assert past
    # A position past the book where it's Black's move, so a deviation can hang from it (as White).
    at = next(i for i in past if (i + 1) % 2 == 1)
    moves = [m.uci for m in line.moves[: at + 1]]
    board = chess.Board()
    for m in moves:
        board.push(chess.Move.from_uci(m))
    their = next(iter(board.legal_moves))
    b2 = board.copy()
    b2.push(their)
    svc.repertoire.add_deviation("white", moves, their.uci(), next(iter(b2.legal_moves)).uci())
    stored = {(e.position_key, e.move_uci): e.source for e in svc.repertoire.edges("white")}
    assert stored[(line.moves[at].key_before, line.moves[at].uci)] == "engine"


def test_a_deviation_shows_up_in_stats(svc: Any) -> None:
    svc.repertoire.add_deviation("white", [E4, E5, NF3, NC6, BC4], "a7a6", "d2d3")
    assert svc.opening_practice.summary("white")["positions"] > 0
    assert svc.opening_practice.stats("white") != []


# ---- Build my repertoire (FR-12.14) -------------------------------------------------------------------------------


def _sources(svc: Any, stored: dict[str, list[Any]] | None = None, popular: Any = None) -> Sources:
    def engine(board: chess.Board) -> list[Any]:
        return FakeEngine().analyse(board, 0.1, 3) if not board.is_game_over() else []

    return Sources(popular or (lambda _b: None), svc.openings.book_moves, engine, stored or {})


def test_a_saved_proposal_is_connected_to_the_root_and_nothing_is_saved_first(svc: Any) -> None:
    p = svc.repertoire.build_now("white", FAMILY, {"max_moves": 8, "max_positions": 30})
    assert svc.repertoire.edges("white") == []
    svc.repertoire.save_proposal(p.id)
    edges = svc.repertoire.edges("white")
    assert edges and {(e.position_key, e.move_uci) for e in edges} == reachable(edges)
    assert len(svc.repertoire.openings("white")) == 1


def test_a_move_stored_after_the_build_stays_as_it_was(svc: Any) -> None:
    p = svc.repertoire.build_now("white", FAMILY, {"max_moves": 6})
    store(svc, "white", [E4, E5], source="you")
    before = {(e.position_key, e.move_uci): e for e in svc.repertoire.edges("white")}
    r = svc.repertoire.save_proposal(p.id)
    assert r.kept >= 2
    now = {(e.position_key, e.move_uci): e for e in svc.repertoire.edges("white")}
    for k, e in before.items():
        assert now[k] == e


def test_your_stored_answer_is_never_replaced_by_a_better_one(svc: Any) -> None:
    store(svc, "white", [E4, E5, "a2a3"], source="you")
    p = svc.repertoire.build_now("white", FAMILY, {"max_moves": 8})
    # Italian's root runs through 3. Bc4, so its own start moves are proposed as well, and a3 stays yours at its position.
    svc.repertoire.save_proposal(p.id)
    here = [e for e in svc.repertoire.edges("white") if e.position_key == key_after(E4, E5)]
    main = next(e for e in here if e.is_main)
    assert main.move_uci == "a2a3" and main.source == "you"


@pytest.mark.parametrize("limit", [5, 8, 20])
def test_the_position_limit_holds(svc: Any, limit: int) -> None:
    root = svc.openings.root(FAMILY)
    moves = propose(root.moves, "white", BuildLimits(20, 0.0, 6, limit), _sources(svc))
    asked = {m.position_key for m in moves[len(root.moves) :]}
    assert len(asked) <= limit


def test_the_depth_limit_holds(svc: Any) -> None:
    root = svc.openings.root(FAMILY)
    moves = propose(root.moves, "white", BuildLimits(5, 0.0, 6, 200), _sources(svc))
    assert max(m.depth for m in moves) < 10


def test_replies_under_the_share_limit_are_left_out_and_few_games_is_flagged(svc: Any) -> None:
    def popular(_board: chess.Board) -> tuple[int, list[Popular]]:
        moves = [m.uci() for m in list(_board.legal_moves)[:3]]
        return 40, [Popular(moves[0], 30), Popular(moves[1], 9), Popular(moves[2], 1)]

    root = svc.openings.root(FAMILY)
    moves = propose(root.moves, "white", BuildLimits(4, 0.05, 3, 3), _sources(svc, popular=popular))
    replies = [m for m in moves[len(root.moves) :] if not m.yours]
    assert replies and all((m.share or 0) >= 0.05 for m in replies)
    assert all("few_games" in m.flags for m in replies)
    assert all(not m.flags or m.flags == ("few_games",) for m in replies)


def test_illegal_explorer_moves_never_enter_a_proposal(svc: Any) -> None:
    def popular(_board: chess.Board) -> tuple[int, list[Popular]]:
        return 1000, [Popular("a1a8", 900), Popular("zzzz", 100)]

    root = svc.openings.root(FAMILY)
    # `_legal` drops them, and a bad UCI string is not a crash.
    moves = propose(root.moves, "white", BuildLimits(6, 0.0, 3, 10), _sources(svc, popular=popular))
    board = chess.Board()
    seen = {position_key(board)}
    for m in moves:
        assert chess.Move.from_uci(m.move_uci) in chess.Board(f"{m.position_key} 0 1").legal_moves
        seen.add(after(m.position_key, m.move_uci))


def test_a_build_with_no_engine_and_no_explorer_is_refused(services: Any) -> None:
    from weaksquare.core.engine import EngineNotInstalled

    services.openings.import_now()
    with pytest.raises(EngineNotInstalled):
        services.repertoire.start_build("white", FAMILY, {})


# ---- what a removal leaves ------------------------------------------------------------------------------------------


def test_removing_a_line_keeps_a_position_another_line_still_reaches(svc: Any) -> None:
    store(svc, "white", [E4, E5, NF3, NC6, BC4], [NF3, NC6, E4, E5, "b1c3"])
    shared = key_after(E4, E5, NF3, NC6)
    svc.repertoire.remove("white", STARTING_KEY, E4)
    edges = svc.repertoire.edges("white")
    assert {e.move_uci for e in edges if e.position_key == shared} == {BC4, "b1c3"}


def test_an_opening_with_no_moves_left_is_no_longer_listed(svc: Any) -> None:
    svc.openings.set_scope("custom", 0, 4)
    svc.repertoire.add_lines("white", FAMILY, [0])
    svc.repertoire.remove("white", STARTING_KEY, E4)
    assert svc.repertoire.edges("white") == []
    assert list(svc.repertoire.view("white").openings) == []


def test_opening_attempts_stay_in_their_own_table(svc: Any, paths: Any) -> None:
    assert isinstance(svc.opening_practice._attempts, OpeningAttemptsRepo)
    store(svc, "white", [E4, E5])
    run_session(svc)
    assert len(attempts(svc)) == 1


def test_tolerance_in_practice_uses_the_interactive_engine(svc: Any) -> None:
    store(svc, "white", [E4, E5])
    svc.opening_practice.set_tolerance(True)
    s = svc.opening_practice.start("white", mode="all")
    svc.opening_practice.play(s.session_id, D4)
    assert svc.engine._bg is None


def test_a_miss_on_an_openings_own_first_moves_shows_in_its_stats(svc: Any) -> None:
    svc.openings.set_scope("custom", 0, 4)
    svc.repertoire.add_lines("white", FAMILY, [0])
    s = svc.opening_practice.start("white", mode="all")
    assert s.position_key == STARTING_KEY
    svc.opening_practice.play(s.session_id, "a2a3")
    stat = svc.opening_practice.stats("white")[0]
    assert stat.attempts == 1 and stat.correct == 0
