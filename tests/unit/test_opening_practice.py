"""The opening trainer's pure rules (v0.13, FR-12.8-12.10, 12.14): the schedule, what comes up, and proposals."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import chess
import pytest

from weaksquare.core.engine import EngineLine
from weaksquare.core.opening_practice import (
    CORRECT,
    FLAG_BAD_EVAL,
    FLAG_ENGINE,
    FLAG_FEW_GAMES,
    HELPED,
    WRONG,
    BuildLimits,
    Popular,
    Review,
    Sources,
    due_and_new,
    parse_their_move,
    path_sources,
    path_to,
    pick_reply,
    propose,
    schedule_position,
    subtree_positions,
)
from weaksquare.core.openings import STARTING_KEY, position_key
from weaksquare.core.repertoire import Edge, after, line_to_moves
from weaksquare.core.srs import Card

INTERVALS = (1, 3, 7)
DAY0 = datetime(2026, 11, 1, 12, tzinfo=UTC)


def local(d: datetime) -> date:
    return d.date()


def review(outcome: str, day: int = 0) -> Review:
    return Review(DAY0 + timedelta(days=day), outcome)


def graph(*lines: list[str]) -> list[Edge]:
    out: dict[tuple[str, str], Edge] = {}
    for line in lines:
        for m in line_to_moves([(uci, "book") for uci in line]):
            out.setdefault((m.position_key, m.move_uci), Edge(m.position_key, m.move_uci, m.san, m.source))
    return list(out.values())


# ---- the schedule ---------------------------------------------------------------------------------------


def test_never_tried_has_no_card() -> None:
    assert schedule_position([], INTERVALS, local) is None


def test_the_first_correct_starts_at_box_1() -> None:
    card = schedule_position([review(CORRECT)], INTERVALS, local)
    assert card == Card(1, date(2026, 11, 2))


def test_correct_answers_climb_then_graduate() -> None:
    reviews = [review(CORRECT), review(CORRECT, 1)]
    assert schedule_position(reviews, INTERVALS, local) == Card(2, date(2026, 11, 5))
    reviews.append(review(CORRECT, 4))
    assert schedule_position(reviews, INTERVALS, local) == Card(3, date(2026, 11, 12))
    reviews.append(review(CORRECT, 11))
    card = schedule_position(reviews, INTERVALS, local)
    assert card is not None and card.graduated and card.due is None


@pytest.mark.parametrize("outcome", [WRONG, HELPED])
def test_a_miss_or_help_goes_back_to_box_1_even_after_graduating(outcome: str) -> None:
    climbed = [review(CORRECT, d) for d in (0, 1, 4, 11)]
    assert schedule_position([*climbed, review(outcome, 20)], INTERVALS, local) == Card(1, date(2026, 11, 22))


def test_a_first_miss_is_due_the_next_day() -> None:
    assert schedule_position([review(WRONG)], INTERVALS, local) == Card(1, date(2026, 11, 2))


def test_shrinking_the_intervals_cant_break_a_card() -> None:
    reviews = [review(CORRECT, d) for d in (0, 1, 4)]
    assert schedule_position(reviews, (1, 3), local) is not None


# ---- what comes up -------------------------------------------------------------------------------------------

LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]


def test_due_comes_before_new_and_most_overdue_first() -> None:
    edges = graph(LINE)
    e4 = after(STARTING_KEY, "e2e4")
    e5 = after(e4, "e7e5")
    nf3 = after(e5, "g1f3")
    nc6 = after(nf3, "b8c6")
    cards = {
        STARTING_KEY: None,
        e5: Card(1, date(2026, 11, 3)),
        nc6: Card(2, date(2026, 11, 1)),
    }
    targets = due_and_new(edges, "white", cards, date(2026, 11, 5))
    assert [t.position_key for t in targets] == [nc6, e5, STARTING_KEY]
    assert [t.reason for t in targets] == ["due", "due", "new"]


def test_a_position_not_due_yet_stays_away() -> None:
    edges = graph(LINE)
    cards = {STARTING_KEY: Card(1, date(2026, 12, 1))}
    keys = [t.position_key for t in due_and_new(edges, "white", cards, date(2026, 11, 5))]
    assert STARTING_KEY not in keys


def test_a_graduated_position_stays_away() -> None:
    edges = graph(LINE)
    cards = {STARTING_KEY: Card(3, None, True)}
    assert STARTING_KEY not in [t.position_key for t in due_and_new(edges, "white", cards, date(2026, 11, 5))]


def test_new_lines_come_a_few_at_a_time_nearest_the_root() -> None:
    edges = graph(LINE)
    targets = due_and_new(edges, "white", {}, date(2026, 11, 5), new_limit=2)
    assert len(targets) == 2 and targets[0].position_key == STARTING_KEY


def test_a_session_can_be_limited_to_a_branch() -> None:
    edges = graph(["e2e4", "e7e5", "g1f3"], ["e2e4", "c7c5", "g1f3"])
    e4 = after(STARTING_KEY, "e2e4")
    branch = subtree_positions(edges, after(e4, "c7c5"))
    keys = {t.position_key for t in due_and_new(edges, "white", {}, date(2026, 11, 5), within=branch)}
    assert keys == {after(e4, "c7c5")}


def test_a_path_is_found_even_through_a_transposition() -> None:
    edges = graph(["g1f3", "d7d5", "d2d4", "g8f6"], ["d2d4", "d7d5", "g1f3", "g8f6"])
    target = after(after(after(STARTING_KEY, "g1f3"), "d7d5"), "d2d4")
    path = path_to(edges, target)
    assert path is not None and len(path) == 3
    assert path_to(edges, "not a position") is None


def test_replies_favor_the_main_one() -> None:
    a = Edge("k", "e7e5", "e5", "book", is_main=True)
    b = Edge("k", "c7c5", "c5", "book")
    rng = random.Random(1)
    counts = Counter(pick_reply([a, b], rng).san for _ in range(1000))
    assert counts["e5"] > counts["c5"] * 2


def test_replies_favor_what_is_popular_when_known() -> None:
    a = Edge("k", "e7e5", "e5", "book", is_main=True)
    b = Edge("k", "c7c5", "c5", "book")
    rng = random.Random(1)
    counts = Counter(pick_reply([a, b], rng, {"c7c5": 900, "e7e5": 100}).san for _ in range(1000))
    assert counts["c5"] > counts["e5"] * 3


# ---- "What if they play…?" -------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["e4", "e2e4", " e4 "])
def test_a_move_can_be_san_or_uci(text: str) -> None:
    move = parse_their_move(chess.Board(), text)
    assert move is not None and move.uci() == "e2e4"


@pytest.mark.parametrize("text", ["e5", "e2e5", "banana", "", None, 3])
def test_an_illegal_move_is_refused(text: object) -> None:
    assert parse_their_move(chess.Board(), text) is None


def test_a_deviations_path_says_what_came_from_the_book() -> None:
    def is_book(key: str, uci: str) -> bool:
        return uci == "e2e4"

    assert path_sources(["e2e4", "a7a6"], is_book) == [("e2e4", "book"), ("a7a6", "you")]


# ---- Build my repertoire ------------------------------------------------------------------------------------------


def engine_says(best: dict[str, str] | None = None, cp: int = 20):  # type: ignore[no-untyped-def]
    """An engine: the given best move per position, otherwise the first legal move."""

    def run(board: chess.Board) -> Sequence[EngineLine]:
        if board.is_game_over():
            return []
        uci = (best or {}).get(position_key(board)) or next(iter(board.legal_moves)).uci()
        return [EngineLine(cp, None, (uci,))]

    return run


def sources(
    popular: dict[str, tuple[int, list[Popular]]] | None = None,
    book: dict[str, list[str]] | None = None,
    stored: dict[str, list[Edge]] | None = None,
    engine: object = None,
) -> Sources:
    return Sources(
        popular=lambda b: (popular or {}).get(position_key(b)),
        book=lambda b: (book or {}).get(position_key(b), []),
        engine=engine or engine_says(),  # type: ignore[arg-type]
        stored=stored or {},
    )


E4 = after(STARTING_KEY, "e2e4")
TINY = BuildLimits(max_moves=2, min_share=0.05, max_replies=3, max_positions=60)


def test_a_proposal_answers_each_reply_once_for_you() -> None:
    popular = {E4: (1000, [Popular("e7e5", 600), Popular("c7c5", 400)])}
    moves = propose(["e2e4"], "white", TINY, sources(popular))
    assert {m.san for m in moves if not m.yours} >= {"e5", "c5"}
    by_position: dict[str, int] = {}
    for m in moves:
        if m.yours:
            by_position[m.position_key] = by_position.get(m.position_key, 0) + 1
    assert set(by_position.values()) == {1}


def test_rare_replies_are_left_out_and_the_count_is_limited() -> None:
    popular = {E4: (1000, [Popular("e7e5", 600), Popular("c7c5", 300), Popular("d7d5", 80), Popular("g8f6", 20)])}
    moves = propose(["e2e4"], "white", TINY, sources(popular))
    replies = {m.san for m in moves if m.position_key == E4}
    assert replies == {"e5", "c5", "d5"}
    limited = propose(["e2e4"], "white", BuildLimits(2, 0.05, 2, 60), sources(popular))
    assert {m.san for m in limited if m.position_key == E4} == {"e5", "c5"}


def test_signed_out_falls_back_to_book_replies() -> None:
    moves = propose(["e2e4"], "white", TINY, sources(book={E4: ["e7e5", "c7c5"]}))
    replies = [m for m in moves if m.position_key == E4]
    assert {m.san for m in replies} == {"e5", "c5"} and {m.source for m in replies} == {"book"}


def test_your_answer_prefers_what_you_have_then_the_book() -> None:
    e5 = after(E4, "e7e5")
    mine = {e5: [Edge(e5, "b1c3", "Nc3", "you")]}
    book = {E4: ["e7e5"], e5: ["g1f3"]}
    move = next(m for m in propose(["e2e4"], "white", TINY, sources(book=book, stored=mine)) if m.position_key == e5)
    assert move.san == "Nc3" and move.already_yours and move.source == "you"
    move = next(m for m in propose(["e2e4"], "white", TINY, sources(book=book)) if m.position_key == e5)
    assert move.san == "Nf3" and move.source == "book" and not move.already_yours


def test_your_answer_is_the_most_played_when_its_close_to_best() -> None:
    e5 = after(E4, "e7e5")
    popular = {E4: (1000, [Popular("e7e5", 900)]), e5: (900, [Popular("f2f4", 800)])}
    answer = next(m for m in propose(["e2e4"], "white", TINY, sources(popular)) if m.position_key == e5)
    assert answer.san == "f4" and answer.source == "explorer" and FLAG_ENGINE not in answer.flags


def test_a_popular_move_far_from_best_gives_way_to_the_engine_and_is_flagged() -> None:
    e5 = after(E4, "e7e5")
    popular = {E4: (1000, [Popular("e7e5", 900)]), e5: (900, [Popular("f2f4", 800)])}

    def engine(board: chess.Board) -> Sequence[EngineLine]:
        if position_key(board) == e5:
            return [EngineLine(100, None, ("g1f3",))]
        return [EngineLine(-200, None, (next(iter(board.legal_moves)).uci(),))]

    answer = next(m for m in propose(["e2e4"], "white", TINY, sources(popular, engine=engine)) if m.position_key == e5)
    assert answer.san == "Nf3" and answer.source == "engine" and FLAG_ENGINE in answer.flags


def test_too_few_games_and_a_bad_eval_are_flagged() -> None:
    popular = {E4: (10, [Popular("e7e5", 9)])}
    moves = propose(["e2e4"], "white", TINY, sources(popular))
    assert FLAG_FEW_GAMES in next(m for m in moves if m.san == "e5").flags
    bad = propose(["e2e4"], "white", TINY, sources(popular, engine=engine_says(cp=-400)))
    assert any(FLAG_BAD_EVAL in m.flags for m in bad if m.yours)


def test_as_black_the_opponents_move_is_what_branches() -> None:
    moves = propose([], "black", BuildLimits(1, 0.05, 3, 60), sources(book={STARTING_KEY: ["e2e4", "d2d4"]}))
    assert {m.san for m in moves if not m.yours} == {"e4", "d4"}
    assert {m.yours for m in moves if m.position_key != STARTING_KEY} == {True}


def test_the_position_limit_keeps_the_moves_nearest_the_opening() -> None:
    replies = {STARTING_KEY: (100, [Popular("e2e4", 50), Popular("d2d4", 50)])}
    moves = propose([], "black", BuildLimits(6, 0.05, 2, 2), sources(replies))
    assert len({m.position_key for m in moves}) <= 3


def test_a_stored_opponent_reply_stays_in_the_tree() -> None:
    mine = {E4: [Edge(E4, "a7a6", "a6", "you")]}
    moves = propose(["e2e4"], "white", TINY, sources({E4: (100, [Popular("e7e5", 90)])}, stored=mine))
    a6 = next(m for m in moves if m.san == "a6")
    assert a6.already_yours and a6.source == "you"


def test_a_bad_move_from_a_source_cant_enter() -> None:
    popular = {E4: (100, [Popular("a1a8", 90), Popular("bad", 5)])}
    moves = propose(["e2e4"], "white", TINY, sources(popular))
    assert all(m.move_uci not in ("a1a8", "bad") for m in moves)
    assert all(chess.Move.from_uci(m.move_uci) for m in moves)
