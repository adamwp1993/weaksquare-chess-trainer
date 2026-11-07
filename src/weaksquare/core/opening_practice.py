"""Drilling a repertoire (v0.13, FR-12.9, 12.10, 12.14). Pure: the schedule per position, choosing what comes up, and
proposing a repertoire.

**The schedule** uses FR-4.6's boxes, replayed from the attempts log. The difference from puzzles: a repertoire
position is scheduled from the first time you get it right, because here there's no earlier miss that puts it in
a box. A wrong move or any help puts it back in box 1, even after it graduated.

**The proposal** (FR-12.14) takes moves only from the explorer, the book, the engine or what you've stored. All of them
arrive here already checked, and each is checked again against the position.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import chess

from weaksquare.core.engine import EngineLine
from weaksquare.core.openings import (
    SOURCE_BOOK,
    SOURCE_ENGINE,
    SOURCE_EXPLORER,
    SOURCE_YOU,
    STARTING_KEY,
    position_key,
)
from weaksquare.core.repertoire import Edge, after, by_position, is_your_turn, your_positions
from weaksquare.core.srs import Card, is_due

CORRECT, WRONG, HELPED = "correct", "wrong", "helped"
MAIN_WEIGHT = 3  # FR-12.9: a main reply comes up this much more often, without the explorer
DEFAULT_NEW = 5  # FR-12.10: New lines introduces unseen positions a few at a time


@dataclass(frozen=True)
class Review:
    at: datetime
    outcome: str


def schedule_position(
    reviews: Iterable[Review], intervals: Sequence[int], local_date: Callable[[datetime], date]
) -> Card | None:
    """Replay one position's attempts (oldest first). None when you've never tried it."""
    box: int | None = None
    due: date | None = None
    graduated = False
    last = len(intervals)
    for r in reviews:
        day = local_date(r.at)
        if r.outcome != CORRECT or box is None:
            box, graduated = 1, False
            due = day + timedelta(days=intervals[0])
        elif not graduated:
            box = min(box, last)
            if box == last:
                graduated, due = True, None
            else:
                box += 1
                due = day + timedelta(days=intervals[box - 1])
    if box is None:
        return None
    return Card(box, due, graduated)


def parents(edges: Iterable[Edge]) -> dict[str, list[Edge]]:
    """The moves that lead to each position."""
    out: dict[str, list[Edge]] = {}
    for e in edges:
        out.setdefault(after(e.position_key, e.move_uci), []).append(e)
    return out


def path_to(edges: Sequence[Edge], target: str, root: str = STARTING_KEY) -> list[Edge] | None:
    """A shortest way from the root to a position, or None when it can't be reached."""
    graph = by_position(edges)
    frontier: list[tuple[str, list[Edge]]] = [(root, [])]
    seen = {root}
    while frontier:
        next_frontier: list[tuple[str, list[Edge]]] = []
        for key, path in frontier:
            if key == target:
                return path
            for e in graph.get(key, []):
                to = after(e.position_key, e.move_uci)
                if to not in seen:
                    seen.add(to)
                    next_frontier.append((to, [*path, e]))
        frontier = next_frontier
    return None


def subtree_positions(edges: Sequence[Edge], root: str) -> set[str]:
    """Every position at or after `root` (FR-12.10: a session limited to one opening or branch)."""
    graph = by_position(edges)
    seen: set[str] = set()
    stack = [root]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        for e in graph.get(key, []):
            stack.append(after(e.position_key, e.move_uci))
    return seen


def pick_reply(moves: Sequence[Edge], rng: random.Random, popularity: Mapping[str, int] | None = None) -> Edge:
    """FR-12.9: an opponent's reply, weighted by explorer popularity when there is any, otherwise toward main lines."""
    pop = popularity or {}
    if any(pop.get(m.move_uci, 0) > 0 for m in moves):
        weights = [max(pop.get(m.move_uci, 0), 1) for m in moves]
    else:
        weights = [MAIN_WEIGHT if m.is_main else 1 for m in moves]
    return rng.choices(list(moves), weights=weights, k=1)[0]


@dataclass(frozen=True)
class Target:
    position_key: str
    reason: str  # 'due' or 'new'


