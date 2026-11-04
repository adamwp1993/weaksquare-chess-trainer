"""Habit tags: each one on positions where it applies and where it doesn't (FR-10.27)."""

from __future__ import annotations

import chess
import pytest

from weaksquare.core.habits import HABIT_DRILLS, HABITS, MoveContext, habit_tags


def ctx(fen: str, uci: str, *, previous: tuple[str, str] | None = None, reply: str | None = None) -> MoveContext:
    before = chess.Board(fen)
    prev_board = prev_move = None
    if previous:
        prev_board = chess.Board(previous[0])
        prev_move = chess.Move.from_uci(previous[1])
        b = prev_board.copy()
        b.push(prev_move)
        assert b.board_fen() == before.board_fen(), "previous + move must lead to the position"
    return MoveContext(
        before, chess.Move.from_uci(uci), prev_board, prev_move, chess.Move.from_uci(reply) if reply else None
    )


def tags(c: MoveContext) -> set[str]:
    return set(habit_tags(c))


# ---- hungPiece -----------------------------------------------------------------------------------
def test_hung_queen_to_a_pawn() -> None:
    assert "hungPiece" in tags(ctx("6k1/8/4p3/8/8/8/8/3Q2K1 w - - 0 1", "d1d5"))


def test_hung_knight_to_the_queen() -> None:
    assert "hungPiece" in tags(ctx("3qk3/8/8/8/8/5N2/8/6K1 w - - 0 1", "f3g5"))


def test_safe_square_is_not_hung() -> None:
    assert "hungPiece" not in tags(ctx("6k1/8/4p3/8/8/8/8/3Q2K1 w - - 0 1", "d1d4"))


def test_defended_knight_against_a_queen_is_not_hung() -> None:
    assert "hungPiece" not in tags(ctx("3qk3/8/8/8/7P/5N2/8/6K1 w - - 0 1", "f3g5"))


# ---- missedFreeCapture ---------------------------------------------------------------------------
def test_missed_a_free_queen() -> None:
    assert "missedFreeCapture" in tags(ctx("4k3/8/8/8/3q4/5N2/P7/7K w - - 0 1", "a2a3"))


def test_missed_a_free_rook() -> None:
    assert "missedFreeCapture" in tags(ctx("r3k3/8/8/8/8/8/6B1/6K1 w - - 0 1", "g1h1"))


def test_taking_it_is_not_missed() -> None:
    assert "missedFreeCapture" not in tags(ctx("4k3/8/8/8/3q4/5N2/P7/7K w - - 0 1", "f3d4"))


def test_nothing_to_take() -> None:
    assert "missedFreeCapture" not in tags(ctx("4k3/8/8/8/8/5N2/P7/6K1 w - - 0 1", "a2a3"))


# ---- ignoredThreat -------------------------------------------------------------------------------
PAWN_PREV = ("4k3/8/4p3/8/3N4/8/8/4K3 b - - 0 1", "e6e5")
PAWN_NOW = "4k3/8/8/4p3/3N4/8/8/4K3 w - - 0 2"
FORK_PREV = ("4k3/8/2n5/8/8/8/7P/R3K3 b - - 0 1", "c6b4")
FORK_NOW = "4k3/8/8/8/1n6/8/7P/R3K3 w - - 0 2"


def test_ignored_a_pawn_attacking_the_knight() -> None:
    assert "ignoredThreat" in tags(ctx(PAWN_NOW, "e1e2", previous=PAWN_PREV))


def test_ignored_a_fork_threat() -> None:
    assert "ignoredThreat" in tags(ctx(FORK_NOW, "h2h3", previous=FORK_PREV))


def test_moving_the_knight_away_answers_the_threat() -> None:
    assert "ignoredThreat" not in tags(ctx(PAWN_NOW, "d4f3", previous=PAWN_PREV))


def test_moving_the_rook_answers_the_fork_threat() -> None:
    assert "ignoredThreat" not in tags(ctx(FORK_NOW, "a1d1", previous=FORK_PREV))


def test_no_previous_move_means_no_threat() -> None:
    assert "ignoredThreat" not in tags(ctx(PAWN_NOW, "e1e2"))


# ---- movedDefender -------------------------------------------------------------------------------
DEFENDER = "4k3/8/8/8/1b6/2N5/3Q4/4K3 w - - 0 1"


def test_queen_was_the_only_defender_and_the_knight_fell() -> None:
    assert "movedDefender" in tags(ctx(DEFENDER, "d2h6", reply="b4c3"))


def test_queen_was_the_only_defender_without_a_known_reply() -> None:
    assert "movedDefender" in tags(ctx(DEFENDER, "d2h6"))


def test_knight_did_not_fall() -> None:
    assert "movedDefender" not in tags(ctx(DEFENDER, "d2h6", reply="e8e7"))


def test_a_second_defender_stays() -> None:
    assert "movedDefender" not in tags(ctx("4k3/8/8/8/1b6/2N5/1P1Q4/4K3 w - - 0 1", "d2h6", reply="b4c3"))


# ---- general -------------------------------------------------------------------------------------
def test_illegal_move_has_no_tags() -> None:
    assert habit_tags(ctx("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1e3")) == ()


def test_a_quiet_good_move_has_no_tags() -> None:
    assert habit_tags(ctx(chess.STARTING_FEN, "e2e4")) == ()


def test_mate_is_never_a_habit() -> None:
    # Back-rank mate leaves the f-pawn's defender behind; nothing is "hung" by mating.
    assert habit_tags(ctx("6k1/5ppp/8/8/8/8/q4PPP/3R2K1 w - - 0 1", "d1d8")) == ()


@pytest.mark.parametrize("habit", HABITS)
def test_every_habit_maps_to_drills(habit: str) -> None:
    themes, _mode = HABIT_DRILLS[habit]
    assert themes
