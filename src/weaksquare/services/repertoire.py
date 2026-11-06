"""Your repertoire (v0.13, FR-12.4): add an opening's lines, list the tree, remove by reachability, and choose
main moves. Moves come from the book, the engine, the explorer or you, and each is checked with python-chess
before it's stored. There's no path here for a move from an LLM."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.openings import Line, position_key
from weaksquare.core.repertoire import (
    Edge,
    NewMove,
    TreeRow,
    check_color,
    line_to_moves,
    removal,
    tree_rows,
)
from weaksquare.services.openings import OpeningsService


class Repo(Protocol):
    def edges(self, color: str) -> list[Edge]: ...

    def add_moves(self, color: str, moves: Sequence[NewMove], created_at: str) -> int: ...

    def delete(self, color: str, edges: Sequence[Edge]) -> None: ...

    def set_main(self, color: str, position_key: str, move_uci: str) -> bool: ...

    def set_order(self, color: str, position_key: str, order: Sequence[str]) -> None: ...

    def openings(self, color: str | None = None) -> list[Any]: ...

    def add_opening(
        self, color: str, name: str, eco: str, root_key: str, root_moves: Sequence[str], created_at: str
    ) -> None: ...


@dataclass(frozen=True)
class RepertoireView:
    color: str
    rows: tuple[TreeRow, ...]
    openings: tuple[Any, ...]


@dataclass(frozen=True)
class AddResult:
    added: int  # new moves stored
    kept: int  # moves you already had, left exactly as they were


def _check_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("That position isn't in your repertoire.")
    return value


class RepertoireService:
    def __init__(self, repo: Repo, openings: OpeningsService, clock: Clock) -> None:
        self._repo = repo
        self._openings = openings
        self._clock = clock

    def _now(self) -> str:
        return self._clock.now().isoformat()

    def view(self, color: object) -> RepertoireView:
        c = check_color(color)
        return RepertoireView(c, tuple(tree_rows(self._repo.edges(c), c)), tuple(self._repo.openings(c)))

    def edges(self, color: object) -> list[Edge]:
        return self._repo.edges(check_color(color))

    def _store(self, color: str, lines: Sequence[Line]) -> AddResult:
        moves: dict[tuple[str, str], NewMove] = {}
        for line in lines:
            for m in line_to_moves([(x.uci, x.source) for x in line.moves]):
                moves.setdefault((m.position_key, m.move_uci), m)
        added = self._repo.add_moves(color, list(moves.values()), self._now())
        return AddResult(added, len(moves) - added)

    def add_lines(self, color: object, family: object, indices: object) -> AddResult:
        """Add lines the service works out for itself, so a move's source can't be claimed by the caller."""
        c = check_color(color)
        if not isinstance(indices, list) or not indices:
            raise ValidationError("Choose at least one line to add.")
        lines = self._openings.lines(family).lines
        chosen: list[Line] = []
        for i in indices:
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(lines):
                raise ValidationError("That line isn't in this opening.")
            chosen.append(lines[i])
        root = self._openings.root(family)
        result = self._store(c, chosen)
        self._repo.add_opening(c, root.family, root.eco, root.final_key, root.moves, self._now())
        return result

    def removal_preview(self, color: object, key: object, move_uci: object) -> list[Edge]:
        c = check_color(color)
        edges = self._repo.edges(c)
        k = _check_key(key)
        if not any(e.position_key == k and e.move_uci == move_uci for e in edges):
            raise NotFoundError("That move isn't in your repertoire.")
        return removal(edges, k, str(move_uci))

    def remove(self, color: object, key: object, move_uci: object) -> int:
        """Remove a move and whatever only it could reach (FR-12.4). Returns how many moves went."""
        gone = self.removal_preview(color, key, move_uci)
        self._repo.delete(check_color(color), gone)
        return len(gone)

    def set_main(self, color: object, key: object, move_uci: object) -> None:
        if not isinstance(move_uci, str) or not self._repo.set_main(check_color(color), _check_key(key), move_uci):
            raise NotFoundError("That move isn't in your repertoire.")

    def move(self, color: object, key: object, move_uci: object, direction: object) -> None:
        """Reorder a move among its position's moves (FR-12.4)."""
        c = check_color(color)
        k = _check_key(key)
        if direction not in ("up", "down"):
            raise ValidationError("Move it up or down.")
        here = [e.move_uci for e in self._repo.edges(c) if e.position_key == k]
        if move_uci not in here:
            raise NotFoundError("That move isn't in your repertoire.")
        i = here.index(str(move_uci))
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(here):
            here[i], here[j] = here[j], here[i]
            self._repo.set_order(c, k, here)


__all__ = ["AddResult", "RepertoireService", "RepertoireView", "position_key"]
