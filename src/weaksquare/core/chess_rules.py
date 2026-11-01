"""Puzzle semantics (REQUIREMENTS §4.2). Pure functions over python-chess.

- FEN is the position BEFORE the opponent's move. moves[0] is the opponent's move; the player
  solves from moves[1] on.
- The player's color is the side NOT to move in the FEN.
- Length (player moves) = len(moves) // 2. Buckets: 1 one-move, 2 short, 3 long, 4+ very long.
- Every player move is an only-move, except that when the expected move mates, any mate is accepted.
"""

from __future__ import annotations

import re

import chess

from weaksquare.core.puzzle import Color

UCI_MOVE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
LENGTH_BUCKETS = (1, 2, 3, 4)  # 4 means "4 or more"


class PuzzleDataError(ValueError):
    """The puzzle's FEN or move list isn't legal chess."""


def player_color_from_fen(fen: str) -> Color:
    """Cheap version for the importer: reads the side-to-move field only."""
    parts = fen.split()
    if len(parts) != 6 or parts[1] not in ("w", "b"):
        raise PuzzleDataError("FEN must have 6 fields and a side to move")
    return "black" if parts[1] == "w" else "white"


def player_color(fen: str) -> Color:
    board = _board(fen)
    return "black" if board.turn == chess.WHITE else "white"


def puzzle_length(moves: list[str] | tuple[str, ...]) -> int:
    return len(moves) // 2


def length_bucket(length: int) -> int:
    return max(1, min(length, 4))


def looks_like_move_list(moves: list[str]) -> bool:
    """Cheap shape check for the importer: at least an opponent move and one player move, all UCI."""
    return len(moves) >= 2 and all(UCI_MOVE.match(m) for m in moves)


def _board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise PuzzleDataError(f"invalid FEN: {e}") from None
    if not board.is_valid():
        raise PuzzleDataError("FEN is not a legal position")
    return board


def _move(board: chess.Board, uci: str) -> chess.Move:
    try:
        move = chess.Move.from_uci(uci)
    except chess.InvalidMoveError:
        raise PuzzleDataError(f"not a UCI move: {uci!r}") from None
    if move not in board.legal_moves:
        raise PuzzleDataError(f"illegal move {uci} in {board.fen()}")
    return move


def validate_line(fen: str, moves: list[str] | tuple[str, ...]) -> None:
    """Raise PuzzleDataError unless every move is legal in sequence from `fen`."""
    if len(moves) < 2:
        raise PuzzleDataError("a puzzle needs the opponent's move and at least one player move")
    board = _board(fen)
    for uci in moves:
        board.push(_move(board, uci))


def start_position(fen: str, moves: list[str] | tuple[str, ...]) -> tuple[chess.Board, chess.Move]:
    """The board the player solves from (after the opponent's first move), and that move."""
    validate_line(fen, moves)
    board = _board(fen)
    opponent = _move(board, moves[0])
    board.push(opponent)
    return board, opponent


def parse_move(board: chess.Board, uci: str) -> chess.Move | None:
    """A legal move from untrusted input, or None."""
    if not isinstance(uci, str) or not UCI_MOVE.match(uci):
        return None
    try:
        move = chess.Move.from_uci(uci)
    except chess.InvalidMoveError:  # e.g. "a1a1": well-formed but not a move
        return None
    return move if move in board.legal_moves else None


def is_acceptable(board: chess.Board, played: chess.Move, expected: chess.Move) -> bool:
    """Is `played` a correct solution move where the solution says `expected`?

    It must be the expected move, except that when the expected move gives checkmate, any legal
    checkmating move is accepted (§4.2).
    """
    if played == expected:
        return True
    if played not in board.legal_moves:
        return False
    after_expected = board.copy(stack=False)
    after_expected.push(expected)
    if not after_expected.is_checkmate():
        return False
    after_played = board.copy(stack=False)
    after_played.push(played)
    return after_played.is_checkmate()
