"""Everything that crosses to JavaScript (ARCHITECTURE §3 decision 8).

`web/src/api/types.ts` is generated from this module by `scripts/gen_types.py`; a contract test
fails if the two drift. Only the classes in EXPORTED are generated, in that order. Never put a
secret in a DTO (SR-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
    reasons_ask: Literal["always", "game_review", "off"]  # FR-5.8: when to ask why you missed (game_review: v0.8)
    rushed_s: int  # FR-5.9: a deciding move faster than this suggests Rushed
    show_best: bool = False  # v0.10, FR-11.35: Game Review shows the better move (default off)
    lesson_sites: list[Literal["youtube", "chesscom", "custom"]] = field(
        default_factory=lambda: ["youtube", "chesscom"]
    )
    lesson_custom_url: str = ""  # v0.11, FR-10.59: an https address with {q}


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
    source: Literal["lichess", "my"] = "lichess"  # v0.8: my = your own puzzle (no rating, no opponent move)
    strict_without_engine: bool = False  # v0.8-B8: a puzzle from your games checked on its stored line (no Stockfish)
    solve_as_opponent: bool = False  # v0.10: an Allowed puzzle: "Find what your opponent could have played" (FR-10.42)
    game_id: int | None = None  # v0.10: the game a puzzle from your games came from (FR-10.44)
    game_ply: int | None = None


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


# ---- v0.7: LLM settings, the cost guardrails, Explain (FR-1.2–1.4, 1.10, §9) -------------------------
# No key ever crosses (SR-1): only whether one is stored.
LlmProviderName = Literal["anthropic", "openai"]


@dataclass(frozen=True)
class LlmModelOption:
    model: str
    explain_usd: float  # about what one Explain costs at the current reasoning level (FR-1.3)


@dataclass(frozen=True)
class LlmProviderInfo:
    provider: LlmProviderName
    label: str  # "Anthropic" / "OpenAI"
    key_stored: bool
    model: str  # the model picked for this provider; '' = none (nothing is pre-selected)
    models: list[LlmModelOption]  # the price table's models for this provider, cheapest first


@dataclass(frozen=True)
class LlmSpend:
    month: str  # YYYY-MM, local
    spent_usd: float
    budget_usd: float
    level: Literal["ok", "warn", "over"]  # FR-1.10 / 8.13: warn at 80%, blocked at 100%
    configured: bool  # a provider with a key: show the indicator


@dataclass(frozen=True)
class LlmModelChoice:
    """One model a feature's picker offers (FR-1.15): the price table's models of every provider."""

    provider: LlmProviderName
    model: str
    usd: float  # about what one request of this feature costs at its reasoning level


@dataclass(frozen=True)
class LlmFeature:
    """A model per AI feature (FR-1.15, v0.9). Explain's choice is `LlmSettings.provider` and the providers'
    models; every other feature can follow it ('same') or pick its own provider and model."""

    feature: Literal["explain", "game_review", "coach"]
    label: str
    choice: Literal["same", "anthropic", "openai", "none"]  # Explain: its provider; others: 'same' or their own
    model: str  # the feature's own model ('' when it follows Explain or none is picked)
    reasoning: Literal["low", "medium", "high"]
    provider: Literal["none", "anthropic", "openai"]  # what its requests use now
    effective_model: str
    ready: bool  # a provider with a stored key and a model with a price row
    spent_usd: float  # this month (FR-1.15)
    options: list[LlmModelChoice]


@dataclass(frozen=True)
class LlmSettings:
    provider: Literal["none", "anthropic", "openai"]
    reasoning: Literal["low", "medium", "high"]  # FR-8.15
    run_cap_usd: float  # FR-8.12
    monthly_budget_usd: float  # FR-8.13
    providers: list[LlmProviderInfo]
    spend: LlmSpend
    # FR-1.6: the silent key check at launch ('none': no AI set up, or a key was saved since).
    key_check: Literal["none", "checking", "ok", "failed"]
    key_check_message: str | None
    features: list[LlmFeature]  # v0.9: Explain first, then Game Review


@dataclass(frozen=True)
class LlmPrice:
    provider: LlmProviderName
    model: str
    input_per_m: float  # USD per 1M tokens
    output_per_m: float
    long_ctx_threshold: int | None  # the long-context tier applies above this many input tokens
    long_input_per_m: float | None
    long_output_per_m: float | None
    as_of: str  # YYYY-MM-DD


@dataclass(frozen=True)
class ExplainQuote:
    """Whether Explain can run for the puzzle that just ended, and roughly what it costs (FR-8.11)."""

    # 'ok', 'cached' (free), or why not: 'not_configured', 'no_model', 'no_price', 'over_budget', 'over_cap'
    state: str
    message: str | None
    provider: str
    model: str
    typical_usd: float | None  # the "about" figure on the button
    worst_usd: float | None  # every output token used: what the per-run cap is checked against


@dataclass(frozen=True)
class ExplainAnnotation:
    kind: Literal["arrow", "circle"]
    orig: str  # a square, validated (FR-8.4)
    dest: str | None  # arrows only
    color: Literal["green", "red", "blue", "yellow"]


@dataclass(frozen=True)
class ExplainStep:
    ply: int  # 0 = your first move
    side: Literal["you", "opponent"]
    san: str
    uci: str
    text: str  # plain text: show it escaped, never as HTML (FR-8.7)
    annotations: list[ExplainAnnotation]
    variation: list[str]  # SAN, checked legal from the position after this move


@dataclass(frozen=True)
class Explanation:
    summary: str
    steps: list[ExplainStep]  # validated; a ply may be missing if its step was discarded
    key_ideas: list[str]
    discarded: int  # > 0: "some annotations were discarded" (FR-8.4)
    provider: str
    model: str
    cost_usd: float  # 0 when cached
    cached: bool
    start_fen: str  # the position your first move is played in: Show me starts here
    solution: list[str]  # UCI from start_fen, both sides


# ---- v0.9: Game Review AI (§11.4) ---------------------------------------------------------------


@dataclass(frozen=True)
class GameAiQuote:
    """Whether Explain this move / Explain my game can run, and what it would cost (FR-8.11, 11.21)."""

    # 'ok', 'cached' (free), or why not: 'not_configured', 'no_model', 'no_price', 'over_budget', 'over_cap'
    state: str
    message: str | None
    provider: str
    model: str
    input_tokens: int | None  # the estimate (FR-8.11)
    typical_output_tokens: int | None
    max_output_tokens: int | None
    typical_usd: float | None
    worst_usd: float | None  # what the per-run cap is checked against (FR-8.12)
    run_cap_usd: float
    spent_usd: float  # this month, for "x% of what's left of your budget"
    budget_usd: float


@dataclass(frozen=True)
class GameMoment:
    ply: int
    played_san: str
    text: str
    annotations: list[ExplainAnnotation]  # in the position before the move, validated
    better_line: list[str]  # SAN from the position before the move; starts with Stockfish's best move
    better_uci: list[str]


@dataclass(frozen=True)
class SuggestedPreset:
    """FR-11.18: offered only; Train these applies it when you click it."""

    themes: list[str]
    names: list[str]
    rating_min: int | None
    rating_max: int | None


@dataclass(frozen=True)
class GameNarrative:
    game_id: int
    n: int
    key_moments: list[int]  # the plies it covers
    opening_summary: str
    turning_point: int | None  # a ply
    themes: list[str]
    takeaways: list[str]
    moments: list[GameMoment]
    preset: SuggestedPreset | None
    discarded: int  # > 0: "some annotations were discarded" (FR-8.4)
    provider: str
    model: str
    cost_usd: float  # 0 when cached
    cached: bool


# ---- v0.8: game library, Game Review, your own puzzles -------------------------------------------


@dataclass(frozen=True)
class ReviewThresholds:
    inaccuracy: int
    mistake: int
    blunder: int
    decided: int  # positions beyond this aren't penalized (FR-11.9)


@dataclass(frozen=True)
class GamesSettings:
    lichess_username: str | None  # linked automatically when you're signed in (FR-11.23)
    chesscom_username: str | None  # linked by username (FR-11.24)
    sync_on_open: bool
    first_sync_days: int
    first_sync_max: int
    think_s: float  # per position (FR-11.8)
    thresholds: ReviewThresholds
    tolerance_cp: int  # Retry mode and puzzles saved from your games (FR-11.15, FR-10.43)
    key_moments: int
    puzzle_level: Literal["blunders", "mistakes", "inaccuracies"] = "mistakes"  # v0.10, FR-10.40
    puzzle_think_s: float = 1.0  # v0.10: per position while checking a puzzle's line (FR-10.41)
    puzzle_job_id: str | None = None  # a level change that has new mistakes to check starts this job


@dataclass(frozen=True)
class ChesscomProfile:
    username: str
    name: str | None
    url: str | None
    joined: int | None


@dataclass(frozen=True)
class GameSummary:
    """One row of My games (FR-11.25). Players are per color; `opponent` is from your side when known."""

    id: int
    source: Literal["lichess", "chesscom", "paste", "file"]
    url: str | None
    played_at: str | None
    time_class: str | None
    time_control: str | None
    rated: bool | None
    white: str | None
    black: str | None
    white_rating: int | None
    black_rating: int | None
    user_color: Literal["white", "black", "both"] | None
    opponent: str | None
    opponent_rating: int | None
    user_rating: int | None
    result: str
    user_result: Literal["win", "loss", "draw"] | None
    eco: str | None
    opening: str | None
    accuracy_user: float | None
    accuracy_opponent: float | None
    lichess_analyzed: bool  # the badge: Lichess already has computer analysis
    analysis_status: Literal["none", "analyzed", "ai_reviewed"]  # ai_reviewed: v0.9 (FR-11.25)


@dataclass(frozen=True)
class GamePage:
    games: list[GameSummary]
    total: int


@dataclass(frozen=True)
class GameChoice:
    index: int
    label: str
    error: str | None  # why this game can't be imported


@dataclass(frozen=True)
class GameImport:
    """An import's result: a stored game, or (several games in a file) the list to pick from."""

    game_id: int | None
    created: bool
    needs_color: bool  # ask which side you played (FR-11.5)
    analyzed: bool  # a re-import found its analysis (FR-11.7)
    choices: list[GameChoice]
    token: str | None  # pass it to pick_imported_game with a choice's index


