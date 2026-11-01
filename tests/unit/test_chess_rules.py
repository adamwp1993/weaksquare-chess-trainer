"""§4.2 puzzle semantics against 10 known puzzles (Done-when item 1), plus the mate-in-1 exception.

The expected values are written out by hand from the puzzle rows in tests/fixtures/puzzles_sample.csv:
FEN is before the opponent's move, moves[0] is the opponent's, the player is the side NOT to move
in the FEN, and length = len(moves) // 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess
import pytest

from weaksquare.core.chess_rules import (
    PuzzleDataError,
    is_acceptable,
    length_bucket,
    parse_move,
    player_color,
    player_color_from_fen,
    puzzle_length,
    start_position,
    validate_line,
)


@dataclass(frozen=True)
class Known:
    id: str
    fen: str
    moves: str
    color: str
    opponent_move: str
    solution: tuple[str, ...]  # the player's moves only
    length: int
    bucket: int
    note: str


KNOWN = [
    Known("001KR", "6Qk/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K b - - 0 28", "h8g8 f1f8",
          "white", "h8g8", ("f1f8",), 1, 1, "mate in 1; d1d8 also mates"),
    Known("00fK0", "r2q1r2/pp3pk1/2np1Np1/2pN1b2/2B4Q/3P4/PPP3PP/R5K1 b - - 1 17", "f5e6 h4h7",
          "white", "f5e6", ("h4h7",), 1, 1, "mate in 1, single mate"),
    Known("01RLM", "3rk2r/ppp2ppp/5n2/4p3/4P1b1/2P2N2/PPP2PPP/R1B1K2R w KQk - 0 9", "f3e5 d8d1",
          "black", "f3e5", ("d8d1",), 1, 1, "player is black"),
    Known("1nPlu", "1q5r/R7/4pk2/1pPp1p2/3P4/2P1bBP1/Q4P2/2R3K1 w - - 0 38", "c1c2 b8g3 f3g2 h8g8",
          "black", "c1c2", ("b8g3", "h8g8"), 2, 2, "short, player black"),
    Known("0OT49", "2r2rk1/5pbp/1q2p1p1/4P3/pB1pQP2/Pp1P4/1P4PP/2R2R1K b - - 1 25", "f7f5 e5f6 g7f6 b4f8",
          "white", "f7f5", ("e5f6", "b4f8"), 2, 2, "first player move is en passant"),
    Known("2bX51", "r3k2r/pp4p1/2p2qb1/2bp3p/4nB2/1QP1P2P/PP1N1P2/R3KB1R w KQkq - 2 15", "b3b7 e8g8 d2e4 g6e4",
          "black", "b3b7", ("e8g8", "g6e4"), 2, 2, "first player move is castling"),
    Known("03cYQ", "6rk/2p2q2/1p4rp/2PR1b1p/P6Q/1P2p1PP/5P1N/3R2K1 w - - 0 36", "h2f3 f5g4 h3g4 f7f3 d5h5 f3d1",
          "black", "h2f3", ("f5g4", "f7f3", "f3d1"), 3, 3, "long"),
    Known("0L0mP", "1r3nk1/3q3p/2p2QpP/b1P5/p2P3R/P2Br3/6P1/2KR4 b - - 0 25", "d7b7 d3c4 e3e6 c4e6 f8e6 f6e6",
          "white", "d7b7", ("d3c4", "c4e6", "f6e6"), 3, 3, "long, player white"),
    Known("00JaW", "8/r7/Pk5p/3R2p1/4p1P1/4P3/3K4/8 b - - 0 48", "a7a6 d5d6 b6a5 d6a6 a5a6 d2c3 a6b7 c3d4",
          "white", "a7a6", ("d5d6", "d6a6", "d2c3", "c3d4"), 4, 4, "very long"),
    Known("04TL9", "8/8/4K1p1/p5P1/4P3/8/4k3/8 w - - 0 57", "e6f6 a5a4 e4e5 a4a3 f6f7 a3a2 e5e6 a2a1q",
          "black", "e6f6", ("a5a4", "a4a3", "a3a2", "a2a1q"), 4, 4, "ends in a promotion"),
]  # fmt: skip


@pytest.mark.parametrize("p", KNOWN, ids=lambda p: f"{p.id}-{p.note}")
def test_known_puzzle(p: Known) -> None:
    moves = p.moves.split()
    assert player_color(p.fen) == p.color
    assert player_color_from_fen(p.fen) == p.color
    assert puzzle_length(moves) == p.length
    assert length_bucket(p.length) == p.bucket
    assert tuple(moves[1::2]) == p.solution

    board, opponent = start_position(p.fen, moves)
    assert opponent.uci() == p.opponent_move
    # After the opponent's move it's the player's turn.
    assert board.turn == (chess.WHITE if p.color == "white" else chess.BLACK)
    # The solution plays out legally, alternating player move / opponent reply.
    for i, uci in enumerate(moves[1:]):
        move = chess.Move.from_uci(uci)
        assert move in board.legal_moves
        if i % 2 == 0:
            assert is_acceptable(board, move, move)
        board.push(move)


def test_en_passant_and_castling_are_recognised() -> None:
    ep = KNOWN[4]
    board, _ = start_position(ep.fen, ep.moves.split())
    assert board.is_en_passant(chess.Move.from_uci("e5f6"))
    castle = KNOWN[5]
    board, _ = start_position(castle.fen, castle.moves.split())
    assert board.is_castling(chess.Move.from_uci("e8g8"))


def test_mate_in_one_accepts_alternative_mate() -> None:
    p = KNOWN[0]
    board, _ = start_position(p.fen, p.moves.split())
    expected = chess.Move.from_uci("f1f8")
    assert is_acceptable(board, chess.Move.from_uci("f1f8"), expected)
    assert is_acceptable(board, chess.Move.from_uci("d1d8"), expected)  # the other mate
    non_mates = [m for m in board.legal_moves if m not in (expected, chess.Move.from_uci("d1d8"))]
    assert non_mates
    for m in non_mates:
        assert not is_acceptable(board, m, expected)


def test_mid_line_mate_alternative() -> None:
    """The exception applies to any solution move that mates, e.g. the last move of a longer line."""
    fen, moves = "kr6/pR4R1/2p5/8/q3PQ1p/Pn5P/KP4P1/8 b - - 0 41", ["b8b7", "g7g8", "b7b8", "f4b8"]
    board, _ = start_position(fen, moves)
    board.push_uci("g7g8")
    board.push_uci("b7b8")
    expected = chess.Move.from_uci("f4b8")
    assert is_acceptable(board, chess.Move.from_uci("g8b8"), expected)
    assert not is_acceptable(board, chess.Move.from_uci("f4f8"), expected)


def test_only_moves_when_not_mating() -> None:
    p = KNOWN[6]  # 03cYQ: f5g4 isn't a mate, so nothing else is accepted
    board, _ = start_position(p.fen, p.moves.split())
    expected = chess.Move.from_uci("f5g4")
    others = [m for m in board.legal_moves if m != expected]
    assert all(not is_acceptable(board, m, expected) for m in others)


def test_illegal_lines_are_rejected() -> None:
    with pytest.raises(PuzzleDataError):
        validate_line(KNOWN[0].fen, ["h8g8", "a2a5"])  # a pawn can't move three squares
    with pytest.raises(PuzzleDataError):
        validate_line("not a fen", ["e2e4", "e7e5"])
    with pytest.raises(PuzzleDataError):
        validate_line(KNOWN[0].fen, ["h8g8"])


def test_parse_move_rejects_untrusted_input() -> None:
    board, _ = start_position(KNOWN[0].fen, KNOWN[0].moves.split())
    assert parse_move(board, "f1f8") == chess.Move.from_uci("f1f8")
    for bad in ["", "f1f9", "e2e4", "f1f8x", "<script>", 42]:
        assert parse_move(board, bad) is None  # type: ignore[arg-type]
