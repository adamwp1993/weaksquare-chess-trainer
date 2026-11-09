"""v0.15, FR-14.2: a set-up position or pasted FEN gets a clear message per problem, and only a legal one passes."""

from __future__ import annotations

import pytest

from weaksquare.core.position_setup import check_fen

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KINGS_ONLY = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"


@pytest.mark.parametrize("fen", [START, KINGS_ONLY, "4k3/8/8/8/8/8/4q3/4K3 w - - 0 1", "  " + KINGS_ONLY + "  "])
def test_a_legal_position_passes_with_its_fen(fen: str) -> None:
    c = check_fen(fen)
    assert c.ok and c.problems == () and c.fen == " ".join(fen.split())


@pytest.mark.parametrize(
    ("fen", "says"),
    [
        ("8/8/8/8/8/8/8/8 w - - 0 1", "empty"),
        ("4k3/8/8/8/8/8/8/8 w - - 0 1", "White has no king"),
        ("8/8/8/8/8/8/8/4K3 w - - 0 1", "Black has no king"),
        ("4k3/8/8/8/8/8/8/K3K3 w - - 0 1", "only one king"),
        ("4k3/8/8/8/8/PPPPPPPP/P7/4K3 w - - 0 1", "White has more than 8 pawns"),
        ("4k3/p7/pppppppp/8/8/8/8/4K3 w - - 0 1", "Black has more than 8 pawns"),
        ("P3k3/8/8/8/8/8/8/4K3 w - - 0 1", "first or last rank"),
        ("4k3/8/8/8/8/8/8/4K3 w K - 0 1", "castling right"),
        ("4k3/8/8/8/8/8/8/4K3 w - e3 0 1", "en passant"),
        ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", "isn't to move is in check"),
        ("k7/8/3n4/8/4K3/6n1/5n2/8 w - - 0 1", "too many pieces at once"),
        ("4k3/8/8/8/8/8/8/1q2K1q1 w - - 0 1", "no legal move could have caused"),
    ],
)
def test_each_problem_has_its_own_sentence_and_no_fen(fen: str, says: str) -> None:
    c = check_fen(fen)
    assert not c.ok and c.fen is None
    assert any(says in p for p in c.problems), c.problems


def test_an_empty_board_gets_one_sentence_not_three() -> None:
    assert len(check_fen("8/8/8/8/8/8/8/8 w - - 0 1").problems) == 1


def test_several_problems_are_all_listed() -> None:
    c = check_fen("P7/8/8/8/8/8/8/8 w K - 0 1")  # no kings, a pawn on the back rank, a castling right
    assert len(c.problems) >= 3


@pytest.mark.parametrize("fen", ["", "   ", None, 42, "hello world", "x" * 101, "rnbqkbnr/pppppppp/8 w"])
def test_text_that_isnt_a_fen_gets_a_message(fen: object) -> None:
    c = check_fen(fen)
    assert not c.ok and c.fen is None and c.problems


def test_chess960_castling_is_refused_as_a_castling_mismatch() -> None:
    c = check_fen("bqnb1rkr/pp3ppp/3ppn2/2p5/5P2/P2P4/NPP1P1PP/BQ1BNRKR w HFhf - 2 9")
    assert not c.ok and "castling right" in c.problems[0]
