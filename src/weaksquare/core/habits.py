"""Habit tags: the club-level mistakes, from plain attack maps (FR-10.27).

Each check looks at one of your moves with python-chess only:
- ``hungPiece``: after your move the opponent can win one of your pieces outright
- ``missedFreeCapture``: the opponent had left material you could win, and you didn't take it
- ``ignoredThreat``: the opponent's last move created a capture or fork threat, and it's still there
  after your move
- ``movedDefender``: the piece you moved was the only defender of something, which then fell

"Win" uses a short exchange count: an undefended piece is won outright; a defended one only by a
cheaper attacker, for the difference. A gain under 2 pawns (a loose pawn, an even trade) doesn't
count. The checks don't know the engine's view, so the caller applies them to your mistakes only.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

HABITS: tuple[str, ...] = ("hungPiece", "missedFreeCapture", "ignoredThreat", "movedDefender")

# FR-10.27: the puzzle drills each habit maps to (themes, and the mode that trains it best).
HABIT_DRILLS: dict[str, tuple[tuple[str, ...], str | None]] = {
    "hungPiece": (("hangingPiece", "fork"), "danger_spotting"),
    "ignoredThreat": (("hangingPiece", "fork"), "danger_spotting"),
    "missedFreeCapture": (("hangingPiece",), None),
    "movedDefender": (("capturingDefender", "deflection"), None),
}

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
MIN_GAIN = 2


def _gain(board: chess.Board, square: chess.Square) -> int:
    """What the side to move wins by taking on ``square`` (0 when it can't, or it doesn't pay)."""
    target = board.piece_at(square)
    if target is None or target.color == board.turn or target.piece_type == chess.KING:
        return 0
    takers = [m for m in board.legal_moves if m.to_square == square]
    if not takers:
        return 0
    value = VALUES[target.piece_type]
    defended = bool(board.attackers(target.color, square))
    if not defended:
        return value
    cheapest = min(VALUES[board.piece_type_at(m.from_square) or chess.PAWN] for m in takers)
    return max(0, value - cheapest)


def winnable(board: chess.Board) -> dict[chess.Square, int]:
    """The squares where the side to move wins at least ``MIN_GAIN``, with the gain."""
    out: dict[chess.Square, int] = {}
    for square, piece in board.piece_map().items():
        if piece.color != board.turn:
            g = _gain(board, square)
            if g >= MIN_GAIN:
                out[square] = g
    return out


def _fork_threats(board: chess.Board) -> set[tuple[chess.Square, chess.Square]]:
    """Moves the side to move could make next that fork two of the other side's pieces.

    Lichess's fork shape: the forking piece lands where it can't be won, and attacks at least two
    non-pawn pieces that are either worth more than it or undefended.
    """
    out: set[tuple[chess.Square, chess.Square]] = set()
    us = board.turn
    for move in board.legal_moves:
        if board.is_capture(move):
            continue  # a capture is a capture threat, counted by winnable()
        mover = board.piece_type_at(move.from_square)
        if mover is None or mover == chess.KING:
            continue
        after = board.copy(stack=False)
        after.push(move)
        if _gain(after, move.to_square) > 0:
            continue  # the forker would just be taken
        hits = 0
        for sq in after.attacks(move.to_square):
            piece = after.piece_at(sq)
            if piece is None or piece.color == us or piece.piece_type == chess.PAWN:
                continue
            if VALUES[piece.piece_type] > VALUES[mover] or not after.attackers(piece.color, sq):
                hits += 1
        if hits >= 2:
            out.add((move.from_square, move.to_square))
    return out


def _as_opponent(board: chess.Board) -> chess.Board:
    """The same position with the other side to move (for "what could they do now")."""
    b = board.copy(stack=False)
    b.turn = not b.turn
    b.ep_square = None
    return b


@dataclass(frozen=True)
class MoveContext:
    """One of your moves in a game.

    ``before`` is the position you moved from (you to move). ``previous`` is the position before the
    opponent's last move, with that move, when there was one. ``reply`` is the opponent's next move
    in the game, when there was one.
    """

    before: chess.Board
    move: chess.Move
    previous: chess.Board | None = None
    previous_move: chess.Move | None = None
    reply: chess.Move | None = None


def hung_piece(ctx: MoveContext) -> bool:
    after = ctx.before.copy(stack=False)
    after.push(ctx.move)
    if after.is_checkmate():
        return False
    already = winnable(_as_opponent(ctx.before)) if not ctx.before.is_check() else {}
    return any(square == ctx.move.to_square or square not in already for square in winnable(after))


def missed_free_capture(ctx: MoveContext) -> bool:
    free = winnable(ctx.before)
    if not free:
        return False
    after = ctx.before.copy(stack=False)
    after.push(ctx.move)
    if after.is_checkmate():
        return False
    return ctx.move.to_square not in free


def ignored_threat(ctx: MoveContext) -> bool:
    if ctx.previous is None or ctx.previous_move is None:
        return False
    old_threats = set(winnable(ctx.previous))  # the opponent was to move there
    old_forks = _fork_threats(ctx.previous)
    them_now = _as_opponent(ctx.before)
    new_threats = set(winnable(them_now)) - old_threats
    new_forks = _fork_threats(them_now) - old_forks
    if not new_threats and not new_forks:
        return False
    after = ctx.before.copy(stack=False)
    after.push(ctx.move)
    if after.is_checkmate():
        return False
    still = set(winnable(after))
    moved_from = ctx.move.from_square
    if any(sq in still for sq in new_threats if sq != moved_from):
        return True
    return bool(new_forks & _fork_threats(after))


def moved_defender(ctx: MoveContext) -> bool:
    before = ctx.before
    us = before.turn
    piece = before.piece_at(ctx.move.from_square)
    if piece is None:
        return False
    after = before.copy(stack=False)
    after.push(ctx.move)
    if after.is_checkmate():
        return False
    now_winnable = winnable(after)
    for square in before.attacks(ctx.move.from_square):
        guarded = before.piece_at(square)
        if guarded is None or guarded.color != us or square == ctx.move.to_square:
            continue
        defenders = before.attackers(us, square)
        if defenders != chess.SquareSet([ctx.move.from_square]):
            continue  # it wasn't the only defender
        if not before.attackers(not us, square) or square not in now_winnable:
            continue
        if ctx.reply is None or ctx.reply.to_square == square:
            return True
    return False


def habit_tags(ctx: MoveContext) -> tuple[str, ...]:
    """The habit tags for one of your moves, in ``HABITS`` order."""
    if ctx.move not in ctx.before.legal_moves:
        return ()
    found = {
        "hungPiece": hung_piece(ctx),
        "missedFreeCapture": missed_free_capture(ctx),
        "ignoredThreat": ignored_threat(ctx),
        "movedDefender": moved_defender(ctx),
    }
    return tuple(h for h in HABITS if found[h])
