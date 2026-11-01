"""Everything that crosses to JavaScript (ARCHITECTURE §3 decision 8).

`web/src/api/types.ts` is generated from this module by `scripts/gen_types.py`; a contract test
fails if the two drift. Only the classes in EXPORTED are generated, in that order. Never put a
secret in a DTO (SR-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from weaksquare.core.filters import FilterSpec, RatioBucket


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class AppInfo:
    version: str
    data_dir: str
    logs_dir: str
    dev_mode: bool
    license: str
    source_url: str
    puzzle_db_export_date: str | None
    puzzle_count: int | None


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    state: Literal["running", "done", "failed", "cancelled"]
    progress: float | None
    message: str
    error_code: str | None


@dataclass(frozen=True)
class PuzzleDbStatus:
    installed: bool
    puzzle_count: int | None
    export_date: str | None
    imported_at: str | None
    rating_min: int | None
    rating_max: int | None
    import_job_id: str | None
    needs_upgrade: bool  # an older-schema puzzles.db: rebuild it locally (no download) first


@dataclass(frozen=True)
class ThemeOption:
    key: str
    name: str
    count: int


@dataclass(frozen=True)
class ThemeGroup:
    name: str
    themes: list[ThemeOption]


@dataclass(frozen=True)
class UiSettings:
    last_filters: FilterSpec | None


@dataclass(frozen=True)
class SessionInfo:
    session_id: int
    match_count: int
    queue_size: int | None


@dataclass(frozen=True)
class PuzzleView:
    """The puzzle as the board needs it. Never includes themes (FR-3.14)."""

    number: int
    puzzle_id: str
    fen: str  # before the opponent's move
    opponent_move: str  # UCI, played (animated) first
    player_color: Literal["white", "black"]
    rating: int


@dataclass(frozen=True)
class ThemeLabel:
    key: str
    name: str


@dataclass(frozen=True)
class Outcome:
    """Sent once per puzzle, when the attempt is decided; themes are revealed here."""

    win: bool
    puzzle_id: str
    rating: int
    themes: list[ThemeLabel]
    solution: list[str]  # UCI, from the player's first move
    puzzle_url: str


@dataclass(frozen=True)
class MoveFeedback:
    kind: Literal["correct", "solved", "wrong", "illegal"]
    reply: str | None  # the opponent's reply (UCI), to play on the board
    finished: bool  # the whole line has been played
    outcome: Outcome | None


@dataclass(frozen=True)
class SessionStats:
    solved: int
    failed: int
    accuracy: float | None
    played: int
    queue_size: int | None
    finished: bool
    all_time_solved: int
    all_time_failed: int


EXPORTED: list[type] = [
    ApiError,
    AppInfo,
    Job,
    PuzzleDbStatus,
    RatioBucket,
    FilterSpec,
    ThemeOption,
    ThemeGroup,
    UiSettings,
    SessionInfo,
    PuzzleView,
    ThemeLabel,
    Outcome,
    MoveFeedback,
    SessionStats,
]
