"""Puzzle identity and data (ARCHITECTURE §3 decision 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from weaksquare.core.errors import ValidationError

Color = Literal["white", "black"]
PuzzleSourceName = Literal["lichess"]  # "my" (custom puzzles from your games) arrives in v0.8
SOURCES: tuple[str, ...] = ("lichess",)


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

    @property
    def length(self) -> int:
        return len(self.moves) // 2


@dataclass(frozen=True)
class NewCustomPuzzle:
    """A puzzle of your own for `custom_puzzles` (v0.8): saved from Game Review or imported from a file."""

    fen: str  # the position you solve (you are to move)
    solution: tuple[str, ...]  # UCI, ending on your move
    player_color: str
    origin: str  # manual / import
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

    @property
    def length(self) -> int:
        return (len(self.solution) + 1) // 2  # your moves
