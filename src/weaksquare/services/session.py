"""Training sessions: queue, puzzles, moves and attempts (FR-3.10–3.12, 3.14, FR-4.1, FR-5.1, 5.3, 5.5).

v0.5: the training mode is chosen per session (§6): Standard, Commit the line (FR-4.2) or Spaced
repetition (FR-4.6, a queue of due puzzles played with Standard's rules). The depth ladder (FR-4.5) is
an order: the session draws from the current level and moves up when the window says so.

v0.6: Name the idea first (FR-4.3, Standard's rules after tagging) and Danger spotting (FR-4.4: the
interactive engine checks the safe candidates; results stay local). After a lost puzzle, the reason
prompt (§7.3) suggests why you missed it (FR-5.9).

Session state (queue, current puzzle, mode state) is kept in memory; every decided attempt is
appended to `attempts` at once, so closing the app never loses a result.
"""

from __future__ import annotations

import dataclasses
import logging
import random
import threading
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import chess

from weaksquare.core.chess_rules import PuzzleDataError, is_acceptable, parse_move, start_position
from weaksquare.core.clock import Clock
from weaksquare.core.engine import (
    REFUTATION_MIN_PLIES,
    EngineError,
    EngineNotInstalled,
    refutation_plies,
    validate_fen,
    validate_line,
)
from weaksquare.core.errors import AppError, ConflictError, NotFoundError, StaleKeyError, ValidationError
from weaksquare.core.explain import CacheKeyParts, DangerFact, EngineLineFact, ExplainInput, RefutationFact
from weaksquare.core.filters import FilterSpec
from weaksquare.core.game_review import Score
from weaksquare.core.ladder import DEFAULT_THRESHOLD, DEFAULT_WINDOW, LEVELS, LadderStatus, ladder_key
from weaksquare.core.ladder import status as ladder_status
from weaksquare.core.modes.base import OPPONENT_DELAY_MS, AttemptResult, Feedback, HelpKind, HelpResult
from weaksquare.core.modes.commit_line import CommitLineMode, CommitResult, CommitState, max_plies
from weaksquare.core.modes.danger import MODE as DANGER
from weaksquare.core.modes.danger import MULTIPV as DANGER_MULTIPV
from weaksquare.core.modes.danger import (
    CallResult,
    DangerMode,
    DangerState,
    ScoredMove,
    pick_safe,
    safe_candidates,
    wants_safe,
)
from weaksquare.core.modes.name_idea import IdeaScore, IdeaTags, NameIdeaMode, NameIdeaState
from weaksquare.core.modes.standard import StandardMode, StandardState
from weaksquare.core.move_sounds import MoveSound, sounds_for_line
from weaksquare.core.puzzle import Color, Puzzle, PuzzleRef
from weaksquare.core.queue import allocate, order_by_theme, order_easy_to_hard, refill_size, theme_group
from weaksquare.core.reasons import DEFAULT_RUSHED_S, ReasonContext, is_forcing_reply, suggest
from weaksquare.core.scoring import MIX, angle_for
from weaksquare.core.srs import DEFAULT_INTERVALS, Card, Review, due_order, next_due, schedule
from weaksquare.core.srs import MODE as SRS_MODE
from weaksquare.core.themes import display_name
from weaksquare.core.tolerance import DEFAULT_TOLERANCE_CP, within_tolerance
from weaksquare.services.engine import Analysis, EngineService

log = logging.getLogger(__name__)

MAX_BAD_PUZZLES = 20
STANDARD, COMMIT, NAME = "standard", "commit_line", "name_idea"
MODES = (STANDARD, COMMIT, NAME, DANGER, SRS_MODE)  # the Modes control, in order (v0.5, v0.6)
LADDER_MODES = (STANDARD, COMMIT)  # FR-3.11: the depth ladder works in these
State = StandardState | CommitState | DangerState  # NameIdeaState is a StandardState


class PuzzleSource(Protocol):
    def version(self) -> int: ...

    def keys_for_ids(self, ids: list[str]) -> set[int]: ...

    def count(self, spec: FilterSpec) -> int: ...

    def count_with_buckets(self, spec: FilterSpec) -> tuple[int, list[int]]: ...

    def sample_keys(
        self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int], match_count: int
    ) -> list[int]: ...

    def get(self, key: int, version: int | None = None) -> Puzzle | None:
        """With `version`: raises StaleKeyError if the database changed since."""
        ...

    def describe(self, keys: list[int]) -> dict[int, tuple[int, tuple[str, ...]]]:
        """(rating, themes) per key, for ordering a queue."""
        ...

    def has_puzzles(self, spec: FilterSpec) -> bool:
        """Depth ladder: does anything match (an existence check that stops at the first match, v0.5-B7)."""
        ...

    def levels_with_puzzles(self, spec: FilterSpec, levels: Sequence[int]) -> list[int]:
        """Depth ladder: which of these levels have any puzzle (existence checks)."""
        ...

    def count_level_and_above(self, spec: FilterSpec, level: int) -> tuple[int, int]:
        """Depth ladder: the count at a level and above it, in one scan."""
        ...

    def key_map(self, ids: list[str]) -> dict[str, int]:
        """Current key per puzzle ID (IDs a newer export dropped are missing). Spaced repetition (v0.5)."""
        ...


class Attempts(Protocol):
    def append(
        self,
        ref: PuzzleRef,
        session_id: int,
        mode: str,
        started_at: str,
        finished_at: str,
        result: AttemptResult,
        puzzle_rating: int | None = None,
        sync: Any = None,
        extra: Any = None,
    ) -> int: ...

    def session_tally(self, session_id: int) -> object: ...

    def all_time_tally(self) -> object: ...

    def srs_rows(self) -> list[Any]: ...  # list[SrsRow]: puzzle_id, finished_at, mode, win

    def ladder_history(self, key: str, window: int) -> tuple[int | None, list[bool]]: ...


class TrainingPrefs(Protocol):
    """The training settings (v0.5), from services/ui_settings.py."""

    def srs_intervals(self) -> tuple[int, ...]: ...

    def ladder_threshold(self) -> int: ...

    def ladder_window(self) -> int: ...

    def reasons_ask(self) -> str: ...  # FR-5.8: 'always', 'game_review' (v0.8) or 'off'

    def rushed_s(self) -> int: ...  # v0.6 (FR-5.9)


class _DefaultPrefs:
    def srs_intervals(self) -> tuple[int, ...]:
        return DEFAULT_INTERVALS

    def ladder_threshold(self) -> int:
        return DEFAULT_THRESHOLD

    def ladder_window(self) -> int:
        return DEFAULT_WINDOW

    def reasons_ask(self) -> str:
        return "always"

    def rushed_s(self) -> int:
        return DEFAULT_RUSHED_S


