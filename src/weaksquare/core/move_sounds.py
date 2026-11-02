"""Which sound a move makes (FR-1.13). Pure; python-chess decides, so the front end plays what it's told.

Priority: checkmate > check > capture (en passant and capturing promotions included) > castling >
an ordinary move. A mate plays only the mate sound, even when it also captures or checks.
"""

from __future__ import annotations

from typing import Literal

import chess

MoveSound = Literal["move", "capture", "check", "checkmate", "castle"]


def sound_for(board: chess.Board, move: chess.Move) -> MoveSound:
    """The sound of `move` played from `board` (which isn't changed)."""
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return "checkmate"
    if after.is_check():
        return "check"
    if board.is_capture(move):
        return "capture"
    if board.is_castling(move):
        return "castle"
    return "move"


def sounds_for_line(fen: str, ucis: list[str] | tuple[str, ...]) -> list[MoveSound]:
    """The sound of each move of a line played from `fen` (for Show answer's steps)."""
    board = chess.Board(fen)
    out: list[MoveSound] = []
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        out.append(sound_for(board, move))
        board.push(move)
    return out
