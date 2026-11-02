"""Everything that crosses to JavaScript (ARCHITECTURE §3 decision 8).

`web/src/api/types.ts` is generated from this module by `scripts/gen_types.py`; a contract test
fails if the two drift. Only the classes in EXPORTED are generated, in that order. Never put a
secret in a DTO (SR-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.core.move_sounds import MoveSound


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
class SoundSettings:
    on: bool
    volume: int  # 0–100
    set: Literal["sfx", "piano", "nes", "futuristic"]


@dataclass(frozen=True)
class UiSettings:
    last_filters: FilterSpec | None
    coordinates: bool  # letters and numbers around the board
    color_scheme: Literal["light", "dark", "auto"]  # FR-1.12; "auto" is Match system
    sounds: SoundSettings  # FR-1.13
    auto_check: bool  # FR-2.5: check for a newer puzzle database once a day


@dataclass(frozen=True)
class OpeningOption:
    tag: str  # the Lichess OpeningTags value, e.g. Sicilian_Defense_Najdorf_Variation
    name: str  # for display: "Najdorf Variation" under its family "Sicilian Defense"
    count: int


@dataclass(frozen=True)
class OpeningFamily:
    family: OpeningOption
    variations: list[OpeningOption]


@dataclass(frozen=True)
class BucketCounts:
    """A ratio mix's live counts (FR-3.10), from one scan: all groups together, and each group."""

    total: int
    buckets: list[int]


@dataclass(frozen=True)
class Preset:
    name: str
    spec: FilterSpec | None  # None when this version can't use it; `error` says why
    error: str | None
    updated_at: str


@dataclass(frozen=True)
class SessionInfo:
    session_id: int
    match_count: int
    queue_size: int | None
    empty_buckets: list[int]  # ratio groups with no matching puzzles, left out of this session


@dataclass(frozen=True)
class PuzzleView:
    """The puzzle as the board needs it. Never includes themes (FR-3.14)."""

    number: int
    puzzle_id: str
    fen: str  # before the opponent's move
    opponent_move: str  # UCI, played (animated) first
    player_color: Literal["white", "black"]
    rating: int
    opponent_sound: MoveSound  # FR-1.13
    already_played: bool  # Lichess has seen this puzzle from you: rating unaffected (badge)


@dataclass(frozen=True)
class ThemeLabel:
    key: str
    name: str


RatingStatus = Literal["syncing", "offline", "unrated", "already_played", "not_rated", "done"]


@dataclass(frozen=True)
class AttemptRating:
    """FR-6.11b: an attempt's Lichess rating change, or why there isn't one. `diff` only with "done"."""

    attempt_id: int
    status: RatingStatus
    diff: int | None


@dataclass(frozen=True)
class Outcome:
    """Sent once per puzzle, when the attempt is decided; themes are revealed here."""

    win: bool
    puzzle_id: str
    rating: int
    themes: list[ThemeLabel]
    solution: list[str]  # UCI, from the player's first move
    puzzle_url: str
    attempt_id: int
    lichess: AttemptRating | None  # None when the attempt isn't synced (not a Lichess puzzle)


@dataclass(frozen=True)
class MoveFeedback:
    kind: Literal["correct", "solved", "wrong", "illegal"]
    reply: str | None  # the opponent's reply (UCI), to play on the board
    finished: bool  # the whole line has been played
    outcome: Outcome | None
    move_sound: MoveSound | None  # FR-1.13: your move…
    reply_sound: MoveSound | None  # …and the reply


@dataclass(frozen=True)
class HelpResponse:
    """Hint or Show answer (§7.2). `outcome` is set when the help decided the attempt (a loss)."""

    kind: Literal["hint", "answer"]
    hint_square: str | None  # Hint: the piece that moves next
    answer_fen: str | None  # Show answer: where the answer starts…
    answer_moves: list[str]  # …and the moves from there (UCI, both sides)
    outcome: Outcome | None
    answer_sounds: list[MoveSound]  # one per answer move


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
    rating_change: int | None  # FR-6.11c: summed only from changes Lichess returned


@dataclass(frozen=True)
class StatRow:
    key: str
    label: str
    attempts: int
    solved: int
    accuracy: float | None
    first_right: int  # attempts where the first move was right
    line_wrong_rate: float | None  # of those, the share where the line then went wrong (FR-9.2)


@dataclass(frozen=True)
class StatsReport:
    overall: StatRow
    by_theme: list[StatRow]
    by_length: list[StatRow]
    by_rating: list[StatRow]
    missing: int  # attempts on puzzles no longer in the database


@dataclass(frozen=True)
class UpdateOffer:
    """FR-2.5: a newer Lichess puzzle export is available."""

    export_date: str | None
    current_export_date: str | None
    size: int | None  # bytes to download
    approx_count: int | None  # from the database.lichess.org page, which can lag the file
    approx_new: int | None


@dataclass(frozen=True)
class AccountStatus:
    """Your Lichess account (FR-1.1, 1.6, 6.11a). Never a token (SR-1). `rating` only when signed in,
    and only as Lichess reported it."""

    state: Literal["signed_out", "checking", "signed_in", "offline", "expired"]
    username: str | None
    rating: int | None
    provisional: bool


@dataclass(frozen=True)
class SyncStatus:
    """The sync queue (FR-1.7, 6.16): `pending` solves waiting; `history_count` puzzles known from
    your Lichess history (FR-6.17)."""

    state: Literal["idle", "syncing", "offline", "waiting", "signed_out"]
    pending: int
    history_count: int


@dataclass(frozen=True)
class SyncEvent:
    """Pushed as the `sync` event whenever the queue or an attempt's rating info changes."""

    status: SyncStatus
    attempts: list[AttemptRating]


@dataclass(frozen=True)
class RatingPoint:
    at: str  # ISO time of the attempt that carried the new rating
    rating: int
    session_id: int | None


@dataclass(frozen=True)
class SessionChange:
    session_id: int
    started_at: str
    change: int
    solves: int


@dataclass(frozen=True)
class RatingHistory:
    """FR-9.4: your Lichess puzzle rating over time (from sync responses), and the change per session."""

    points: list[RatingPoint]
    sessions: list[SessionChange]


EXPORTED: list[type] = [
    ApiError,
    AppInfo,
    Job,
    PuzzleDbStatus,
    RatioBucket,
    FilterSpec,
    ThemeOption,
    ThemeGroup,
    OpeningOption,
    OpeningFamily,
    BucketCounts,
    Preset,
    SoundSettings,
    UiSettings,
    SessionInfo,
    PuzzleView,
    ThemeLabel,
    AttemptRating,
    Outcome,
    MoveFeedback,
    HelpResponse,
    SessionStats,
    StatRow,
    StatsReport,
    UpdateOffer,
    AccountStatus,
    SyncStatus,
    SyncEvent,
    RatingPoint,
    SessionChange,
    RatingHistory,
]
