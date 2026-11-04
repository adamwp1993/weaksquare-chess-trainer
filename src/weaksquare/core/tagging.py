"""Theme tags for a tactic line, from the vendored lichess-puzzler tagger (FR-10.12).

The tagger reads a Lichess-shaped puzzle: the position before the opponent's move, that move, then
the solver's line, which ends on a solver move. Game mistakes supply the move before the position
(the opponent's last move for Missed, your mistake for Allowed). An imported puzzle has none, so a
null move stands in for it; tags that look at that move then see nothing (FR-10.49).

Only keys in Lichess's public theme list are kept, so the tags match the puzzle DB exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import chess
import chess.pgn

from weaksquare.core import themes
from weaksquare.core.game_review import MoveRow, Score, saved_line
from weaksquare.core.habits import MoveContext, habit_tags
from weaksquare.vendor.lichess_puzzler.cook import cook
from weaksquare.vendor.lichess_puzzler.model import Puzzle

MATE_CP = 999_999  # what lichess-puzzler stores as the cp of a mate puzzle
GOALS = ("advantage", "crushing", "equality")  # picked from the cp, so dropped when it isn't known


def _root_without_premove(fen: str) -> chess.Board | None:
    """The puzzle position with the other side to move, so a null move brings it back."""
    board = chess.Board(fen)
    board.turn = not board.turn
    board.ep_square = None
    return board if board.king(chess.WHITE) is not None and board.king(chess.BLACK) is not None else None


def tag_line(fen: str, premove: str | None, line: Sequence[str], cp: int | None) -> tuple[str, ...]:
    """Lichess theme keys for a tactic.

    - ``fen`` is the position before ``premove``, or the solver's position when ``premove`` is None.
    - ``line`` is the solver's line in UCI, starting with the solver's move. It's cut at the first
      illegal move and trimmed to end on a solver move.
    - ``cp`` is the solver's eval after the line, from the solver's view (any value for a mate), or
      None when it isn't known (an imported puzzle): the goal themes are then left out.

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
        tags = cook(Puzzle("local", game, 0 if cp is None else cp))
    except (AssertionError, AttributeError, IndexError, KeyError, ValueError):
        return ()  # the tagger assumes Lichess-shaped input; anything else stays untagged
    return tuple(dict.fromkeys(t for t in tags if themes.is_known(t) and (cp is not None or t not in GOALS)))


# ---- a whole analyzed game (v0.10, FR-10.12 and FR-10.27) -----------------------------------------

ERRORS = ("inaccuracy", "mistake", "blunder")


def _solver_cp(score: Score) -> int:
    return MATE_CP if score.mate is not None and score.mate > 0 else score.value()


def move_themes(rows: Sequence[MoveRow], i: int) -> tuple[str, ...]:
    """Themes of the tactic behind a Missed or Allowed mistake (FR-10.11, 10.12).

    - **Missed:** Stockfish's best line from your position, after the opponent's move that led there.
    - **Allowed:** the opponent's best line after your move, which is the move before it.
    """
    row = rows[i]
    if row.kind == "missed":
        return best_line_themes(rows, i)
    if row.kind == "allowed":
        if not row.refutation:
            return ()
        return tag_line(row.fen_before, row.move_uci, saved_line(row.refutation), _solver_cp(row.eval_after.negate()))
    return ()


def best_line_themes(rows: Sequence[MoveRow], i: int) -> tuple[str, ...]:
    """Themes of Stockfish's best line from the position before move ``i``, solved by the side to move
    there: a Missed mistake, or a key moment saved as a puzzle (FR-11.16)."""
    row = rows[i]
    if not row.lines or not row.lines[0].pv:
        return ()
    line = saved_line(row.lines[0].pv)
    if i == 0:
        return tag_line(row.fen_before, None, line, _solver_cp(row.eval_before))
    prev = rows[i - 1]
    return tag_line(prev.fen_before, prev.move_uci, line, _solver_cp(row.eval_before))


def move_habits(rows: Sequence[MoveRow], i: int) -> tuple[str, ...]:
    """Habit tags for an inaccuracy, mistake or blunder (FR-10.27); () for any other move."""
    row = rows[i]
    if row.classification not in ERRORS:
        return ()
    try:
        before = chess.Board(row.fen_before)
        move = chess.Move.from_uci(row.move_uci)
        prev = rows[i - 1] if i > 0 else None
        previous = chess.Board(prev.fen_before) if prev else None
        previous_move = chess.Move.from_uci(prev.move_uci) if prev else None
        reply = chess.Move.from_uci(rows[i + 1].move_uci) if i + 1 < len(rows) else None
    except ValueError:
        return ()
    return habit_tags(MoveContext(before, move, previous, previous_move, reply))


def tag_game(rows: Sequence[MoveRow]) -> list[MoveRow]:
    """Every move with its themes and habits worked out from the stored analysis (no engine)."""
    return [replace(r, themes=move_themes(rows, i), habits=move_habits(rows, i)) for i, r in enumerate(rows)]
