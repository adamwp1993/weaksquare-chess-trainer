"""Theme tags for a tactic line, from the vendored lichess-puzzler tagger (FR-10.12).

The tagger reads a Lichess-shaped puzzle: the position before the opponent's move, that move, then
the solver's line, which ends on a solver move. Game mistakes supply the move before the position
(the opponent's last move for Missed, your mistake for Allowed). An imported puzzle has none, so a
null move stands in for it; tags that look at that move then see nothing (FR-10.49).

Only keys in Lichess's public theme list are kept, so the tags match the puzzle DB exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

import chess
import chess.pgn

from weaksquare.core import themes
from weaksquare.vendor.lichess_puzzler.cook import cook
from weaksquare.vendor.lichess_puzzler.model import Puzzle

MATE_CP = 999_999  # what lichess-puzzler stores as the cp of a mate puzzle


def _root_without_premove(fen: str) -> chess.Board | None:
    """The puzzle position with the other side to move, so a null move brings it back."""
    board = chess.Board(fen)
    board.turn = not board.turn
    board.ep_square = None
    return board if board.king(chess.WHITE) is not None and board.king(chess.BLACK) is not None else None


def tag_line(fen: str, premove: str | None, line: Sequence[str], cp: int) -> tuple[str, ...]:
    """Lichess theme keys for a tactic.

    - ``fen`` is the position before ``premove``, or the solver's position when ``premove`` is None.
    - ``line`` is the solver's line in UCI, starting with the solver's move. It's cut at the first
      illegal move and trimmed to end on a solver move.
    - ``cp`` is the solver's eval after the line, from the solver's view (any value for a mate).

    Returns () when there's nothing legal to tag.
    """
    try:
        if premove is None:
            root = _root_without_premove(fen)
            first = chess.Move.null()
        else:
            root = chess.Board(fen)
            first = chess.Move.from_uci(premove)
            if first not in root.legal_moves:
                return ()
    except ValueError:
        return ()
    if root is None:
        return ()
    game = chess.pgn.Game()
    game.setup(root)
    node: chess.pgn.GameNode = game.add_variation(first)
    board = node.board()
    played: list[chess.pgn.ChildNode] = []
    for uci in line:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        node = node.add_variation(move)
        played.append(node)
        board.push(move)
    if len(played) % 2 == 0:  # the line must end on the solver's move
        if not played:
            return ()
        played[-1].parent.variations.clear()
    try:
        tags = cook(Puzzle("local", game, cp))
    except (AssertionError, AttributeError, IndexError, KeyError, ValueError):
        return ()  # the tagger assumes Lichess-shaped input; anything else stays untagged
    return tuple(dict.fromkeys(t for t in tags if themes.is_known(t)))
