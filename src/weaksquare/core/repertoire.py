"""Your repertoire (v0.13, FR-12.4). Pure: a graph of moves between positions, one per color.

Moves are edges keyed by position, not a strict tree, so two move orders reaching one position share it and
everything stored after it. That's why removal works by **reachability**: taking a move away deletes only
what can no longer be reached from the start. A position another line still reaches stays.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import chess

from weaksquare.core.errors import ValidationError
from weaksquare.core.openings import STARTING_KEY, board_of, position_key

COLORS = ("white", "black")
SOURCES = ("book", "engine", "explorer", "you")  # plus "study" from v0.14 (FR-13.11)


def check_color(color: object) -> str:
    if color not in COLORS:
        raise ValidationError("A repertoire is for White or Black.")
    return str(color)


def side_to_move(key: str) -> str:
    return "white" if key.split()[1] == "w" else "black"


def is_your_turn(key: str, color: str) -> bool:
    return side_to_move(key) == color


def after(key: str, uci: str) -> str:
    """The position a stored move leads to."""
    board = board_of(key)
    board.push(chess.Move.from_uci(uci))
    return position_key(board)


@dataclass(frozen=True)
class Edge:
    position_key: str
    move_uci: str
    san: str
    source: str
    is_main: bool = False
    sort_order: int = 0
    id: int = 0


@dataclass(frozen=True)
class NewMove:
    position_key: str
    move_uci: str
    san: str
    source: str


def line_to_moves(sans_or_ucis: Sequence[tuple[str, str]], source_of: Mapping[int, str] | None = None) -> list[NewMove]:
    """(uci, source) pairs from the start of the game -> checked moves. Anything illegal raises: a move only
    enters a repertoire after python-chess has accepted it (FR-12.8)."""
    board = chess.Board()
    out: list[NewMove] = []
    for uci, source in sans_or_ucis:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as e:
            raise ValidationError(f"{uci} isn't a move.") from e
        if move not in board.legal_moves:
            raise ValidationError(f"{uci} isn't legal here.")
        out.append(NewMove(position_key(board), uci, board.san(move), source))
        board.push(move)
    return out


def by_position(edges: Iterable[Edge]) -> dict[str, list[Edge]]:
    out: dict[str, list[Edge]] = {}
    for e in edges:
        out.setdefault(e.position_key, []).append(e)
    for moves in out.values():
        moves.sort(key=lambda e: (not e.is_main, e.sort_order, e.move_uci))
    return out


def reachable(edges: Iterable[Edge], roots: Iterable[str] = (STARTING_KEY,)) -> set[tuple[str, str]]:
    """Every (position, move) that can be reached from the roots."""
    graph = by_position(edges)
    seen_positions: set[str] = set()
    found: set[tuple[str, str]] = set()
    stack = list(roots)
    while stack:
        key = stack.pop()
        if key in seen_positions:
            continue
        seen_positions.add(key)
        for e in graph.get(key, []):
            found.add((e.position_key, e.move_uci))
            stack.append(after(e.position_key, e.move_uci))
    return found


def removal(edges: Sequence[Edge], position: str, move_uci: str) -> list[Edge]:
    """What removing one move deletes: that move, plus anything only it could reach."""
    remaining = [e for e in edges if not (e.position_key == position and e.move_uci == move_uci)]
    keep = reachable(remaining)
    return [e for e in edges if (e.position_key, e.move_uci) not in keep]


@dataclass(frozen=True)
class TreeRow:
    """One move in the tree as the screen lists it: its depth from the root, and whether it's a repeat."""

    depth: int
    edge: Edge
    yours: bool
    transposes: bool  # this position was already listed through another move order


def tree_rows(edges: Iterable[Edge], color: str, root: str = STARTING_KEY) -> list[TreeRow]:
    """The graph unfolded depth-first. A position reached again is listed once, and marked where it recurs,
    so a transposition can't make the list repeat or loop."""
    graph = by_position(edges)
    rows: list[TreeRow] = []
    expanded: set[str] = set()

    def walk(key: str, depth: int) -> None:
        expanded.add(key)
        for e in graph.get(key, []):
            next_key = after(e.position_key, e.move_uci)
            seen = next_key in expanded
            rows.append(TreeRow(depth, e, is_your_turn(key, color), seen))
            if not seen:
                walk(next_key, depth + 1)

    walk(root, 0)
    return rows


def your_positions(edges: Iterable[Edge], color: str) -> dict[str, list[Edge]]:
    """Your decision points (FR-12.10): reachable positions where it's your move and you have an answer."""
    all_edges = list(edges)
    keep = reachable(all_edges)
    out: dict[str, list[Edge]] = {}
    for key, moves in by_position(e for e in all_edges if (e.position_key, e.move_uci) in keep).items():
        if is_your_turn(key, color):
            out[key] = moves
    return out
