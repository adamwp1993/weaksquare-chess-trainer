"""Setting up a position on the Analysis tab (v0.15, FR-14.2). Pure: a FEN in, a verdict out, no I/O.

A position from the editor or a pasted FEN is checked with python-chess's `Board.status()`, and every problem it finds
gets one plain sentence. Only a position with no problems is ever sent to Stockfish (FR-7.6); `core.engine.validate_fen`
checks it again on the way in.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

MAX_FEN_LEN = 100

# python-chess status flags → what to tell you, in the order they're listed. Several can apply at once.
_PROBLEMS: tuple[tuple[int, str], ...] = (
    (chess.STATUS_EMPTY, "The board is empty. Put both kings on it."),
    (chess.STATUS_NO_WHITE_KING, "White has no king."),
    (chess.STATUS_NO_BLACK_KING, "Black has no king."),
    (chess.STATUS_TOO_MANY_KINGS, "There can be only one king of each color."),
    (chess.STATUS_TOO_MANY_WHITE_PAWNS, "White has more than 8 pawns."),
    (chess.STATUS_TOO_MANY_BLACK_PAWNS, "Black has more than 8 pawns."),
    (chess.STATUS_PAWNS_ON_BACKRANK, "A pawn can't stand on the first or last rank."),
    (chess.STATUS_TOO_MANY_WHITE_PIECES, "White has more than 16 pieces."),
    (chess.STATUS_TOO_MANY_BLACK_PIECES, "Black has more than 16 pieces."),
    (
        chess.STATUS_BAD_CASTLING_RIGHTS,
        "A castling right doesn't match the board: the king and that rook must be on their starting squares.",
    ),
    (chess.STATUS_INVALID_EP_SQUARE, "The en passant square doesn't match the last pawn move."),
    (chess.STATUS_OPPOSITE_CHECK, "The side that isn't to move is in check, so it can't be their opponent's turn."),
    (chess.STATUS_TOO_MANY_CHECKERS, "The king is in check from too many pieces at once to be a real position."),
    (chess.STATUS_IMPOSSIBLE_CHECK, "The king is in check in a way no legal move could have caused."),
)


@dataclass(frozen=True)
class PositionCheck:
    """`fen` is the position, tidied, when `problems` is empty; otherwise None and nothing reaches the engine."""

    fen: str | None
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def check_fen(fen: object) -> PositionCheck:
    """A pasted FEN or the editor's position: can it be analyzed? Never raises."""
    if not isinstance(fen, str) or not fen.strip():
        return PositionCheck(None, ("Paste a FEN, or set up a position on the board.",))
    text = " ".join(fen.split())
    if len(text) > MAX_FEN_LEN:
        return PositionCheck(None, ("That's too long to be a FEN.",))
    try:
        board = chess.Board(text)
    except ValueError:
        return PositionCheck(
            None,
            ("That isn't a FEN. A FEN looks like rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",),
        )
    return check_board(board)


def check_board(board: chess.Board) -> PositionCheck:
    status = board.status()
    if status == chess.STATUS_VALID:
        return PositionCheck(board.fen(), ())
    if status & chess.STATUS_EMPTY:
        return PositionCheck(None, (_PROBLEMS[0][1],))  # an empty board also has no kings: one sentence is enough
    problems = tuple(text for flag, text in _PROBLEMS if status & flag)
    return PositionCheck(None, problems or ("That position isn't legal.",))
