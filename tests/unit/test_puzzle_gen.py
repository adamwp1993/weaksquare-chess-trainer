"""The quality check for puzzles from your games, ported from lichess-puzzler (FR-10.41)."""

from __future__ import annotations

from collections.abc import Sequence

import chess
import pytest

from weaksquare.core.engine import EngineLine
from weaksquare.core.puzzle_gen import MATE_SCORE, PovScore, check_position, validate_margin

BACK_RANK = "6k1/5ppp/7q/8/8/8/5PPP/3R2K1 w - - 0 1"  # the queen on h6 can't help
FORK = "r3k3/7p/8/3N4/8/8/8/6K1 w - - 0 1"  # White is down material: knight against rook and pawn


def L(cp: int | None = None, mate: int | None = None, pv: str = "") -> EngineLine:
    return EngineLine(cp, mate, tuple(pv.split()))


class Engine:
    """Answers by position (after the given moves from a start FEN); records every call."""

    def __init__(self, start: str, answers: dict[str, Sequence[EngineLine]]) -> None:
        self.answers: dict[str, Sequence[EngineLine]] = {}
        for moves, lines in answers.items():
            b = chess.Board(start)
            for m in moves.split():
                b.push_uci(m)
            self.answers[b.fen()] = lines
        self.calls: list[tuple[str, int]] = []

    def __call__(self, board: chess.Board, multipv: int) -> Sequence[EngineLine]:
        self.calls.append((board.fen(), multipv))
        return self.answers.get(board.fen(), [])


def test_win_chances() -> None:
    assert PovScore(cp=0).win_chances() == 0
    assert PovScore(mate=3).win_chances() == 1 and PovScore(mate=-2).win_chances() == -1
    assert 0.5 < PovScore(cp=300).win_chances() < 0.6


def test_a_clean_mate_in_one_needs_no_engine_call() -> None:
    engine = Engine(BACK_RANK, {})
    v = check_position(BACK_RANK, [L(mate=1, pv="d1d8"), L(cp=0, pv="g1f1")], PovScore(cp=0), engine)
    assert v.passed and v.line == ("d1d8",) and v.cp == MATE_SCORE
    assert engine.calls == []


def test_a_unique_best_move_extends_while_it_stays_the_only_move() -> None:
    engine = Engine(
        FORK,
        {
            "d5c7": [L(cp=500, pv="e8d7")],
            "d5c7 e8d7": [L(cp=520, pv="c7a8"), L(cp=-100, pv="g1f2")],
            "d5c7 e8d7 c7a8": [L(cp=510, pv="d7c6")],
            "d5c7 e8d7 c7a8 d7c6": [L(cp=500, pv="a8b6"), L(cp=480, pv="g1g2")],  # no longer only-move
        },
    )
    v = check_position(FORK, [L(cp=500, pv="d5c7 e8d7"), L(cp=-150, pv="g1f2")], PovScore(cp=0), engine)
    assert v.passed, v.reason
    assert v.line == ("d5c7", "e8d7", "c7a8") and v.cp == 520


def test_several_equally_good_moves_are_rejected() -> None:
    v = check_position(FORK, [L(cp=500, pv="d5c7"), L(cp=480, pv="d5b6")], PovScore(cp=0), Engine(FORK, {}))
    assert not v.passed and v.reason == "not_only_move"


def test_a_one_move_advantage_puzzle_is_dropped() -> None:
    engine = Engine(
        FORK,
        {
            "d5c7": [L(cp=500, pv="e8d7")],
            "d5c7 e8d7": [L(cp=520, pv="c7a8"), L(cp=500, pv="c7b5")],  # two good moves: the line ends
        },
    )
    v = check_position(FORK, [L(cp=500, pv="d5c7"), L(cp=-150, pv="g1f2")], PovScore(cp=0), engine)
    assert not v.passed and v.reason == "one_move"


@pytest.mark.parametrize(
    ("prev", "reason"),
    [(PovScore(cp=700), "decided"), (PovScore(cp=-700), "decided"), (PovScore(cp=350), "already_winning")],
)
def test_an_already_decided_position_is_rejected(prev: PovScore, reason: str) -> None:
    v = check_position(FORK, [L(cp=500, pv="d5c7"), L(cp=-150, pv="g1f2")], prev, Engine(FORK, {}))
    assert not v.passed and v.reason == reason


def test_being_up_material_already_is_rejected() -> None:
    fen = "4k3/8/8/3N4/8/8/8/R5K1 w - - 0 1"
    v = check_position(fen, [L(cp=900, pv="a1a8"), L(cp=0, pv="g1f1")], PovScore(cp=0), Engine(fen, {}))
    assert not v.passed and v.reason == "up_in_material"


def test_no_jump_means_no_tactic() -> None:
    v = check_position(FORK, [L(cp=150, pv="d5c7"), L(cp=-150, pv="g1f2")], PovScore(cp=0), Engine(FORK, {}))
    assert not v.passed and v.reason == "no_tactic"


def test_a_mate_line_follows_the_defence() -> None:
    fen = "r5k1/5ppp/7q/8/8/8/3R1PPP/3R2K1 w - - 0 1"  # 1. Rd8+ Rxd8 2. Rxd8#
    engine = Engine(
        fen,
        {
            "d2d8": [L(mate=-1, pv="a8d8")],
            "d2d8 a8d8": [L(mate=1, pv="d1d8"), L(cp=-900, pv="g1f1")],
        },
    )
    v = check_position(fen, [L(mate=2, pv="d2d8 a8d8 d1d8"), L(cp=-300, pv="d2d7")], PovScore(cp=0), engine)
    assert v.passed, v.reason
    assert v.line == ("d2d8", "a8d8", "d1d8") and v.cp == MATE_SCORE
    assert (_after(fen, "d2d8"), 1) in engine.calls  # the defence is the engine's move


def _after(fen: str, moves: str) -> str:
    b = chess.Board(fen)
    for m in moves.split():
        b.push_uci(m)
    return b.fen()


def test_illegal_engine_output_is_rejected_not_crashed() -> None:
    v = check_position(FORK, [L(cp=500, pv="a1a8"), L(cp=-150, pv="g1f2")], PovScore(cp=0), Engine(FORK, {}))
    assert not v.passed


def test_margin_validation() -> None:
    assert validate_margin(0.7) == 0.7
    with pytest.raises(ValueError):
        validate_margin(2)
    with pytest.raises(ValueError):
        validate_margin(True)
