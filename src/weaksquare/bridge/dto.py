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

# The Modes control (§6), v0.5 + v0.6.
TrainingMode = Literal["standard", "commit_line", "name_idea", "danger_spotting", "spaced_repetition"]
ReasonKey = Literal["didntLook", "missedResource", "miscalculated", "unknownPattern", "rushed", "misclick"]


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
    mode: TrainingMode  # v0.5: the Modes control (§6)
    show_length: bool  # Commit the line: Show move count (FR-4.2)
    ladder_threshold: int  # FR-4.5, percent
    ladder_window: int  # FR-4.5, attempts
    srs_intervals: list[int]  # FR-4.6, days per box
    filters_collapsed: bool  # FR-1.14
    time_offset_days: int | None  # FR-4.6 fast-forward: --dev runs only (None in the real app)
    reasons_ask: Literal["always", "off"]  # FR-5.8: ask why you missed a puzzle
    rushed_s: int  # FR-5.9: a deciding move faster than this suggests Rushed


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
    mode: TrainingMode  # v0.5 (§6)


@dataclass(frozen=True)
class PuzzleView:
    """The puzzle as the board needs it. Never includes themes (FR-3.14)."""

    number: int
    puzzle_id: str
    fen: str  # before the opponent's move (Danger spotting: the position you judge the candidate in)
    opponent_move: str  # UCI, played (animated) first; empty in Danger spotting
    player_color: Literal["white", "black"]  # Danger spotting: the side about to move
    rating: int
    opponent_sound: MoveSound | None  # FR-1.13; None in Danger spotting
    already_played: bool  # Lichess has seen this puzzle from you: rating unaffected (badge)
    mode: TrainingMode
    solution_plies: int | None  # Commit the line with Show move count only: moves to enter, both sides
    max_plies: int | None  # Commit the line: the longest line Submit accepts
    candidate: str | None  # Danger spotting: the highlighted move (UCI); never says whether it's the blunder


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
class LadderInfo:
    """Depth ladder (FR-4.5): the level for a theme set, and its rolling window."""

    level: int  # puzzle length: 2, 3 or 4 (4 = 4 or more)
    label: str  # "Short", "Long", "Very long"
    step: int  # 1-based position on the ladder…
    steps: int  # …out of this many
    played: int  # attempts at this level in the window
    wins: int
    window: int
    threshold: int  # percent
    top: bool


@dataclass(frozen=True)
class LadderPreview:
    """For the mixer while Order is Depth ladder: the level a session would start at."""

    ladder: LadderInfo
    match_count: int  # puzzles at that level


@dataclass(frozen=True)
class SrsStatus:
    """Spaced repetition (FR-4.6), for the mixer."""

    due: int
    next_due: str | None  # ISO date of the next review day after today
    scheduled: int  # puzzles in a box, not graduated


@dataclass(frozen=True)
class PlyGrade:
    played: str | None  # your move (UCI); None where your line stopped short
    expected: str  # the solution's move
    player: bool  # your move, or a predicted reply
    correct: bool


@dataclass(frozen=True)
class CommitFeedback:
    """Commit the line (FR-4.2): your submitted line, graded."""

    grades: list[PlyGrade]
    extra: list[str]  # your moves after the end of the solution: ignored
    replies_correct: int
    replies_total: int
    win: bool
    outcome: Outcome | None  # set when Submit decided the attempt
    line_sounds: list[MoveSound]  # one per move you submitted


@dataclass(frozen=True)
class IdeaResult:
    """Name the idea first (FR-4.3): your tags against the puzzle's motif themes."""

    found: int
    total: int  # the puzzle's motifs; 0 means no tag score
    extra: int
    correct: list[ThemeLabel]  # your tags that were motifs
    wrong: list[ThemeLabel]  # your tags that weren't
    missed: list[ThemeLabel]  # motifs you didn't name


@dataclass(frozen=True)
class DangerReveal:
    """Danger spotting (FR-4.4): the truth about the candidate, after the end."""

    candidate: str  # UCI
    is_safe: bool
    call: Literal["safe", "unsafe"] | None  # None if you moved on (or used Show answer) before calling
    best_score: str | None  # a safe candidate: Stockfish's best line, from the blunderer's side…
    candidate_score: str | None  # …and the candidate's
    line: list[str]  # after the candidate: Stockfish's line (safe) or the refutation (the blunder)


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
    level_up: LadderInfo | None  # the depth ladder moved up with this attempt (FR-4.5)
    idea: IdeaResult | None  # Name the idea first (FR-4.3)
    danger: DangerReveal | None  # Danger spotting (FR-4.4)


@dataclass(frozen=True)
class DangerFeedback:
    """Danger spotting: your Safe/Unsafe call."""

    call: Literal["safe", "unsafe"]
    correct: bool
    refute: bool  # Unsafe on the real blunder: it was played; now find the refutation's first move
    fen: str  # the position after the call (after the blunder when you refute)
    blunder_sound: MoveSound | None  # the blunder's sound, when it was played
    outcome: Outcome | None  # set when the call decided the attempt


@dataclass(frozen=True)
class ReasonOption:
    key: ReasonKey
    label: str
    gap: Literal["process", "calculation", "knowledge", "time", "noise"]