@dataclass(frozen=True)
class AnalysisQueue:
    job_id: str | None  # the running analysis job, if any
    current: int | None  # the game being analyzed
    waiting: list[int]


@dataclass(frozen=True)
class ReviewLine:
    score: str  # from the mover's side
    pv: list[str]  # UCI
    sans: list[str]


@dataclass(frozen=True)
class ReviewMove:
    ply: int
    san: str
    uci: str
    mover: Literal["white", "black"]
    fen_before: str
    classification: Literal["best", "good", "inaccuracy", "mistake", "blunder"] | None
    symbol: str | None  # ?! ? ??
    cp_loss: int | None
    eval_white: int | None  # after the move, White's side, clamped to ±1000 (the eval graph)
    eval_text: str | None
    best_move: str | None
    best_san: str | None
    lines: list[ReviewLine]  # the top engine lines before the move (FR-11.14)
    refutation: list[str]  # UCI after the move: the best reply line (FR-11.14)
    kind: Literal["missed", "allowed", "other"] | None
    phase: Literal["opening", "middlegame", "endgame"] | None
    low_clock: bool | None
    reason: str | None  # your mistake reason (FR-5.7)
    suggested_reason: str | None
    saved: bool  # already saved as a puzzle


@dataclass(frozen=True)
class PhaseSummary:
    phase: Literal["opening", "middlegame", "endgame"]
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    avg_cp_loss: float | None