def due_and_new(
    edges: Sequence[Edge],
    color: str,
    cards: Mapping[str, Card | None],
    today: date,
    within: set[str] | None = None,
    new_limit: int = DEFAULT_NEW,
) -> list[Target]:
    """FR-12.10: what's due first, most overdue first, then a few positions you haven't seen, nearest the root first."""
    mine = your_positions(edges, color)
    keys = [k for k in mine if within is None or k in within]
    due = sorted(
        (k for k in keys if (c := cards.get(k)) is not None and is_due(c, today)),
        key=lambda k: (cards[k].due, cards[k].box, k),  # type: ignore[union-attr]
    )
    unseen = [k for k in keys if cards.get(k) is None]
    distance = {k: len(path_to(edges, k) or []) for k in unseen}
    new = sorted(unseen, key=lambda k: (distance[k], k))[: max(0, new_limit)]
    return [Target(k, "due") for k in due] + [Target(k, "new") for k in new]


# ---- Build my repertoire (FR-12.14) ------------------------------------------------------------------------------------

FLAG_ENGINE = "engine_answer"  # your answer fell back to the engine
FLAG_FEW_GAMES = "few_games"  # too few games to trust what's popular here
FLAG_BAD_EVAL = "bad_eval"  # you're clearly worse after your answer
BAD_EVAL_CP = -150
FEW_GAMES = 50
ANSWER_TOLERANCE_CP = 50  # FR-12.14: the most-played move, if it's this close to the engine's best
MATE_CP = 10_000


@dataclass(frozen=True)
class BuildLimits:
    max_moves: int = 12
    min_share: float = 0.05
    max_replies: int = 3
    max_positions: int = 60


@dataclass(frozen=True)
class ProposedMove:
    position_key: str
    move_uci: str
    san: str
    source: str
    yours: bool
    depth: int
    share: float | None  # of the games at this position, for a reply
    already_yours: bool  # you've stored this move
    flags: tuple[str, ...]


@dataclass(frozen=True)
class Popular:
    uci: str
    games: int


@dataclass(frozen=True)
class Sources:
    """Where a proposal's moves come from. Each is I/O, given to `propose` by the service."""

    popular: Callable[[chess.Board], tuple[int, Sequence[Popular]] | None]  # (total games, moves), or None
    book: Callable[[chess.Board], Sequence[str]]  # ranked book moves
    engine: Callable[[chess.Board], Sequence[EngineLine]]
    stored: Mapping[str, Sequence[Edge]]  # what you have, by position


def side_cp(line: EngineLine, color: str) -> int:
    """A stored eval from your side, with a mate as a large number."""
    sign = 1 if color == "white" else -1
    if line.mate is not None:
        return (MATE_CP if line.mate > 0 else -MATE_CP) * sign
    return (line.cp or 0) * sign


def _legal(board: chess.Board, uci: str) -> chess.Move | None:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def _your_answer(board: chess.Board, color: str, src: Sources) -> tuple[str, str, bool, tuple[str, ...]] | None:
    """FR-12.14's order: one you already have, the book, the most-played if close to the engine's best, the engine's best.
    Returns (uci, source, already yours, flags)."""
    key = position_key(board)
    stored = src.stored.get(key)
    if stored:
        return stored[0].move_uci, stored[0].source, True, ()
    for uci in src.book(board):
        if _legal(board, uci) is not None:
            return uci, SOURCE_BOOK, False, ()
    lines = src.engine(board)
    best = lines[0] if lines and lines[0].pv else None
    popular = src.popular(board)
    if popular is not None and popular[1] and best is not None:
        top = popular[1][0]
        move = _legal(board, top.uci)
        if move is not None:
            if top.uci == best.pv[0]:
                return top.uci, SOURCE_EXPLORER, False, ()
            after_board = board.copy()
            after_board.push(move)
            reply = src.engine(after_board)
            if reply and side_cp(best, color) - side_cp(reply[0], color) <= ANSWER_TOLERANCE_CP:
                return top.uci, SOURCE_EXPLORER, False, ()
    if best is not None and _legal(board, best.pv[0]) is not None:
        return best.pv[0], SOURCE_ENGINE, False, (FLAG_ENGINE,)
    return None


