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
