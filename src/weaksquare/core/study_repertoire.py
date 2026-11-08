"""Add to my repertoire from a study (v0.14, FR-13.11). Pure: a checked chapter tree in, repertoire moves out.

- **Which moves:** each chapter's main line by default; with side lines, every move in the tree. Side lines mix the
  other side's alternatives with the author's ideas for your side, so they can add several moves for you at one
  position (Adam, v0.14 planning).
- **Conflicts:** at a position where it's your move, a study move you don't have, when you already have a move there,
  is a conflict. You choose: **mine** (the default) keeps your move and skips the study's, and everything only it led
  to; **study** adds the study's move as your main one and keeps yours as a sideline. Nothing of yours is deleted.
- **Reachability:** a repertoire starts from the first move, and Practice walks from there. Only moves reachable from
  the start, through your moves and the ones being added, are stored. A chapter from a set position joins only if your
  repertoire already reaches that position; the rest are counted as skipped, never stored unreachable (a later removal
  would delete them anyway, ARCHITECTURE §7 v0.13).
- **Positions are matched by key** (`core.openings.position_key`), so a transposition reuses its position.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import chess

from weaksquare.core.openings import STARTING_KEY, position_key
from weaksquare.core.repertoire import Edge, NewMove, after, by_position, is_your_turn, reachable
from weaksquare.core.study_pgn import Node

SOURCE = "study"
Choice = Literal["mine", "study"]


def study_moves(root: Node, start_fen: str, include_side_lines: bool) -> list[NewMove]:
    """The chapter's moves as repertoire moves, in tree order (main line first). Every move was checked when the study
    was read (`core.study_pgn.node_from_json`); python-chess checks it again here."""
    out: list[NewMove] = []
    seen: set[tuple[str, str]] = set()

    def walk(node: Node, board: chess.Board) -> None:
        kids = node.children if include_side_lines else node.children[:1]
        for child in kids:
            move = chess.Move.from_uci(child.uci or "")
            if move not in board.legal_moves:
                raise ValueError("illegal move in a checked tree")
            key = position_key(board)
            if (key, move.uci()) not in seen:
                seen.add((key, move.uci()))
                out.append(NewMove(key, move.uci(), board.san(move), SOURCE))
            nxt = board.copy(stack=False)
            nxt.push(move)
            walk(child, nxt)

    walk(root, chess.Board(start_fen))
    return out


@dataclass(frozen=True)
class Conflict:
    position_key: str
    yours: list[str]  # SAN of the moves you have there
    study: list[str]  # SAN of the study's moves there that you don't have
    path: list[str] = field(default_factory=list)  # SAN from the start, to say where it is


@dataclass(frozen=True)
class AddPlan:
    """What adding would do, before anything is saved."""

    new: list[NewMove]  # moves you don't have yet, reachable once added (conflicts resolved as "mine")
    already: int  # study moves you already have
    unreachable: int  # study moves that can't join a repertoire starting from the first move
    conflicts: list[Conflict]


def plan_add(existing: Sequence[Edge], candidates: Sequence[NewMove], color: str) -> AddPlan:
    """The preview: conflicts found, and what would be added if every conflict kept your move."""
    have = {(e.position_key, e.move_uci) for e in existing}
    yours_at = by_position(e for e in existing if is_your_turn(e.position_key, color))
    fresh = [m for m in candidates if (m.position_key, m.move_uci) not in have]
    found: dict[str, list[str]] = {}
    for m in fresh:
        if is_your_turn(m.position_key, color) and m.position_key in yours_at:
            found.setdefault(m.position_key, []).append(m.san)
    to_add, _ = resolve(existing, candidates, color, {})
    # Unreachable: not added even if every conflict took the study's move.
    best, _ = resolve(existing, candidates, color, dict.fromkeys(found, "study"))
    reachable_at_best = {(m.position_key, m.move_uci) for m in best}
    paths = _paths(list(existing) + [_edge(m) for m in candidates])
    return AddPlan(
        new=to_add,
        already=len(candidates) - len(fresh),
        unreachable=sum(1 for m in fresh if (m.position_key, m.move_uci) not in reachable_at_best),
        conflicts=[Conflict(k, [e.san for e in yours_at[k]], study, paths.get(k, [])) for k, study in found.items()],
    )


def resolve(
    existing: Sequence[Edge], candidates: Sequence[NewMove], color: str, choices: Mapping[str, Choice]
) -> tuple[list[NewMove], list[tuple[str, str]]]:
    """The moves to store and the (position, move) pairs to make main, given your choice at each conflict. A conflict
    with no choice keeps your move."""
    have = {(e.position_key, e.move_uci) for e in existing}
    yours_at = {e.position_key for e in existing if is_your_turn(e.position_key, color)}
    kept: list[NewMove] = []
    mains: list[tuple[str, str]] = []
    made_main: set[str] = set()
    for m in candidates:
        if (m.position_key, m.move_uci) in have:
            continue
        if is_your_turn(m.position_key, color) and m.position_key in yours_at:
            if choices.get(m.position_key, "mine") != "study":
                continue
            if m.position_key not in made_main:
                made_main.add(m.position_key)
                mains.append((m.position_key, m.move_uci))
        kept.append(m)
    # Only what the start can reach, through your moves and the kept ones.
    ok = reachable(list(existing) + [_edge(m) for m in kept], (STARTING_KEY,))
    to_add = [m for m in kept if (m.position_key, m.move_uci) in ok]
    reached = {(m.position_key, m.move_uci) for m in to_add}
    return to_add, [mm for mm in mains if mm in reached]


def _edge(m: NewMove) -> Edge:
    return Edge(m.position_key, m.move_uci, m.san, m.source)


def _paths(edges: Iterable[Edge]) -> dict[str, list[str]]:
    """The shortest SAN path from the start to each position, to show where a conflict is."""
    graph = by_position(edges)
    out: dict[str, list[str]] = {STARTING_KEY: []}
    queue = [STARTING_KEY]
    while queue:
        key = queue.pop(0)
        for e in graph.get(key, []):
            nxt = after(e.position_key, e.move_uci)
            if nxt not in out:
                out[nxt] = [*out[key], e.san]
                queue.append(nxt)
    return out
