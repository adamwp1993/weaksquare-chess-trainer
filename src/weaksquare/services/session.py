"""Training sessions: queue, puzzles, moves and attempts (FR-3.10–3.12, 3.14, FR-4.1, FR-5.1, 5.3, 5.5).

Session state (queue, current puzzle, mode state) is kept in memory; every decided attempt is
appended to `attempts` at once, so closing the app never loses a result.
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

from weaksquare.core.chess_rules import PuzzleDataError
from weaksquare.core.clock import Clock
from weaksquare.core.errors import NotFoundError, StaleKeyError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.modes.base import AttemptResult, Feedback, HelpKind, HelpResult
from weaksquare.core.modes.standard import StandardMode, StandardState
from weaksquare.core.move_sounds import MoveSound, sounds_for_line
from weaksquare.core.puzzle import Puzzle, PuzzleRef
from weaksquare.core.queue import allocate, order_by_theme, order_easy_to_hard, refill_size, theme_group
from weaksquare.core.scoring import angle_for

log = logging.getLogger(__name__)

MAX_BAD_PUZZLES = 20


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
    ) -> int: ...

    def session_tally(self, session_id: int) -> object: ...

    def all_time_tally(self) -> object: ...


class Sessions(Protocol):
    def create(self, started_at: str, mode: str, filters: dict, queue_size: int | None) -> int: ...


class SyncHooks(Protocol):
    """The Lichess sync queue, as the session sees it (v0.3; services/sync.py)."""

    def fields_for(self, puzzle_id: str) -> Any: ...  # QueueFields(account, already_played)

    def played_before(self, puzzle_id: str) -> bool: ...

    def recorded(self) -> None: ...

    def attempt_ratings(self, attempt_ids: list[int]) -> list: ...  # list[RatingInfo]

    def session_change(self, session_id: int) -> int | None: ...


@dataclass
class _Current:
    state: StandardState
    started_at: str


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


@dataclass(frozen=True)
class SessionInfo:
    session_id: int
    match_count: int
    queue_size: int | None
    empty_buckets: list[int] = field(default_factory=list)  # ratio groups with no puzzles: left out


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


@dataclass(frozen=True)
class Outcome:
    win: bool
    puzzle_id: str
    themes: list[str]
    solution: list[str]
    rating: int
    attempt_id: int = 0
    lichess: Any = None  # RatingInfo: the Lichess rating change, or why there isn't one (FR-6.11b)


@dataclass(frozen=True)
class MoveResult:
    feedback: Feedback
    outcome: Outcome | None


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
    ) -> None:
        """`sync` queues every decided attempt for Lichess (v0.3); without it attempts stay local.
        `queue_fields` builds the repo's SyncFields (passed in so services don't import adapters)."""
        self._sync = sync
        self._queue_fields = queue_fields
        self._puzzles = puzzles
        self._attempts = attempts
        self._sessions_repo = sessions
        self._clock = clock
        self._rng = rng
        self._rng_lock = threading.Lock()
        self._mode = StandardMode()
        self._sessions: dict[int, _Session] = {}

    def start(self, spec: FilterSpec, rated: bool = True) -> SessionInfo:
        buckets = [spec.bucket(i) for i in range(len(spec.ratios))]
        if buckets:
            count, bucket_counts = self._puzzles.count_with_buckets(spec)
        else:
            count, bucket_counts = self._puzzles.count(spec), []
        if count == 0:
            raise ValidationError("No puzzles match these filters. Widen them and try again.")
        sid = self._sessions_repo.create(self._clock.now().isoformat(timespec="seconds"), self._mode.name,
                                         spec.to_json(), spec.queue_size)  # fmt: skip
        session = _Session(sid, spec, count, self._puzzles.version(), rated)
        if buckets:
            # An empty group is left out and the others share its slots (renormalized).
            session.buckets = buckets
            session.bucket_counts = bucket_counts
            session.weights = [b.weight if n > 0 else 0 for b, n in zip(spec.ratios, bucket_counts, strict=True)]
            session.drawn = [0] * len(buckets)
        self._sessions[sid] = session
        return SessionInfo(sid, count, spec.queue_size, [i for i, n in enumerate(bucket_counts) if n == 0])

    def _session(self, session_id: int) -> _Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise NotFoundError("That session has ended. Start a new one.")
        return s

    def _record(self, s: _Session, result: AttemptResult) -> Outcome:
        assert s.current is not None
        p = s.current.state.puzzle
        sync_fields = None
        if self._sync is not None and self._queue_fields is not None and p.ref.source == "lichess":
            q = self._sync.fields_for(p.ref.id)
            sync_fields = self._queue_fields(status="pending", rated=s.rated,
                                             angle=angle_for(s.spec, p.themes, p.length),
                                             account=q.account, already_played=q.already_played)  # fmt: skip
        aid = self._attempts.append(p.ref, s.id, self._mode.name, s.current.started_at,
                                    self._clock.now().isoformat(timespec="seconds"), result, p.rating,
                                    sync_fields)  # fmt: skip
        info = None
        if sync_fields is not None and self._sync is not None:
            found = self._sync.attempt_ratings([aid])
            info = found[0] if found else None
            self._sync.recorded()
        return Outcome(result.win, p.ref.id, list(p.themes), list(p.moves[1:]), p.rating, aid, info)

    def next_puzzle(self, session_id: int) -> PuzzleView | None:
        """The next puzzle, or None when the session is complete. Moving on from an undecided
        puzzle records it as a loss."""
        s = self._session(session_id)
        with s.lock:
            if s.current is not None:
                result = self._mode.give_up(s.current.state, self._clock.monotonic_ms())
                if result is not None:
                    self._record(s, result)
                s.current = None
            self._follow_reimport(s)
            for _ in range(MAX_BAD_PUZZLES):
                if s.spec.queue_size is not None and s.served >= s.spec.queue_size:
                    return None
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
                    state = self._mode.start(puzzle, self._clock.monotonic_ms())
                except PuzzleDataError:
                    log.warning("skipping puzzle %s: its moves aren't legal", puzzle.ref)
                    continue
                s.served += 1
                s.served_ids.append(puzzle.ref.id)
                s.current = _Current(state, self._clock.now().isoformat(timespec="seconds"))
                played = self._sync.played_before(puzzle.ref.id) if self._sync is not None else False
                return PuzzleView(s.served, puzzle.ref.id, puzzle.fen, puzzle.moves[0],
                                  "white" if state.board.turn else "black", puzzle.rating,
                                  sounds_for_line(puzzle.fen, puzzle.moves[:1])[0], played)  # fmt: skip
            raise ValidationError("Too many unreadable puzzles in a row. Try re-importing the puzzle database.")

    def _follow_reimport(self, s: _Session) -> None:
        """A puzzle-DB update was swapped in mid-session: queued keys now point at other puzzles.
        Drop them, re-find the puzzles already served by ID (so none repeats), and re-count."""
        version = self._puzzles.version()
        if version == s.db_version:
            return
        log.info("session %d: the puzzle database changed; rebuilding its queue", s.id)
        s.db_version = version
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
            feedback = self._mode.on_move(s.current.state, uci, self._clock.monotonic_ms())
            outcome = self._record(s, feedback.attempt) if feedback.attempt else None
            return MoveResult(feedback, outcome)

    def request_help(self, session_id: int, kind: HelpKind) -> HelpOutcome:
        """Hint or Show answer (§7.2). Before the attempt is decided it's recorded as a loss."""
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            result = self._mode.on_help(s.current.state, kind, self._clock.monotonic_ms())
            outcome = self._record(s, result.attempt) if result.attempt else None
            return HelpOutcome(result, outcome)

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
        )