def propose(start: Sequence[str], color: str, limits: BuildLimits, src: Sources) -> list[ProposedMove]:
    """A tree from the end of `start` (UCI from the start of the game), breadth first, so a position limit keeps the
    moves nearest the opening. The moves of `start` itself are included, so the tree is connected."""
    board = chess.Board()
    out: list[ProposedMove] = []
    for uci in start:
        move = chess.Move.from_uci(uci)
        key = position_key(board)
        known = [e for e in src.stored.get(key, ()) if e.move_uci == uci]
        out.append(
            ProposedMove(
                key, uci, board.san(move), known[0].source if known else SOURCE_BOOK, is_your_turn(key, color), len(out),
                None, bool(known), (),
            )
        )  # fmt: skip
        board.push(move)
    max_plies = limits.max_moves * 2
    frontier = [(board.copy(), len(start))]
    seen = {position_key(board)}
    positions = 0
    while frontier and positions < limits.max_positions:
        next_frontier: list[tuple[chess.Board, int]] = []
        for b, ply in frontier:
            if ply >= max_plies or b.is_game_over(claim_draw=False) or positions >= limits.max_positions:
                continue
            positions += 1
            key = position_key(b)
            chosen: list[tuple[str, str, bool, float | None, tuple[str, ...]]] = []
            if is_your_turn(key, color):
                answer = _your_answer(b, color, src)
                if answer is None:
                    continue
                uci, source, have, flags = answer
                chosen.append((uci, source, have, None, flags))
            else:
                popular = src.popular(b)
                if popular is not None and popular[1]:
                    total, moves = popular
                    few = (FLAG_FEW_GAMES,) if total < FEW_GAMES else ()
                    for m in moves[: limits.max_replies]:
                        portion = m.games / total if total else 0.0
                        if portion >= limits.min_share:
                            chosen.append((m.uci, SOURCE_EXPLORER, False, portion, few))
                if not chosen:
                    chosen.extend((u, SOURCE_BOOK, False, None, ()) for u in list(src.book(b))[: limits.max_replies])
                for e in src.stored.get(key, ()):
                    if all(c[0] != e.move_uci for c in chosen):
                        chosen.append((e.move_uci, e.source, True, None, ()))
            for uci, source, have, share, flags in chosen:
                legal = _legal(b, uci)
                if legal is None:
                    continue
                nb = b.copy()
                nb.push(legal)
                final_flags = flags
                if is_your_turn(key, color):
                    lines = src.engine(nb)
                    if lines and side_cp(lines[0], color) <= BAD_EVAL_CP:
                        final_flags = (*flags, FLAG_BAD_EVAL)
                stored_here = [e for e in src.stored.get(key, ()) if e.move_uci == uci]
                out.append(
                    ProposedMove(
                        key, uci, b.san(legal), stored_here[0].source if stored_here else source,
                        is_your_turn(key, color), ply, share, have or bool(stored_here), final_flags,
                    )
                )  # fmt: skip
                next_key = position_key(nb)
                if next_key not in seen:
                    seen.add(next_key)
                    next_frontier.append((nb, ply + 1))
        frontier = next_frontier
    return out


# ---- "What if they play…?" (FR-12.8) ------------------------------------------------------------------------------------


def parse_their_move(board: chess.Board, text: object) -> chess.Move | None:
    """A move as SAN or UCI, checked with python-chess before it's near the engine or the repertoire."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    try:
        move = chess.Move.from_uci(raw)
        if move in board.legal_moves:
            return move
    except ValueError:
        pass
    try:
        return board.parse_san(raw)
    except ValueError:
        return None


def path_sources(
    moves: Sequence[str],
    is_book: Callable[[str, str], bool],
    continued: Callable[[chess.Board, str], str | None] = lambda _b, _u: None,
) -> list[tuple[str, str]]:
    """(uci, source) for the moves leading to a deviation, so what it hangs from is connected to the root. `continued`
    says where a move past the book came from, the explorer or the engine. Anything else was your own choice."""
    board = chess.Board()
    out: list[tuple[str, str]] = []
    for uci in moves:
        key = position_key(board)
        source = SOURCE_BOOK if is_book(key, uci) else continued(board, uci) or SOURCE_YOU
        out.append((uci, source))
        board.push(chess.Move.from_uci(uci))
    return out