class Sessions(Protocol):
    def create(self, started_at: str, mode: str, filters: dict, queue_size: int | None) -> int: ...


class SyncHooks(Protocol):
    """The Lichess sync queue, as the session sees it (v0.3; services/sync.py)."""

    def fields_for(self, puzzle_id: str) -> Any: ...  # QueueFields(account, already_played)

    def played_before(self, puzzle_id: str) -> bool: ...

    def recorded(self) -> None: ...

    def attempt_ratings(self, attempt_ids: list[int]) -> list: ...  # list[RatingInfo]

    def session_change(self, session_id: int) -> int | None: ...


@dataclass(frozen=True)
class Refutation:
    """§7.2 step 2: why your move failed: the engine's best reply line (3–5 plies) and the eval."""

    fen_before: str  # the position you played the wrong move in
    wrong_move: str  # UCI
    line: tuple[str, ...]  # the reply line after it (UCI)
    score: str | None  # from your side (FR-7.2); None when the game ended
    game_over: str | None = None
    mate: int | None = None  # from your side: < 0 means the refutation mates you (mistake reasons, FR-5.9)


AnalysisPurpose = Literal["start", "panel", "board"]
PURPOSES = ("start", "panel", "board")


@dataclass(frozen=True)
class _ReasonBase:
    """What the reason suggestion needs from a lost attempt, taken when it's recorded (FR-5.9). The
    refutation part is added when the prompt is asked for, from Stockfish's answer to `first_wrong`."""

    attempt_id: int
    source: str  # 'puzzle' / 'danger'
    decisive_ms: int | None
    first_right_later_wrong: bool
    first_wrong: tuple[str, str] | None
    idea_found: int | None
    idea_total: int | None
    called_blunder_safe: bool


@dataclass
class _Current:
    state: State
    started_at: str
    refutation: Refutation | None = None
    analyses: dict[str, Analysis] = field(default_factory=dict)  # by FEN, for this puzzle
    reason: _ReasonBase | None = None  # set when the attempt was recorded as a loss
    suggested: str | None = None  # the last suggestion the prompt gave
    refuting: threading.Event | None = None  # a refutation search is running; set when it's done (v0.6-B3)


@dataclass
class _Session:
    id: int
    spec: FilterSpec
    match_count: int
    db_version: int
    rated: bool = True  # FR-1.9: the session's Rated toggle
    queue: deque[int] = field(default_factory=deque)
    served_keys: set[int] = field(default_factory=set)
    served_ids: list[str] = field(default_factory=list)
    served: int = 0
    current: _Current | None = None
    exhausted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Ratios (FR-3.10): one pool per bucket, how many each has given, and which bucket gave a key.
    buckets: list[FilterSpec] = field(default_factory=list)
    weights: list[int] = field(default_factory=list)  # 0 once a bucket has run dry
    bucket_counts: list[int] = field(default_factory=list)
    drawn: list[int] = field(default_factory=list)
    key_bucket: dict[int, int] = field(default_factory=dict)
    # v0.5: the mode, and what it needs.
    mode: str = STANDARD
    show_length: bool = False  # Commit the line's Show move count (FR-4.2)
    srs_ids: deque[str] = field(default_factory=deque)  # Spaced repetition: due puzzles left, in order
    ladder_base: FilterSpec | None = None  # the filters as chosen (order = depth_ladder); `spec` is the level's pool
    ladder: LadderStatus | None = None
    ladder_levels: list[int] = field(default_factory=list)  # open levels known at start (see ladder_preview)
    # v0.6: Danger spotting owes the next puzzle a safe candidate when one had none (FR-4.4).
    owed_safe: bool = False


@dataclass(frozen=True)
class SessionInfo:
    session_id: int
    match_count: int
    queue_size: int | None
    empty_buckets: list[int] = field(default_factory=list)  # ratio groups with no puzzles: left out
    mode: str = STANDARD


@dataclass(frozen=True)
class PuzzleView:
    """What the board needs. No themes: they're hidden until the attempt is decided (FR-3.14)."""

    number: int
    puzzle_id: str
    fen: str  # before the opponent's move
    opponent_move: str  # played (animated) first
    player_color: str
    rating: int
    opponent_sound: MoveSound | None  # FR-1.13: the opponent's first move plays a sound too (None: Danger spotting)
    already_played: bool = False  # Lichess has seen it from you: rating unaffected (badge)
    mode: str = STANDARD
    solution_plies: int | None = None  # Commit the line with Show move count only: how many moves to enter
    max_plies: int | None = None  # Commit the line: the longest line Submit accepts
    candidate: str | None = None  # Danger spotting: the highlighted move (never says if it's the blunder)
    source: str = "lichess"  # v0.8: "my" for your own puzzles (no rating or opponent move first; never synced)
    strict_without_engine: bool = False  # v0.8-B8: a puzzle from your games, checked on its stored line


@dataclass(frozen=True)
class Outcome:
    win: bool
    puzzle_id: str
    themes: list[str]
    solution: list[str]
    rating: int
    attempt_id: int = 0
    lichess: Any = None  # RatingInfo: the Lichess rating change, or why there isn't one (FR-6.11b)
    level_up: LadderStatus | None = None  # the depth ladder moved up with this attempt (FR-4.5)
    idea: IdeaScore | None = None  # Name the idea: your tags, graded (FR-4.3)
    danger: DangerReveal | None = None  # Danger spotting: the truth about the candidate (FR-4.4)


@dataclass(frozen=True)
class DangerReveal:
    candidate: str
    is_safe: bool
    call: str | None
    best_score: str | None  # safe candidates: Stockfish's best line…
    candidate_score: str | None  # …and the candidate's, from the blunderer's side
    line: tuple[str, ...]  # after the candidate: Stockfish's line (safe) or the refutation (the blunder)


@dataclass(frozen=True)
class SafeInfo:
    """Kept on a Danger state with a safe candidate, for the reveal after the end."""

    best_score: str
    candidate_score: str
    line: tuple[str, ...]


@dataclass(frozen=True)
class DangerOutcome:
    result: CallResult
    outcome: Outcome | None


@dataclass(frozen=True)
class ReasonPrompt:
    """§7.3: ask why you missed this one. `suggested` is only pre-highlighted (FR-5.9)."""

    attempt_id: int
    source: str
    suggested: str | None


@dataclass(frozen=True)
class MoveResult:
    feedback: Feedback
    outcome: Outcome | None


@dataclass(frozen=True)
class CommitOutcome:
    result: CommitResult
    outcome: Outcome | None  # set when Submit decided the attempt


