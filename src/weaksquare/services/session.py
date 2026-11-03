"""Training sessions: queue, puzzles, moves and attempts (FR-3.10–3.12, 3.14, FR-4.1, FR-5.1, 5.3, 5.5).

v0.5: the training mode is chosen per session (§6): Standard, Commit the line (FR-4.2) or Spaced
repetition (FR-4.6, a queue of due puzzles played with Standard's rules). The depth ladder (FR-4.5) is
an order: the session draws from the current level and moves up when the window says so.

Session state (queue, current puzzle, mode state) is kept in memory; every decided attempt is
appended to `attempts` at once, so closing the app never loses a result.
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import chess

from weaksquare.core.chess_rules import PuzzleDataError
from weaksquare.core.clock import Clock
from weaksquare.core.engine import (
    REFUTATION_MIN_PLIES,
    EngineNotInstalled,
    refutation_plies,
    validate_fen,
    validate_line,
)
from weaksquare.core.errors import ConflictError, NotFoundError, StaleKeyError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.ladder import DEFAULT_THRESHOLD, DEFAULT_WINDOW, LadderStatus, ladder_key
from weaksquare.core.ladder import status as ladder_status
from weaksquare.core.modes.base import AttemptResult, Feedback, HelpKind, HelpResult
from weaksquare.core.modes.commit_line import CommitLineMode, CommitResult, CommitState, max_plies
from weaksquare.core.modes.standard import StandardMode, StandardState
from weaksquare.core.move_sounds import MoveSound, sounds_for_line
from weaksquare.core.puzzle import Puzzle, PuzzleRef
from weaksquare.core.queue import allocate, order_by_theme, order_easy_to_hard, refill_size, theme_group
from weaksquare.core.scoring import MIX, angle_for
from weaksquare.core.srs import DEFAULT_INTERVALS, Card, Review, due_order, next_due, schedule
from weaksquare.core.srs import MODE as SRS_MODE
from weaksquare.services.engine import Analysis, EngineService

log = logging.getLogger(__name__)

MAX_BAD_PUZZLES = 20
STANDARD, COMMIT = "standard", "commit_line"
MODES = (STANDARD, COMMIT, SRS_MODE)  # the Modes control, in order (v0.5)
State = StandardState | CommitState


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


class _DefaultPrefs:
    def srs_intervals(self) -> tuple[int, ...]:
        return DEFAULT_INTERVALS

    def ladder_threshold(self) -> int:
        return DEFAULT_THRESHOLD

    def ladder_window(self) -> int:
        return DEFAULT_WINDOW


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


AnalysisPurpose = Literal["start", "panel", "board"]
PURPOSES = ("start", "panel", "board")


@dataclass
class _Current:
    state: State
    started_at: str
    refutation: Refutation | None = None
    analyses: dict[str, Analysis] = field(default_factory=dict)  # by FEN, for this puzzle


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
    level_up: bool = False  # the last recorded attempt moved the ladder up (reported once)


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
    opponent_sound: MoveSound  # FR-1.13: the opponent's first move plays a sound too
    already_played: bool = False  # Lichess has seen it from you: rating unaffected (badge)
    mode: str = STANDARD
    solution_plies: int | None = None  # Commit the line with Show move count only: how many moves to enter
    max_plies: int | None = None  # Commit the line: the longest line Submit accepts


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
        self._standard = StandardMode()
        self._commit = CommitLineMode()
        self._sessions: dict[int, _Session] = {}

    def _mode_for(self, s: _Session) -> Any:
        return self._commit if s.mode == COMMIT else self._standard  # SRS plays by Standard's rules

    def start(
        self, spec: FilterSpec, rated: bool = True, mode: str = STANDARD, show_length: bool = False
    ) -> SessionInfo:
        if mode not in MODES:
            raise ValidationError("Unknown training mode.")
        if mode == SRS_MODE:
            return self._start_srs(spec, rated)
        ladder = None
        base = None
        if spec.depth_ladder:
            base = spec
            ladder = self.ladder_status(spec)
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
                           show_length=show_length and mode == COMMIT, ladder_base=base, ladder=ladder)  # fmt: skip
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

    def ladder_status(self, spec: FilterSpec) -> LadderStatus:
        key = ladder_key(spec)
        window, threshold = self._prefs.ladder_window(), self._prefs.ladder_threshold()
        level, recent = self._attempts.ladder_history(key, window)
        return ladder_status(key, level, recent, threshold, window)

    def pool_spec(self, spec: FilterSpec) -> FilterSpec:
        """What a session would draw from: the current ladder level's pool for a depth-ladder order."""
        return spec.at_ladder_level(self.ladder_status(spec).level) if spec.depth_ladder else spec

    def _after_ladder_attempt(self, s: _Session) -> LadderStatus | None:
        """Re-read the ladder after an attempt; on a level-up, draw from the new level from now on."""
        if s.ladder_base is None or s.ladder is None:
            return None
        new = self.ladder_status(s.ladder_base)
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
        sync_fields = None
        if self._sync is not None and self._queue_fields is not None and p.ref.source == "lichess":
            q = self._sync.fields_for(p.ref.id)
            # Spaced repetition ignores the filters: nothing was chosen in advance, so `mix` (§8.3).
            angle = MIX if s.mode == SRS_MODE else angle_for(s.spec, p.themes, p.length, length_known=s.show_length)
            sync_fields = self._queue_fields(status="pending", rated=s.rated, angle=angle,
                                             account=q.account, already_played=q.already_played)  # fmt: skip
        extra = self._mode_fields(
            replies_correct=commit.replies_correct if commit else None,
            replies_total=commit.replies_total if commit else None,
            ladder_key=s.ladder.key if s.ladder else None,
            ladder_level=s.ladder.level if s.ladder else None,
        )
        aid = self._attempts.append(p.ref, s.id, s.mode, s.current.started_at,
                                    self._clock.now().isoformat(timespec="seconds"), result, p.rating,
                                    sync_fields, extra)  # fmt: skip
        info = None
        if sync_fields is not None and self._sync is not None:
            found = self._sync.attempt_ratings([aid])
            info = found[0] if found else None
            self._sync.recorded()
        level_up = self._after_ladder_attempt(s)
        return Outcome(result.win, p.ref.id, list(p.themes), list(p.moves[1:]), p.rating, aid, info, level_up)

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
                s.served_ids.append(puzzle.ref.id)
                s.current = _Current(state, self._clock.now().isoformat(timespec="seconds"))
                played = self._sync.played_before(puzzle.ref.id) if self._sync is not None else False
                commit = isinstance(state, CommitState)
                return PuzzleView(s.served, puzzle.ref.id, puzzle.fen, puzzle.moves[0],
                                  "white" if state.board.turn else "black", puzzle.rating,
                                  sounds_for_line(puzzle.fen, puzzle.moves[:1])[0], played, s.mode,
                                  len(puzzle.moves) - 1 if commit and s.show_length else None,
                                  max_plies(puzzle, s.show_length) if commit else None)  # fmt: skip
            raise ValidationError("Too many unreadable puzzles in a row. Try re-importing the puzzle database.")

    def _start_state(self, s: _Session, puzzle: Puzzle, practice: bool = False) -> State:
        now = self._clock.monotonic_ms()
        if s.mode == COMMIT:
            if practice:
                return self._commit.start_practice(puzzle, now, s.show_length)
            return self._commit.start(puzzle, now, s.show_length)
        return self._standard.start_practice(puzzle, now) if practice else self._standard.start(puzzle, now)

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
        s.served_keys = self._puzzles.keys_for_ids(s.served_ids)
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
        if s.spec.order == "random" or len(keys) < 2:
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
            feedback = self._mode_for(s).on_move(s.current.state, uci, self._clock.monotonic_ms())
            practice = s.current.state.practice  # Try again: never recorded (FR-5.12)
            outcome = self._record(s, feedback.attempt) if feedback.attempt and not practice else None
            return MoveResult(feedback, outcome)

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
        return "white" if chess.Board(cur.state.start_fen).turn == chess.WHITE else "black"

    def get_refutation(self, session_id: int) -> Refutation:
        """The engine's answer to the move that lost this puzzle (Show answer, §7.2 step 2)."""
        s = self._session(session_id)
        with s.lock:
            cur = self._finished(s)
            if cur.refutation is not None:
                return cur.refutation
            wrong = cur.state.first_wrong
            player = self._player(cur)
        if wrong is None:
            raise NotFoundError("There's no wrong move to refute in this puzzle.")
        fen_before, uci = wrong
        board = validate_line(fen_before, [uci])  # FR-7.6: validated before the engine sees it
        engine = self._engine_or_raise()
        analysis = engine.analyse(board, player, multipv=1)
        if analysis.lines:
            first = analysis.lines[0]
            line = self._extend_refutation(engine, board, player, refutation_plies(first.pv))
            result = Refutation(fen_before, uci, line, first.score)
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
                self._start_state(s, puzzle, practice=True),
                s.current.started_at,
                analyses=s.current.analyses,  # same positions: the engine's answers still hold
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
        )
