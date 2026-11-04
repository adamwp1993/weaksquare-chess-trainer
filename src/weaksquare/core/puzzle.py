"""Puzzle identity and data (ARCHITECTURE §3 decision 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from weaksquare.core.errors import ValidationError

Color = Literal["white", "black"]
PuzzleSourceName = Literal["lichess", "my"]  # my: your own puzzles (custom_puzzles), v0.8
SOURCES: tuple[str, ...] = ("lichess", "my")
# v0.8: a custom puzzle has no opponent move first: its moves[0] is this, and the FEN is the position you solve.
NO_PREMOVE = ""


@dataclass(frozen=True, order=True)
class PuzzleRef:
    """A puzzle anywhere in the app: `lichess:00008`. Never a bare ID."""

    source: str
    id: str

    def __str__(self) -> str:
        return f"{self.source}:{self.id}"

    @classmethod
    def parse(cls, text: str) -> PuzzleRef:
        source, sep, pid = text.partition(":")
        if not sep or source not in SOURCES or not pid or len(pid) > 32 or not pid.isalnum():
            raise ValidationError(f"not a puzzle reference: {text[:40]!r}")
        return cls(source, pid)


@dataclass(frozen=True)
class Puzzle:
    ref: PuzzleRef
    fen: str  # before the opponent's move (§4.2)
    moves: tuple[str, ...]  # UCI; moves[0] is the opponent's
    rating: int
    themes: tuple[str, ...]
    game_url: str
    opening_tags: tuple[str, ...]
    tolerance: bool = False  # v0.8: solved with the engine tolerance (FR-10.43), not only the stored line

    @property
    def has_premove(self) -> bool:
        return bool(self.moves) and self.moves[0] != NO_PREMOVE

    @property
    def length(self) -> int:
        return len(self.moves) // 2


@dataclass(frozen=True)
class NewCustomPuzzle:
    """A puzzle of your own for `custom_puzzles` (v0.8): saved from Game Review or imported from a file."""

    fen: str  # the position you solve (you are to move)
    solution: tuple[str, ...]  # UCI, ending on your move
    player_color: str
    origin: str  # manual / import / coach (v0.10)
    strict: bool
    game_id: int | None = None
    ply: int | None = None
    set_label: str | None = None
    name: str | None = None
    kind: str | None = None
    severity: str | None = None
    cp_loss: int | None = None
    phase: str | None = None
    time_class: str | None = None
    game_date: str | None = None
    themes: tuple[str, ...] = ()  # v0.10: lichess-puzzler themes (FR-10.12, 10.43)
    solve_as: str = "you"  # v0.10: 'opponent' for an Allowed puzzle from your games (FR-10.42)

    @property
    def length(self) -> int:
        return (len(self.solution) + 1) // 2  # your moves