@dataclass(frozen=True)
class ReasonPrompt:
    """§7.3: why did you miss it? The chips are `reasons`, in order (keys 1–6)."""

    attempt_id: int
    source: Literal["puzzle", "danger"]
    suggested: ReasonKey | None  # pre-highlighted only; saved when you click (FR-5.9)
    reasons: list[ReasonOption]


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
    refute: bool  # a wrong move was played: ask get_refutation for the engine's answer to it (§7.2)


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
    mode: TrainingMode
    ladder: LadderInfo | None  # depth ladder (FR-4.5)
    misclicks: int  # FR-5.10: left out of solved/failed/accuracy


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
class ModeDetails:
    """FR-9.3: each mode's own measure, as counts (a share is n/a when its total is 0)."""

    replies_correct: int  # Commit the line: calculation accuracy = replies_correct ÷ replies_total
    replies_total: int
    ideas_found: int  # Name the idea: ideas found = ideas_found ÷ ideas_total…
    ideas_total: int
    tags_named: int  # …tags right = ideas_found ÷ tags_named
    danger_safe: int  # Danger spotting: safe candidates shown, and called right
    danger_safe_right: int
    danger_blunder: int  # real blunders shown, and called right and refuted
    danger_blunder_right: int


@dataclass(frozen=True)
class StatsReport:
    overall: StatRow
    by_theme: list[StatRow]
    by_length: list[StatRow]
    by_rating: list[StatRow]
    missing: int  # attempts on puzzles no longer in the database
    by_mode: list[StatRow]  # v0.5 (FR-9.1)
    misclicks: int  # v0.6 (FR-5.10): left out of every row above
    misclick_warning: bool  # an unusually high share of your tagged misses are misclicks
    details: ModeDetails  # v0.6 (FR-9.3)


@dataclass(frozen=True)
class ReasonStatRow:
    key: ReasonKey
    label: str
    gap: Literal["process", "calculation", "knowledge", "time", "noise"]
    count: int
    share: float | None  # of the tagged misses (misclicks aside)


@dataclass(frozen=True)
class ReasonWeek:
    week: str  # ISO date of the Monday
    counts: list[int]  # per reason, in `ReasonStats.reasons` order


@dataclass(frozen=True)
class ReasonStats:
    """FR-9.7: why you missed puzzles (for one theme and/or mode when filtered)."""

    reasons: list[ReasonStatRow]  # every reason except misclick, in FR-5.6 order
    tagged: int
    untagged: int  # misses you didn't tag
    misclicks: int  # shown separately
    misclick_warning: bool
    trend: list[ReasonWeek]  # oldest first


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


# ---- engine (v0.4: FR-7.1–7.7) -------------------------------------------------------------------


@dataclass(frozen=True)
class EngineStatus:
    state: Literal["ready", "not_installed", "unsupported_platform", "custom_invalid"]
    source: Literal["managed", "custom"] | None
    name: str | None  # e.g. "Stockfish 19"
    path: str | None  # the exe in use (About, NFR-7)
    tag: str  # the pinned release, e.g. sf_19
    install_job_id: str | None  # an install in progress
    message: str | None


@dataclass(frozen=True)
class EngineSettings:
    think_s: float  # FR-7.4: 0.2–10 s, default 1
    threads: int  # 1–max_threads, default CPU cores − 1
    hash_mb: int  # 16–2048, default 256
    custom_path: str | None  # FR-7.5 advanced: your own engine's .exe
    max_threads: int


@dataclass(frozen=True)
class EngineLine:
    score: str  # from your side (FR-7.2): "+3.2 for you", "You mate in 3"
    cp: int | None  # centipawns from your side
    mate: int | None  # moves to mate from your side (negative: you're mated)
    pv: list[str]  # UCI, legal from the position


@dataclass(frozen=True)
class Analysis:
    fen: str
    lines: list[EngineLine]  # up to 3 (MultiPV, FR-7.2)
    game_over: str | None  # the position is over: no engine lines
    superseded: bool  # a newer request for the same view replaced this one: ignore it


@dataclass(frozen=True)
class Refutation:
    """§7.2 step 2: Stockfish's answer to the move that lost the puzzle."""

    fen_before: str
    wrong_move: str  # UCI
    line: list[str]  # the best reply line after it, 3–5 plies (UCI)
    score: str | None  # from your side
    game_over: str | None


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
    LadderInfo,
    IdeaResult,
    DangerReveal,
    Outcome,
    DangerFeedback,
    ReasonOption,
    ReasonPrompt,
    MoveFeedback,
    HelpResponse,
    PlyGrade,
    CommitFeedback,
    LadderPreview,
    SrsStatus,
    SessionStats,
    StatRow,
    ModeDetails,
    StatsReport,
    ReasonStatRow,
    ReasonWeek,
    ReasonStats,
    UpdateOffer,
    AccountStatus,
    SyncStatus,
    SyncEvent,
    RatingPoint,
    SessionChange,
    RatingHistory,
    EngineStatus,
    EngineSettings,
    EngineLine,
    Analysis,
    Refutation,
]