@dataclass(frozen=True)
class SideSummary:
    color: Literal["white", "black"]
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    avg_cp_loss: float | None
    platform_accuracy: float | None
    phases: list[PhaseSummary]
    low_clock_errors: int | None


@dataclass(frozen=True)
class GameReview:
    game: GameSummary
    start_fen: str
    moves: list[ReviewMove]
    analyzed: bool
    current: bool  # analyzed at today's settings
    summaries: list[SideSummary]  # White, then Black (FR-11.11)
    key_moments: list[int]  # plies (FR-11.13)
    retry_plies: list[int]  # your mistakes and blunders (FR-11.15)
    ask_reasons: bool  # FR-5.8


@dataclass(frozen=True)
class RetryResult:
    retry_id: int
    found: bool
    played_san: str
    played_score: str
    best_san: str | None
    best_line: list[str]  # UCI: the answer, sent only with the result
    reply_line: list[str]  # the engine's answer to your move, when it wasn't found
    suggested_reason: str | None
    engine_checked: bool


@dataclass(frozen=True)
class SavedPuzzle:
    puzzle_id: int
    created: bool


@dataclass(frozen=True)
class PuzzleImportError:
    n: int  # entry number in the file, from 1
    reason: str


@dataclass(frozen=True)
class PuzzleImportReport:
    label: str
    file_name: str
    format: Literal["pgn", "epd", "csv"]
    entries: int
    added: int
    duplicates: int
    skipped: int
    errors: list[PuzzleImportError]  # the first 500 skipped entries


@dataclass(frozen=True)
class PuzzleSet:
    label: str
    count: int


@dataclass(frozen=True)
class SourceAccuracy:
    source: Literal["lichess", "my"]
    attempts: int
    wins: int


