"""Training sessions: queue, puzzles, moves and attempts (FR-3.11, 3.12, 3.14, FR-4.1, FR-5.1, 5.3, 5.5).

Session state (queue, current puzzle, mode state) is kept in memory; every decided attempt is
appended to `attempts` at once, so closing the app never loses a result.
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from weaksquare.core.chess_rules import PuzzleDataError
from weaksquare.core.clock import Clock
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.modes.base import AttemptResult, Feedback
from weaksquare.core.modes.standard import StandardMode, StandardState
from weaksquare.core.puzzle import Puzzle, PuzzleRef
from weaksquare.core.queue import refill_size

log = logging.getLogger(__name__)

MAX_BAD_PUZZLES = 20


class PuzzleSource(Protocol):
    def count(self, spec: FilterSpec) -> int: ...

    def sample_keys(
        self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int], match_count: int
    ) -> list[int]: ...

    def get(self, key: int) -> Puzzle | None: ...


class Attempts(Protocol):
    def append(
        self, ref: PuzzleRef, session_id: int, mode: str, started_at: str, finished_at: str, result: AttemptResult
    ) -> int: ...

    def session_tally(self, session_id: int) -> object: ...

    def all_time_tally(self) -> object: ...


class Sessions(Protocol):
    def create(self, started_at: str, mode: str, filters: dict, queue_size: int | None) -> int: ...


@dataclass
class _Current:
    state: StandardState
    started_at: str


@dataclass
class _Session:
    id: int
    spec: FilterSpec
    match_count: int
    queue: deque[int] = field(default_factory=deque)
    served_keys: set[int] = field(default_factory=set)
    served: int = 0
    current: _Current | None = None
    exhausted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class SessionInfo:
    session_id: int
    match_count: int
    queue_size: int | None


@dataclass(frozen=True)
class PuzzleView:
    """What the board needs. No themes: they're hidden until the attempt is decided (FR-3.14)."""

    number: int
    puzzle_id: str
    fen: str  # before the opponent's move
    opponent_move: str  # played (animated) first
    player_color: str
    rating: int


@dataclass(frozen=True)
class Outcome:
    win: bool
    puzzle_id: str
    themes: list[str]
    solution: list[str]
    rating: int


@dataclass(frozen=True)
class MoveResult:
    feedback: Feedback
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


class SessionService:
    def __init__(
        self, puzzles: PuzzleSource, attempts: Attempts, sessions: Sessions, clock: Clock, rng: random.Random
    ) -> None:
        self._puzzles = puzzles
        self._attempts = attempts
        self._sessions_repo = sessions
        self._clock = clock
        self._rng = rng
        self._rng_lock = threading.Lock()
        self._mode = StandardMode()
        self._sessions: dict[int, _Session] = {}

    def start(self, spec: FilterSpec) -> SessionInfo:
        count = self._puzzles.count(spec)
        if count == 0:
            raise ValidationError("No puzzles match these filters. Widen them and try again.")
        sid = self._sessions_repo.create(self._clock.now().isoformat(timespec="seconds"), self._mode.name,
                                         spec.to_json(), spec.queue_size)  # fmt: skip
        self._sessions[sid] = _Session(sid, spec, count)
        return SessionInfo(sid, count, spec.queue_size)

    def _session(self, session_id: int) -> _Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise NotFoundError("That session has ended. Start a new one.")
        return s

    def _record(self, s: _Session, result: AttemptResult) -> Outcome:
        assert s.current is not None
        p = s.current.state.puzzle
        self._attempts.append(p.ref, s.id, self._mode.name, s.current.started_at,
                              self._clock.now().isoformat(timespec="seconds"), result)  # fmt: skip
        return Outcome(result.win, p.ref.id, list(p.themes), list(p.moves[1:]), p.rating)

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
            for _ in range(MAX_BAD_PUZZLES):
                if s.spec.queue_size is not None and s.served >= s.spec.queue_size:
                    return None
                if not s.queue:
                    self._refill(s)
                if not s.queue:
                    s.exhausted = True
                    return None
                key = s.queue.popleft()
                puzzle = self._puzzles.get(key)
                if puzzle is None:  # dropped by a re-import (FR-2.4): skip it
                    continue
                try:
                    state = self._mode.start(puzzle, self._clock.monotonic_ms())
                except PuzzleDataError:
                    log.warning("skipping puzzle %s: its moves aren't legal", puzzle.ref)
                    continue
                s.served += 1
                s.current = _Current(state, self._clock.now().isoformat(timespec="seconds"))
                return PuzzleView(s.served, puzzle.ref.id, puzzle.fen, puzzle.moves[0],
                                  "white" if state.board.turn else "black", puzzle.rating)  # fmt: skip
            raise ValidationError("Too many unreadable puzzles in a row. Try re-importing the puzzle database.")

    def _refill(self, s: _Session) -> None:
        n = refill_size(s.spec.queue_size, s.served, len(s.queue))
        if n <= 0:
            return
        with self._rng_lock:
            keys = self._puzzles.sample_keys(s.spec, n, self._rng, s.served_keys | set(s.queue), s.match_count)
        s.served_keys.update(keys)
        s.queue.extend(keys)

    def submit_move(self, session_id: int, uci: str) -> MoveResult:
        s = self._session(session_id)
        with s.lock:
            if s.current is None:
                raise ValidationError("There's no puzzle in progress.")
            feedback = self._mode.on_move(s.current.state, uci, self._clock.monotonic_ms())
            outcome = self._record(s, feedback.attempt) if feedback.attempt else None
            return MoveResult(feedback, outcome)

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
        )