@dataclass(frozen=True)
class SrsStatus:
    """For the mixer in Spaced-repetition mode (FR-4.6)."""

    due: int  # due today (puzzles still in the database)
    next_due: str | None  # ISO date of the next one after today
    scheduled: int  # in a box and not graduated


@dataclass(frozen=True)
class HelpOutcome:
    help: HelpResult
    outcome: Outcome | None  # set when this help decided the attempt (a loss, FR-5.2)


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
    rating_change: int | None = None  # FR-6.11c: the sum of the changes Lichess returned
    mode: str = STANDARD
    ladder: LadderStatus | None = None  # depth ladder (FR-4.5): the level and its window
    misclicks: int = 0  # FR-5.10: left out of solved/failed/accuracy, counted here


def _parse_time(text: str) -> datetime:
    """`finished_at` as stored (ISO, UTC). Very old rows without an offset are read as UTC."""
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


class SessionService:
    def __init__(
        self,
        puzzles: PuzzleSource,
        attempts: Attempts,
        sessions: Sessions,
        clock: Clock,
        rng: random.Random,
        sync: SyncHooks | None = None,
        queue_fields: Any = None,
        engine: EngineService | None = None,
        prefs: TrainingPrefs | None = None,
        mode_fields: Any = None,
        tolerance_cp: Any = None,
    ) -> None:
        """`sync` queues every decided attempt for Lichess (v0.3); without it attempts stay local.
        `queue_fields` builds the repo's SyncFields (passed in so services don't import adapters)."""
        self._sync = sync
        self._queue_fields = queue_fields
        self._engine = engine
        self._puzzles = puzzles
        self._attempts = attempts
        self._sessions_repo = sessions
        self._clock = clock
        self._rng = rng
        self._rng_lock = threading.Lock()
        self._prefs: TrainingPrefs = prefs or _DefaultPrefs()
        # Builds the repo's ModeFields (passed in, like queue_fields, so services don't import adapters).
        self._mode_fields = mode_fields or (lambda **kw: None)
        # v0.8: the engine tolerance for puzzles saved from your games (FR-10.43), shared with Retry mode.
        self._tolerance_cp = tolerance_cp or (lambda: DEFAULT_TOLERANCE_CP)
        self._standard = StandardMode()
        self._commit = CommitLineMode()
        self._name = NameIdeaMode()
        self._danger = DangerMode()
        self._modes: dict[str, Any] = {COMMIT: self._commit, NAME: self._name, DANGER: self._danger}
        self._sessions: dict[int, _Session] = {}

    def _mode_for(self, s: _Session) -> Any:
        return self._modes.get(s.mode, self._standard)  # SRS plays by Standard's rules

    def _require_engine(self) -> EngineService:
        """Danger spotting checks its safe candidates with Stockfish (FR-4.4, FR-7.2)."""
        if self._engine is None or self._engine.status().state != "ready":
            raise EngineNotInstalled(
                "Danger spotting needs Stockfish to check the safe moves. Install it in Settings → Engine."
            )
        return self._engine

    def start(
        self, spec: FilterSpec, rated: bool = True, mode: str = STANDARD, show_length: bool = False
    ) -> SessionInfo:
        if mode not in MODES:
            raise ValidationError("Unknown training mode.")
        if mode == SRS_MODE:
            return self._start_srs(spec, rated)
        if spec.source != "lichess" and mode in (NAME, DANGER):
            raise ValidationError(
                "My puzzles works in Standard, Commit the line and Spaced repetition. Choose Lichess DB for this mode."
            )
        if spec.depth_ladder and mode not in LADDER_MODES:
            raise ValidationError("The depth ladder works in Standard and Commit the line. Choose another order.")
        if mode == DANGER:
            self._require_engine()
            rated = False  # FR-4.4: Danger spotting never syncs
        ladder = None
        base = None
        ladder_levels: list[int] = []
        if spec.depth_ladder:
            base = spec
            ladder, ladder_levels, _ = self.ladder_preview(spec)
            spec = spec.at_ladder_level(ladder.level)
        buckets = [spec.bucket(i) for i in range(len(spec.ratios))]
        if buckets:
            count, bucket_counts = self._puzzles.count_with_buckets(spec)
        else:
            count, bucket_counts = self._puzzles.count(spec), []
        if count == 0:
            if ladder is not None:
                raise ValidationError("No puzzles match these filters at this ladder level. Widen them and try again.")
            raise ValidationError("No puzzles match these filters. Widen them and try again.")
        sid = self._sessions_repo.create(self._clock.now().isoformat(timespec="seconds"), mode,
                                         (base or spec).to_json(), spec.queue_size)  # fmt: skip
        session = _Session(sid, spec, count, self._puzzles.version(), rated, mode=mode,
                           show_length=show_length and mode == COMMIT, ladder_base=base, ladder=ladder,
                           ladder_levels=ladder_levels)  # fmt: skip
        if buckets:
            # An empty group is left out and the others share its slots (renormalized).
            session.buckets = buckets
            session.bucket_counts = bucket_counts
            session.weights = [b.weight if n > 0 else 0 for b, n in zip(spec.ratios, bucket_counts, strict=True)]
            session.drawn = [0] * len(buckets)
        self._sessions[sid] = session
        return SessionInfo(sid, count, spec.queue_size, [i for i, n in enumerate(bucket_counts) if n == 0], mode)

    # ---- Spaced repetition (FR-4.6) ------------------------------------------------------------------

    def _cards(self) -> dict[str, Card]:
        intervals = self._prefs.srs_intervals()
        by_puzzle: dict[str, list[Review]] = {}
        for r in self._attempts.srs_rows():
            by_puzzle.setdefault(r.puzzle_id, []).append(Review(_parse_time(r.finished_at), r.mode, r.win))
        cards: dict[str, Card] = {}
        for pid, reviews in by_puzzle.items():
            card = schedule(reviews, intervals, self._clock.local_date)
            if card is not None:
                cards[pid] = card
        return cards

    def _due_ids(self) -> tuple[list[str], dict[str, Card]]:
        cards = self._cards()
        due = due_order(cards, self._clock.local_date(self._clock.now()))
        present = self._puzzles.key_map(due) if due else {}
        return [pid for pid in due if pid in present], cards

    def srs_status(self) -> SrsStatus:
        due, cards = self._due_ids()
        nxt = next_due(cards, self._clock.local_date(self._clock.now()))
        return SrsStatus(len(due), nxt.isoformat() if nxt else None, sum(1 for c in cards.values() if not c.graduated))

    def _start_srs(self, spec: FilterSpec, rated: bool) -> SessionInfo:
        """The due puzzles, most overdue first. The filters don't apply, except the queue size."""
        due, _ = self._due_ids()
        if not due:
            raise ValidationError("Nothing is due for review. Missed puzzles come back here on their review day.")
        plain = FilterSpec(queue_size=spec.queue_size)  # reported as `mix`: nothing was chosen in advance
        sid = self._sessions_repo.create(self._clock.now().isoformat(timespec="seconds"), SRS_MODE,
                                         plain.to_json(), plain.queue_size)  # fmt: skip
        session = _Session(sid, plain, len(due), self._puzzles.version(), rated, mode=SRS_MODE, srs_ids=deque(due))
        self._sessions[sid] = session
        return SessionInfo(sid, len(due), plain.queue_size, [], SRS_MODE)

    # ---- Depth ladder (FR-4.5) -----------------------------------------------------------------------

    def _promotes(self, level: int, recorded: int | None, recent: list[bool], window: int, threshold: int) -> bool:
        counted = recent[-window:]
        wins = sum(1 for r in counted if r)
        return level == recorded and len(counted) >= window and wins * 100 >= threshold * window

    def ladder_preview(self, spec: FilterSpec) -> tuple[LadderStatus, list[int], int]:
        """Where a depth-ladder session with these filters is (FR-4.5): the status, the open levels it needs
        (FR-4.5 skips empty ones, v0.5-B2) and the pool size at its level.

        Kept within the live-count target on the full DB (v0.5-B7): the count at the level you'd play
        (needed anyway) and whether anything is above it. With themes chosen that's one scan
        (`count_level_and_above`); with All themes, a count plus an existence check above, which finds a
        row at once. The exact next open level is looked up only when the window says you move up."""
        key = ladder_key(spec)
        window, threshold = self._prefs.ladder_window(), self._prefs.ladder_threshold()
        recorded, recent = self._attempts.ladder_history(key, window)
        start = recorded if recorded in LEVELS else LEVELS[0]
        order = [lv for lv in LEVELS if lv >= start] + [lv for lv in reversed(LEVELS) if lv < start]
        current, n, above = None, 0, None
        for lv in order:  # the recorded level, or the nearest open one above it, else below
            if spec.themes:
                n, above_n = self._puzzles.count_level_and_above(spec, lv)
                above = above_n > 0
            else:
                n = self._puzzles.count(spec.at_ladder_level(lv))
            if n > 0:
                current = lv
                break
        if current is None:
            return ladder_status(key, None, [], threshold, window, []), [], 0
        higher = [lv for lv in LEVELS if lv > current]
        if higher and self._promotes(current, recorded, list(recent), window, threshold):
            available = [current, *self._puzzles.levels_with_puzzles(spec, higher)]
        elif higher and (
            above
            if above is not None
            else self._puzzles.has_puzzles(dataclasses.replace(spec, lengths=tuple(higher), order="random"))
        ):
            available = [current, higher[0]]  # something above: not the top (which level only matters on a move up)
        else:
            available = [current]
        st = ladder_status(key, recorded, recent, threshold, window, available)
        if st.level != current:
            n = self._puzzles.count(spec.at_ladder_level(st.level))
        return st, available, n

    def ladder_status(self, spec: FilterSpec) -> LadderStatus:
        return self.ladder_preview(spec)[0]

    def _after_ladder_attempt(self, s: _Session) -> LadderStatus | None:
        """Re-read the ladder after an attempt; on a level-up, draw from the new level from now on. Without a
        move up this costs no puzzle query (the open levels are known from the session's start)."""
        if s.ladder_base is None or s.ladder is None:
            return None
        window, threshold = self._prefs.ladder_window(), self._prefs.ladder_threshold()
        recorded, recent = self._attempts.ladder_history(s.ladder.key, window)
        if self._promotes(s.ladder.level, recorded, list(recent), window, threshold):
            new, s.ladder_levels, _ = self.ladder_preview(s.ladder_base)
        else:
            new = ladder_status(s.ladder.key, recorded, recent, threshold, window, s.ladder_levels)
        moved = new.level > s.ladder.level
        s.ladder = new
        if not moved:
            return None
        s.spec = s.ladder_base.at_ladder_level(new.level)
        s.queue.clear()
        s.match_count = self._puzzles.count(s.spec)
        log.info("session %d: the depth ladder moved up to %d moves", s.id, new.level)
        return new

    def _session(self, session_id: int) -> _Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise NotFoundError("That session has ended. Start a new one.")
        return s

    def _record(self, s: _Session, result: AttemptResult, commit: CommitResult | None = None) -> Outcome:
        assert s.current is not None
        p = s.current.state.puzzle
        state = s.current.state
        sync_fields = None
        local_only = s.mode == DANGER  # FR-4.4: Danger spotting stays on this PC
        if not local_only and self._sync is not None and self._queue_fields is not None and p.ref.source == "lichess":
            q = self._sync.fields_for(p.ref.id)
            # Spaced repetition ignores the filters: nothing was chosen in advance, so `mix` (§8.3).
            angle = MIX if s.mode == SRS_MODE else angle_for(s.spec, p.themes, p.length, length_known=s.show_length)
            sync_fields = self._queue_fields(status="pending", rated=s.rated, angle=angle,
                                             account=q.account, already_played=q.already_played)  # fmt: skip
        idea = self._name.score(state) if isinstance(state, NameIdeaState) else None
        danger = state if isinstance(state, DangerState) else None
        extra = self._mode_fields(
            replies_correct=commit.replies_correct if commit else None,
            replies_total=commit.replies_total if commit else None,
            ladder_key=s.ladder.key if s.ladder else None,
            ladder_level=s.ladder.level if s.ladder else None,
            idea_tags=state.tags.to_json() if isinstance(state, NameIdeaState) and state.tags else None,
            idea_found=idea.found if idea and idea.total else None,
            idea_total=idea.total if idea else None,
            idea_extra=idea.extra if idea and idea.total else None,
            danger_candidate=danger.candidate if danger else None,
            danger_safe=danger.is_safe if danger else None,
            danger_call=danger.call if danger else None,
        )
        aid = self._attempts.append(p.ref, s.id, s.mode, s.current.started_at,
                                    self._clock.now().isoformat(timespec="seconds"), result,
                                    p.rating if p.ref.source == "lichess" else None, sync_fields, extra)  # fmt: skip
        info = None
        if sync_fields is not None and self._sync is not None:
            found = self._sync.attempt_ratings([aid])
            info = found[0] if found else None
            self._sync.recorded()
        if not result.win:
            s.current.reason = self._reason_base(s, aid, result, commit, idea)
        level_up = self._after_ladder_attempt(s)
        return Outcome(result.win, p.ref.id, list(p.themes), list(p.moves[1:]), p.rating, aid, info, level_up,
                       idea, self._reveal(danger) if danger else None)  # fmt: skip

    @staticmethod
    def _reveal(state: DangerState) -> DangerReveal:
        info = state.safe_info if isinstance(state.safe_info, SafeInfo) else None
        if state.is_safe:
            return DangerReveal(state.candidate, True, state.call, info.best_score if info else None,
                                info.candidate_score if info else None, info.line if info else ())  # fmt: skip
        return DangerReveal(state.candidate, False, state.call, None, None, tuple(state.puzzle.moves[1:]))

    def _reason_base(
        self, s: _Session, aid: int, result: AttemptResult, commit: CommitResult | None, idea: IdeaScore | None
    ) -> _ReasonBase:
        assert s.current is not None
        state = s.current.state
        if isinstance(state, DangerState):
            return _ReasonBase(aid, "danger", state.decisive_ms, False, None, None, None,
                               state.call == "safe" and not state.is_safe)  # fmt: skip
        # Decided by Submit (Commit the line): the think time is the whole entry, from when the opponent's
        # first move had played (v0.6-B4).
        if commit is not None:
            decisive: int | None = max(0, result.time_ms - OPPONENT_DELAY_MS)
        else:
            decisive = state.decisive_ms if isinstance(state, StandardState) else None
        return _ReasonBase(
            attempt_id=aid,
            source="puzzle",
            decisive_ms=decisive,
            first_right_later_wrong=result.first_move_correct and result.help_used == "none",
            first_wrong=state.first_wrong,
            idea_found=idea.found if idea else None,
            idea_total=idea.total if idea else None,
            called_blunder_safe=False,
        )

    def next_puzzle(self, session_id: int) -> PuzzleView | None:
        """The next puzzle, or None when the session is complete. Moving on from an undecided
        puzzle records it as a loss."""
        s = self._session(session_id)
        with s.lock:
            if s.current is not None:
                result = self._mode_for(s).give_up(s.current.state, self._clock.monotonic_ms())
                if result is not None and not s.current.state.practice:
                    self._record(s, result)
                s.current = None
            self._follow_reimport(s)
            for _ in range(MAX_BAD_PUZZLES):
                if s.spec.queue_size is not None and s.served >= s.spec.queue_size:
                    return None
                if s.mode == SRS_MODE:
                    key_or_none = self._next_srs_key(s)
                    if key_or_none is None:
                        s.exhausted = True
                        return None
                    key = key_or_none
                else:
                    if not s.queue:
                        self._refill(s)
                    if not s.queue:
                        s.exhausted = True
                        return None
                    key = s.queue.popleft()
                try:
                    puzzle = self._puzzles.get(key, s.db_version)
                except StaleKeyError:  # the database was swapped after the check above (v0.2-B3)
                    self._follow_reimport(s)
                    continue
                if puzzle is None:  # dropped by a re-import (FR-2.4): skip it
                    continue
                try:
                    state = self._start_state(s, puzzle)
                except PuzzleDataError:
                    log.warning("skipping puzzle %s: its moves aren't legal", puzzle.ref)
                    continue
                s.served += 1
                s.served_ids.append(puzzle.ref.id if puzzle.ref.source == "lichess" else str(puzzle.ref))
                s.current = _Current(state, self._clock.now().isoformat(timespec="seconds"))
                if isinstance(state, DangerState):
                    # The raw position, from the side about to move; the blunder itself never reaches
                    # the front end before the end (FR-4.4).
                    return PuzzleView(s.served, puzzle.ref.id, puzzle.fen, "",
                                      "white" if state.board.turn else "black", puzzle.rating, None, False, s.mode,
                                      candidate=state.candidate)  # fmt: skip
                lichess = puzzle.ref.source == "lichess"
                played = self._sync.played_before(puzzle.ref.id) if self._sync is not None and lichess else False
                commit = isinstance(state, CommitState)
                sound = sounds_for_line(puzzle.fen, puzzle.moves[:1])[0] if puzzle.has_premove else None
                return PuzzleView(s.served, puzzle.ref.id, puzzle.fen, puzzle.moves[0],
                                  "white" if state.board.turn else "black", puzzle.rating, sound, played,
                                  s.mode, len(puzzle.moves) - 1 if commit and s.show_length else None,
                                  max_plies(puzzle, s.show_length) if commit else None,
                                  source=puzzle.ref.source,
                                  strict_without_engine=puzzle.tolerance and (self._engine is None or
                                                        self._engine.status().state != "ready"))  # fmt: skip
            raise ValidationError("Too many unreadable puzzles in a row. Try re-importing the puzzle database.")

    def _start_state(self, s: _Session, puzzle: Puzzle, practice: bool = False, prev: State | None = None) -> State:
        now = self._clock.monotonic_ms()
        if s.mode == DANGER:
            if practice and isinstance(prev, DangerState):
                state = self._danger.start_practice(puzzle, now, prev.candidate, prev.is_safe)
                state.safe_info = prev.safe_info
                return state
            candidate, is_safe, info = self._danger_candidate(s, puzzle)
            state = self._danger.start(puzzle, self._clock.monotonic_ms(), candidate, is_safe)
            state.safe_info = info
            return state
        if s.mode == NAME:
            return self._name.start_practice(puzzle, now) if practice else self._name.start(puzzle, now)
        if s.mode == COMMIT:
            if practice:
                return self._commit.start_practice(puzzle, now, s.show_length)
            return self._commit.start(puzzle, now, s.show_length)
        return self._standard.start_practice(puzzle, now) if practice else self._standard.start(puzzle, now)

    def _danger_candidate(self, s: _Session, puzzle: Puzzle) -> tuple[str, bool, SafeInfo | None]:
        """FR-4.4: about half the candidates are a Stockfish-verified safe move. The interactive engine
        (ARCHITECTURE §3 decision 12) looks at the raw position from the blunderer's side; a puzzle with
        no safe move shows the blunder and owes the next one a safe candidate."""
        blunder = puzzle.moves[0]
        engine = self._require_engine()
        board = validate_fen(puzzle.fen)  # FR-7.6: validated before the engine sees it
        mover: Any = "white" if board.turn == chess.WHITE else "black"
        # The search runs for every puzzle, safe slot or not, so how long a puzzle takes to appear says
        # nothing about the answer (v0.6-B1).
        analysis: Analysis | None
        try:
            analysis = engine.analyse(board, mover, multipv=DANGER_MULTIPV)
        except EngineNotInstalled:
            raise
        except AppError as e:  # the engine failed once: show the blunder and owe a safe one
            log.warning("danger spotting: no engine answer for %s (%s)", puzzle.ref, e.message)
            analysis = None
        with self._rng_lock:
            want = wants_safe(self._rng, s.owed_safe)
        if not want:
            return blunder, False, None
        if analysis is None:
            s.owed_safe = True
            return blunder, False, None
        lines = {line.pv[0]: line for line in analysis.lines if line.pv}
        scored = [ScoredMove(m, line.cp, line.mate) for m, line in lines.items()]
        with self._rng_lock:
            pick = pick_safe(self._rng, safe_candidates(scored, blunder))
        if pick is None:
            s.owed_safe = True
            return blunder, False, None
        s.owed_safe = False
        best, chosen = analysis.lines[0], lines[pick.move]
        return pick.move, True, SafeInfo(best.score, chosen.score, tuple(chosen.pv[1:]))

    def _next_srs_key(self, s: _Session) -> int | None:
        """The next due puzzle still in the database (a re-import may have dropped some, FR-2.4)."""
        while s.srs_ids:
            pid = s.srs_ids.popleft()
            key = self._puzzles.key_map([pid]).get(pid)
            if key is not None:
                return key
        return None

    def _follow_reimport(self, s: _Session) -> None:
        """A puzzle-DB update was swapped in mid-session: queued keys now point at other puzzles.
        Drop them, re-find the puzzles already served by ID (so none repeats), and re-count."""
        version = self._puzzles.version()
        if version == s.db_version:
            return
        log.info("session %d: the puzzle database changed; rebuilding its queue", s.id)
        s.db_version = version
        if s.mode == SRS_MODE:
            return  # its queue is puzzle IDs, looked up as they're served
        s.queue.clear()
        # Your own puzzles' keys (negative) never change, so they're kept as they are.
        s.served_keys = self._puzzles.keys_for_ids(s.served_ids) | {k for k in s.served_keys if k < 0}
        s.key_bucket.clear()
        if s.buckets:
            s.match_count, s.bucket_counts = self._puzzles.count_with_buckets(s.spec)
            s.weights = [r.weight if n > 0 else 0 for r, n in zip(s.spec.ratios, s.bucket_counts, strict=True)]
        else:
            s.match_count = self._puzzles.count(s.spec)

    def _refill(self, s: _Session) -> None:
        if s.spec.order != "random" and s.spec.queue_size is not None:
            # A fixed queue in a chosen order is drawn whole, so the order covers all of it.
            n = max(0, s.spec.queue_size - s.served - len(s.queue))
        else:
            n = refill_size(s.spec.queue_size, s.served, len(s.queue))
        if n <= 0:
            return
        with self._rng_lock:
            exclude = s.served_keys | set(s.queue)
            if s.buckets:
                keys = self._sample_ratio(s, n, exclude)
            else:
                keys = self._puzzles.sample_keys(s.spec, n, self._rng, exclude, s.match_count)
        keys = self._order(s, keys)
        s.served_keys.update(keys)
        s.queue.extend(keys)

    def _sample_ratio(self, s: _Session, n: int, exclude: set[int]) -> list[int]:
        """`n` keys split across the ratio buckets by quota (FR-3.10). A bucket that runs dry gets
        weight 0, and its slots go to the others in the next round."""
        chosen: list[int] = []
        while len(chosen) < n and any(s.weights):
            slots = allocate(s.weights, s.drawn, n - len(chosen), self._rng)
            got: dict[int, deque[int]] = {}
            for b in sorted(set(slots)):
                need = slots.count(b)
                keys = self._puzzles.sample_keys(s.buckets[b], need, self._rng, exclude, s.bucket_counts[b])
                exclude.update(keys)
                s.drawn[b] += len(keys)
                if len(keys) < need:
                    s.weights[b] = 0  # this group has no more puzzles
                got[b] = deque(keys)
            for b in slots:  # keep the shuffled slot order, so the groups are interleaved
                if got[b]:
                    key = got[b].popleft()
                    s.key_bucket[key] = b
                    chosen.append(key)
        return chosen

    def _order(self, s: _Session, keys: list[int]) -> list[int]:
        """FR-3.11. Random keeps the sampled order. Easy → hard and grouped-by-theme sort what was
        drawn: the whole queue when its size is fixed, each refill of 50 when it's endless."""
        if s.spec.order == "random" or len(keys) < 2 or s.spec.source != "lichess":
            return keys
        info = self._puzzles.describe(keys)
        if s.spec.order == "easy_to_hard":
            return order_easy_to_hard(keys, {k: v[0] for k, v in info.items()})
        if s.buckets:
            by_bucket = {k: str(s.key_bucket.get(k, "")) for k in keys}
            return order_by_theme(keys, by_bucket, [str(i) for i in range(len(s.buckets))])
        by_theme = {k: theme_group(v[1], s.spec.themes) for k, v in info.items()}
        return order_by_theme(keys, by_theme, s.spec.themes)

    def submit_move(self, session_id: int, uci: str) -> MoveResult:
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            state = s.current.state
            if isinstance(state, StandardState) and state.puzzle.tolerance and not state.finished:
                self._tolerate(state, uci)
            feedback = self._mode_for(s).on_move(s.current.state, uci, self._clock.monotonic_ms())
            practice = s.current.state.practice  # Try again: never recorded (FR-5.12)
            outcome = self._record(s, feedback.attempt) if feedback.attempt and not practice else None
            return MoveResult(feedback, outcome)

    def _tolerate(self, state: StandardState, uci: str) -> None:
        """FR-10.43 (built in v0.8 for puzzles saved from your games): a move off the stored line counts
        when the interactive engine rates it within the tolerance of the best move. The line then
        continues from your move with the engine's best play, so the mode sees the expected move.
        Without Stockfish (or when it fails), the stored line is checked as it is."""
        board = state.board
        move = parse_move(board, uci)
        if move is None or state.next_index >= len(state.puzzle.moves):
            return
        expected = chess.Move.from_uci(state.puzzle.moves[state.next_index])
        if is_acceptable(board, move, expected) or self._engine is None or self._engine.status().state != "ready":
            return
        player: Color = "white" if board.turn == chess.WHITE else "black"
        after = board.copy()
        after.push(move)
        continuation: tuple[str, ...] = ()
        try:
            before = self._engine.analyse(board, player)
            if not before.lines:
                return
            best = Score(before.lines[0].cp, before.lines[0].mate)
            if after.is_checkmate():
                played = Score(None, 0)
            else:
                same = [ln for ln in before.lines if ln.pv and ln.pv[0] == move.uci()]
                if same:
                    played, continuation = Score(same[0].cp, same[0].mate), tuple(same[0].pv[1:])
                else:
                    a = self._engine.analyse(after, player)
                    if not a.lines:  # stalemate or a draw by rule
                        played = Score(0, None)
                    else:
                        played, continuation = Score(a.lines[0].cp, a.lines[0].mate), tuple(a.lines[0].pv)
        except AppError as e:
            log.warning("tolerance check failed (%s): checking the stored line", e.message)
            return
        if not within_tolerance(best, played, self._tolerance_cp()):
            return
        remaining = len(state.puzzle.moves) - state.next_index
        tail = [move.uci()] if after.is_checkmate() else [move.uci(), *continuation[: remaining - 1]]
        if len(tail) % 2 == 0:
            tail = tail[:-1]  # end on your move
        state.puzzle = dataclasses.replace(state.puzzle, moves=(*state.puzzle.moves[: state.next_index], *tail))

    def submit_line(self, session_id: int, moves: Any) -> CommitOutcome:
        """Commit the line (FR-4.2): grade the whole submitted line. Recorded once, if it decided the attempt."""
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            state = s.current.state
            if not isinstance(state, CommitState):
                raise ConflictError("Submit is for Commit the line: in this mode, play your moves on the board.")
            result = self._commit.on_submit(state, moves, self._clock.monotonic_ms())
            outcome = None
            if result.attempt and not state.practice:
                outcome = self._record(s, result.attempt, result)
            return CommitOutcome(result, outcome)

    def set_idea_tags(self, session_id: int, setup: Any, payoff: Any) -> IdeaTags:
        """Name the idea first (FR-4.3): your tags, before your first move."""
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            state = s.current.state
            if not isinstance(state, NameIdeaState):
                raise ConflictError("Tagging the idea is for Name the idea first.")
            return self._name.set_tags(state, setup, payoff, self._clock.monotonic_ms())

    def call_danger(self, session_id: int, call: Any) -> DangerOutcome:
        """Danger spotting (FR-4.4): Safe or Unsafe."""
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            state = s.current.state
            if not isinstance(state, DangerState):
                raise ConflictError("Safe / Unsafe is for Danger spotting.")
            result = self._danger.on_call(state, call, self._clock.monotonic_ms())
            outcome = self._record(s, result.attempt) if result.attempt and not state.practice else None
            return DangerOutcome(result, outcome)

    # ---- mistake reasons (§7.3) -----------------------------------------------------------------------

    def reason_prompt(self, session_id: int) -> ReasonPrompt | None:
        """Ask why you missed the puzzle: once it's over, after a recorded loss, unless the setting is Off
        (FR-5.7, 5.8). The suggestion (FR-5.9) uses Stockfish's refutation when the engine is installed."""
        if self._prefs.reasons_ask() != "always":  # "game_review" asks only in Game Review (v0.8)
            return None
        s = self._session(session_id)
        with s.lock:
            cur = s.current
            if cur is None or cur.reason is None or not cur.state.finished:
                return None
            base = cur.reason
            refutation = cur.refutation
        if base.first_wrong is not None and refutation is None and self._engine is not None:
            try:
                refutation = self.get_refutation(session_id)
            except AppError as e:  # no engine, or it failed: no refutation-based suggestion
                log.info("reason prompt without a refutation: %s", e.code)
        forcing = mates = False
        if refutation is not None and refutation.line and base.first_wrong is not None:
            board = chess.Board(base.first_wrong[0])
            board.push_uci(base.first_wrong[1])
            forcing = is_forcing_reply(board.fen(), refutation.line[0])
            mates = refutation.mate is not None and refutation.mate < 0
        suggested = suggest(
            ReasonContext(
                decisive_ms=base.decisive_ms,
                rushed_ms=self._prefs.rushed_s() * 1000,
                first_right_later_wrong=base.first_right_later_wrong,
                reply_forcing=forcing,
                reply_mates=mates,
                idea_found=base.idea_found,
                idea_total=base.idea_total,
                called_blunder_safe=base.called_blunder_safe,
            )
        )
        with s.lock:
            if s.current is cur:
                cur.suggested = suggested
        return ReasonPrompt(base.attempt_id, base.source, suggested)

    def suggestion_for(self, attempt_id: int) -> str | None:
        """The last suggestion shown for this attempt, if its puzzle is still the current one."""
        for s in list(self._sessions.values()):
            cur = s.current
            if cur is not None and cur.reason is not None and cur.reason.attempt_id == attempt_id:
                return cur.suggested
        return None

    def request_help(self, session_id: int, kind: HelpKind) -> HelpOutcome:
        """Hint or Show answer (§7.2). Before the attempt is decided it's recorded as a loss."""
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            result = self._mode_for(s).on_help(s.current.state, kind, self._clock.monotonic_ms())
            practice = s.current.state.practice
            outcome = self._record(s, result.attempt) if result.attempt and not practice else None
            return HelpOutcome(result, outcome)

    # ---- engine after the puzzle (FR-7.2, 7.3, 7.7) -------------------------------------------------

    def _finished(self, s: _Session) -> _Current:
        """FR-7.3: engine output only once the puzzle is over (line complete, or Show answer used).
        A puzzle lost to a wrong move that you're still playing through is still in progress."""
        if s.current is None:
            raise ValidationError("There's no puzzle in progress.")
        if not s.current.state.finished:
            raise ConflictError("The engine is available once the puzzle is over.")
        return s.current

    def _engine_or_raise(self) -> EngineService:
        if self._engine is None:
            raise EngineNotInstalled("Stockfish isn't installed.")
        return self._engine

    @staticmethod
    def _player(cur: _Current) -> Any:
        """Whose side evals are worded from (FR-7.2): the side you played. In Danger spotting that's the
        punishing side once you called the real blunder Unsafe and played on (v0.6-B5)."""
        state = cur.state
        mover = chess.Board(state.start_fen).turn
        if isinstance(state, DangerState) and state.call == "unsafe" and not state.is_safe:
            mover = not mover
        return "white" if mover == chess.WHITE else "black"

    def get_refutation(self, session_id: int) -> Refutation:
        """The engine's answer to the move that lost this puzzle (Show answer, §7.2 step 2)."""
        s = self._session(session_id)
        with s.lock:
            cur = self._finished(s)
            if cur.refutation is not None:
                return cur.refutation
            wrong = cur.state.first_wrong
            player = self._player(cur)
            running = cur.refuting
            if running is None and wrong is not None:
                cur.refuting = threading.Event()
        if wrong is None:
            raise NotFoundError("There's no wrong move to refute in this puzzle.")
        if running is not None:  # another caller is searching it: wait for that answer (v0.6-B3)
            running.wait(60)
            with s.lock:
                if cur.refutation is not None:
                    return cur.refutation
            raise EngineError("Stockfish didn't answer. Try again.")
        try:
            return self._search_refutation(s, cur, wrong, player)
        finally:
            with s.lock:
                done, cur.refuting = cur.refuting, None
            if done is not None:
                done.set()

    def _search_refutation(self, s: _Session, cur: _Current, wrong: tuple[str, str], player: Any) -> Refutation:
        fen_before, uci = wrong
        board = validate_line(fen_before, [uci])  # FR-7.6: validated before the engine sees it
        engine = self._engine_or_raise()
        analysis = engine.analyse(board, player, multipv=1)
        if analysis.lines:
            first = analysis.lines[0]
            line = self._extend_refutation(engine, board, player, refutation_plies(first.pv))
            result = Refutation(fen_before, uci, line, first.score, mate=first.mate)
        else:
            result = Refutation(fen_before, uci, (), None, analysis.game_over)
        with s.lock:
            if s.current is cur:
                cur.refutation = result
        return result

    @staticmethod
    def _extend_refutation(
        engine: EngineService, board: chess.Board, player: Any, line: tuple[str, ...]
    ) -> tuple[str, ...]:
        """§7.2: the reply line is 3–5 plies unless the game ends sooner. Stockfish sometimes stops its pv
        at 2 (v0.4-B2), so ask again from where it stopped, at most twice."""
        for _ in range(2):
            if len(line) >= REFUTATION_MIN_PLIES:
                break
            end = board.copy()
            for uci in line:
                end.push_uci(uci)
            if end.is_game_over():
                break
            more = engine.analyse(end, player, multipv=1)
            if not more.lines or not more.lines[0].pv:
                break
            line = refutation_plies(line + more.lines[0].pv)
        return line

    def analyze(self, session_id: int, fen: Any, purpose: Any = "panel") -> Analysis:
        """Eval and top lines for a position, only after the puzzle is over (FR-7.3, FR-7.7). The
        analysis board sends any legal position; it's validated here first (FR-7.6)."""
        if purpose not in PURPOSES:
            raise ValidationError("Unknown analysis purpose.")
        board = validate_fen(fen)
        s = self._session(session_id)
        with s.lock:
            cur = self._finished(s)
            cached = cur.analyses.get(board.fen())
            player = self._player(cur)
        if cached is not None:
            return cached
        engine = self._engine_or_raise()
        key = (session_id, purpose)
        result = engine.analyse(board, player, key=key, gen=engine.ticket(key))
        if not result.superseded:
            with s.lock:
                if s.current is cur:
                    cur.analyses[board.fen()] = result
        return result

    # ---- Explain (v0.7, FR-8.2): the grounded facts for the puzzle that just ended -------------------

    def explain_facts(self, session_id: int, with_engine: bool = True) -> tuple[ExplainInput, CacheKeyParts]:
        """The allowlisted facts for Explain and its cache key. Only once the puzzle is over (FR-7.3), and
        only with Stockfish (Adam, v0.7 planning). `with_engine=False` skips the searches: the quote only
        needs the prompt's size."""
        s = self._session(session_id)
        with s.lock:
            cur = self._finished(s)
            state = cur.state
            puzzle = state.puzzle
        engine = self._engine_or_raise()
        if engine.status().state != "ready":
            raise EngineNotInstalled("Explain needs Stockfish. Install it first.")
        themes = tuple(display_name(t) for t in puzzle.themes)
        danger = None
        entered: tuple[str, ...] | None = None
        path: tuple[str, ...] = (s.mode,)
        if isinstance(state, DangerState):
            danger = DangerFact(state.candidate, state.is_safe, state.call)
            path += ("call", state.call or "none")
        elif isinstance(state, CommitState):
            entered = tuple(state.played)
            path += ("line", *entered)
        if state.first_wrong is not None:
            path += ("wrong", state.first_wrong[1])
        attempt = state.attempt
        solved = state.first_wrong is None and not state.hinted and bool((attempt and attempt.win) or state.practice)
        lines: tuple[EngineLineFact, ...] = ()
        refutation = None
        if with_engine:
            board, _ = start_position(puzzle.fen, puzzle.moves)
            you: Color = "white" if board.turn == chess.WHITE else "black"  # the solving side, also in Danger spotting
            analysis = engine.analyse(board, you)
            lines = tuple(EngineLineFact(x.score, x.pv) for x in analysis.lines)
            if state.first_wrong is not None:
                r = self.get_refutation(session_id)
                refutation = RefutationFact(r.fen_before, r.wrong_move, r.line, r.score)
        inp = ExplainInput(puzzle.fen, puzzle.moves, themes, lines, refutation, entered, solved, danger)
        return inp, CacheKeyParts(str(puzzle.ref), path)

    def current_puzzle(self, session_id: int) -> str | None:
        """The puzzle on the board (as text), so a late Explain result can't land on the next puzzle."""
        s = self._session(session_id)
        with s.lock:
            return str(s.current.state.puzzle.ref) if s.current else None

    def retry(self, session_id: int) -> None:
        """FR-5.12 Try again (not scored): replay the current puzzle from its start, once it's over.
        The recorded attempt is untouched and nothing is queued for Lichess."""
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            if not s.current.state.finished:
                raise ConflictError("Finish the puzzle first: Try again is for after it's over.")
            puzzle = s.current.state.puzzle
            s.current = _Current(
                self._start_state(s, puzzle, practice=True, prev=s.current.state),
                s.current.started_at,
                analyses=s.current.analyses,  # same positions: the engine's answers still hold
                refutation=s.current.refutation,
                reason=s.current.reason,  # the reason chips stay until you move on (FR-5.8)
                suggested=s.current.suggested,
            )

    def stats(self, session_id: int) -> SessionStats:
        s = self._session(session_id)
        t = self._attempts.session_tally(session_id)
        a = self._attempts.all_time_tally()
        solved, failed = t.solved, t.failed  # type: ignore[attr-defined]
        played = solved + failed
        finished = s.exhausted or (s.spec.queue_size is not None and played >= s.spec.queue_size)
        return SessionStats(
            solved=solved,
            failed=failed,
            accuracy=solved / played if played else None,
            played=played,
            queue_size=s.spec.queue_size,
            finished=finished,
            all_time_solved=a.solved,  # type: ignore[attr-defined]
            all_time_failed=a.failed,  # type: ignore[attr-defined]
            rating_change=self._sync.session_change(session_id) if self._sync is not None else None,
            mode=s.mode,
            ladder=s.ladder,
            misclicks=getattr(t, "misclicks", 0),
        )