@dataclass(frozen=True)
class GameStats:
    retry_found: int
    retry_tried: int
    sources: list[SourceAccuracy]


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
    LlmModelOption,
    LlmProviderInfo,
    LlmSpend,
    LlmModelChoice,
    LlmFeature,
    LlmSettings,
    LlmPrice,
    ExplainQuote,
    ExplainAnnotation,
    ExplainStep,
    Explanation,
    GameAiQuote,
    GameMoment,
    SuggestedPreset,
    GameNarrative,
    ReviewThresholds,
    GamesSettings,
    ChesscomProfile,
    GameSummary,
    GamePage,
    GameChoice,
    GameImport,
    AnalysisQueue,
    ReviewLine,
    ReviewMove,
    PhaseSummary,
    SideSummary,
    GameReview,
    RetryResult,
    SavedPuzzle,
    PuzzleImportError,
    PuzzleImportReport,
    PuzzleSet,
    SourceAccuracy,
    GameStats,
]


# ---- v0.10: the Coach (§10) ------------------------------------------------------------------------


@dataclass(frozen=True)
class CoachExample:
    game_id: int
    ply: int
    cp_loss: int


@dataclass(frozen=True)
class CoachWeakness:
    key: str  # missed:<theme> / allowed:<theme> / habit:<habit> / puzzle:<theme>
    kind: Literal["missed", "allowed", "habit", "puzzle", "opening", "endgame", "phase", "time"]
    name: str
    label: str
    count: int
    per10: float  # per 10 games (FR-10.38)
    severity: int  # average eval lost, cp
    score: float
    themes: list[str]
    mode: str | None
    reasons: dict[str, int]  # latest mistake reason -> count (§7.3)
    examples: list[CoachExample]
    puzzle_accuracy: float | None
    trend: float | None  # change in per10 against your previous report (FR-10.20); None: no previous


@dataclass(frozen=True)
class CoachGapRow:
    theme: str
    label: str
    puzzle_accuracy: float | None
    puzzle_attempts: int
    missed_per10: float
    allowed_per10: float


@dataclass(frozen=True)
class CoachPresetView:
    """A preset to Load or Save (FR-10.24): the filters, the drill mode and why."""

    name: str
    spec: dict[str, Any]  # FilterSpec JSON
    mode: str
    why: list[str]


@dataclass(frozen=True)
class CoachReport:
    id: int
    created_at: str
    subject_label: str
    is_me: bool  # False: another player's report (FR-10.3)
    source: Literal["puzzles", "games", "both"]
    params: dict[str, Any]
    games: int
    first_played: str | None
    last_played: str | None
    per10: dict[str, float]
    results: dict[str, int]
    missed: list[CoachWeakness]
    allowed: list[CoachWeakness]
    habits: list[CoachWeakness]
    puzzles: list[CoachWeakness]
    gap: list[CoachGapRow]
    reasons: dict[str, int]
    low_clock_errors: int
    preset: CoachPresetView | None
    notes: list[str]
    whole_game: list[CoachWeakness] = field(default_factory=list)  # v0.11, FR-10.57
    measures: CoachMeasures | None = None  # v0.11, FR-10.53; None for older reports


@dataclass(frozen=True)
class CoachReportSummary:
    id: int
    created_at: str
    subject_label: str
    is_me: bool
    source: Literal["puzzles", "games", "both"]
    games: int
    top: list[str]  # the top weaknesses' labels


@dataclass(frozen=True)
class PlayerSubject:
    """Another player you ran the Coach on (the Player filter in My Games)."""

    subject: str  # <platform>:<username>
    label: str
    games: int


@dataclass(frozen=True)
class CoachDefaults:
    params: dict[str, Any]  # the last run's settings (FR-10.2–10.5)
    usernames: list[str]  # your linked accounts
    players: list[PlayerSubject]
    running_job: str | None  # a Coach run in progress


@dataclass(frozen=True)
class CoachOpeningRow:
    family: str
    games: int
    score: float  # % (a draw counts half)
    avg_eval_end: int | None  # your view at move 15, cp
    errors_first15: int
    enough: bool  # at least 5 games (FR-10.53); otherwise "not enough data yet"


@dataclass(frozen=True)
class CoachEndgameRow:
    type: str
    label: str
    games: int
    wins: int
    draws: int
    losses: int
    errors: int
    enough: bool


@dataclass(frozen=True)
class CoachRateRow:
    games: int
    hits: int  # converted (won) or saved (not lost)
    rate: float | None  # %
    enough: bool


@dataclass(frozen=True)
class CoachTimeRow:
    games: int
    low_moves: int
    low_errors: int
    low_blunders: int
    low_error_rate: float | None  # mistakes and blunders per 100 moves
    other_moves: int
    other_errors: int
    other_blunders: int
    other_error_rate: float | None
    enough: bool


