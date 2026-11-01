"""FR-1.13: each move maps to the right sound, and a mate plays only the mate sound."""

from __future__ import annotations

import chess
import pytest

from weaksquare.core.move_sounds import sound_for, sounds_for_line


@pytest.mark.parametrize(
    ("fen", "uci", "sound"),
    [
        # quiet move
        (chess.STARTING_FEN, "e2e4", "move"),
        # capture
        ("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "e4d5", "capture"),
        # check (Bb5+)
        ("rnbqkbnr/ppp2ppp/8/3pp3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 3", "f1b5", "check"),
        # checkmate (scholar's mate)
        ("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "h5f7", "checkmate"),
        # castling, both sides
        ("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1", "e1g1", "castle"),
        ("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1", "e1c1", "castle"),
        # en passant is a capture
        ("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3", "e5f6", "capture"),
        # promotion with capture is a capture; a quiet promotion is a move
        ("1r6/P7/7k/8/8/8/8/K7 w - - 0 1", "a7b8q", "capture"),
        ("7k/P7/8/8/8/8/8/K7 w - - 0 1", "a7a8n", "move"),
        # capture that gives check: the check sound
        ("4k3/8/8/8/8/8/4r3/4R2K w - - 0 1", "e1e2", "check"),
        # castling that gives check: the check sound
        ("5k2/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1", "check"),
    ],
)
def test_sound_for(fen: str, uci: str, sound: str) -> None:
    board = chess.Board(fen)
    before = board.fen()
    assert sound_for(board, chess.Move.from_uci(uci)) == sound
    assert board.fen() == before  # the board isn't changed


def test_mate_by_capture_plays_only_the_mate_sound() -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/r2R2K1 w - - 0 1")  # Rxa1 isn't mate; Rd8# is
    assert sound_for(board, chess.Move.from_uci("d1d8")) == "checkmate"
    capture_mate = chess.Board("3r2k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
    assert sound_for(capture_mate, chess.Move.from_uci("d1d8")) == "checkmate"


def test_sounds_for_line() -> None:
    assert sounds_for_line(chess.STARTING_FEN, ["e2e4", "d7d5", "e4d5"]) == ["move", "move", "capture"]