@dataclass(frozen=True)
class CoachKingRow:
    games: int
    late: int
    late_score: float | None
    on_time_score: float | None
    enough: bool


@dataclass(frozen=True)
class CoachMeasures:
    """FR-10.53, free: whole-game measures over the report's games."""

    games: int
    min_games: int
    openings: list[CoachOpeningRow]
    errors_per10_by_phase: dict[str, float]
    conversion: CoachRateRow
    saves: CoachRateRow
    endgames: list[CoachEndgameRow]
    time: CoachTimeRow
    king: CoachKingRow


@dataclass(frozen=True)
class CoachAdvancedCompare:
    """FR-10.56: an Advanced run against a standard one, for the Confirm dialog."""

    games_with_moves: int
    token_ratio: float | None
    standard_usd: float | None
    budget_share: float | None  # of the monthly budget
    minutes: int


@dataclass(frozen=True)
class CoachAiQuote:
    quote: GameAiQuote
    compare: CoachAdvancedCompare | None  # Advanced only
    cached_run: int | None  # 'cached': the stored answer that will show again, free


@dataclass(frozen=True)
class CoachAiRunSummary:
    id: int
    created_at: str
    format: Literal["keyed", "diagnosis"]
    advanced: bool
    include_notes: bool
    game_cap: int | None
    provider: str
    model: str
    cost_usd: float
    findings: int
    new: int  # findings no earlier run of this report had


@dataclass(frozen=True)
class CoachEvidence:
    label: str  # G3
    game_id: int  # opens Game Review (FR-10.55); never sent to the AI
    ply: int  # 0-based, as Game Review takes it
    move: str  # "23... Nf6", from your own analysis, not from the AI


@dataclass(frozen=True)
class CoachLesson:
    """FR-10.59 pointers for a topic. No URLs: the backend builds and opens them."""

    topic: str
    label: str
    drill: CoachPresetView | None  # "Learn X"
    curated: list[str]  # titles, opened as "curated:<index>"
    sites: list[Literal["youtube", "chesscom", "custom"]]


@dataclass(frozen=True)
class CoachFinding:
    key: str | None  # a measured weakness (tracked) or None
    label: str | None  # that weakness's label
    category: Literal["tactical", "strategic", "opening", "endgame", "time", "other"]
    title: str
    explanation: str
    advice: str
    tentative: bool  # fewer than 3 games cited (FR-10.55)
    observation: bool  # can't be measured (FR-10.57)
    seen: int  # observations: how many of your reports have found it
    new: bool  # no earlier AI run of this report had it
    evidence: list[CoachEvidence]
    lesson: CoachLesson | None


@dataclass(frozen=True)
class CoachAiRun:
    id: int
    created_at: str
    format: Literal["keyed", "diagnosis"]
    advanced: bool
    include_notes: bool
    game_cap: int | None
    summary: str
    findings: list[CoachFinding]
    presets: list[CoachPresetView]
    fallback_preset: bool  # no AI preset survived validation: the report's own (FR-10.23)
    discarded: int
    provider: str
    model: str
    cost_usd: float


@dataclass(frozen=True)
class CoachNote:
    """One note Include my notes would send (FR-10.60), exactly as sent."""

    game: str | None  # G label, or None for a puzzle note
    ply: int | None  # 1-based, as sent
    move: str | None
    reason: str | None
    text: str
    source: Literal["game", "retry", "puzzle", "danger"]


@dataclass(frozen=True)
class SuggestionView:
    """The Suggested mix (FR-10.28–10.31)."""

    report_id: int
    number: int
    created_at: str
    label: str  # "Suggested — from Coach run #N, <date>"
    spec: dict[str, Any]
    mode: str
    why: list[str]
    pending: bool  # the banner: Apply / Compare / Dismiss
    previous: dict[str, Any] | None  # your filters it would replace (Compare)
    active: bool  # your current filters are this suggestion


EXPORTED += [
    CoachExample,
    CoachWeakness,
    CoachGapRow,
    CoachPresetView,
    CoachReport,
    CoachReportSummary,
    PlayerSubject,
    CoachDefaults,
    CoachOpeningRow,
    CoachEndgameRow,
    CoachRateRow,
    CoachTimeRow,
    CoachKingRow,
    CoachMeasures,
    CoachAdvancedCompare,
    CoachAiQuote,
    CoachAiRunSummary,
    CoachEvidence,
    CoachLesson,
    CoachFinding,
    CoachAiRun,
    CoachNote,
    SuggestionView,
]
