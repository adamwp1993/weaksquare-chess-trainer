"""Game analysis (v0.8, REQUIREMENTS §11.2): every position of a game on the **background engine**, graded
by `core.game_review`, stored in `game_analysis`.

**The queue (FR-11.31):** games wait in a first-in, first-out queue drained by one `game_analysis` job
at a time (each engine search already uses several threads), with progress per game and per position,
and cancel. A game already analyzed at the same think time and engine is skipped, so it's never analyzed
twice at the same settings. Results are stored per game in one transaction.

Also here: the Review settings (think time, thresholds, the retry tolerance, the number of key moments),
which the Coach shares from v0.10.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import chess

from weaksquare.core.engine import EngineLine, EngineNotInstalled
from weaksquare.core.errors import ValidationError
from weaksquare.core.game_review import MoveRow, Thresholds, grade_game, regrade
from weaksquare.core.games import GameError, GameRow, low_clock, parse_single_pgn
from weaksquare.core.tagging import tag_game
from weaksquare.core.tolerance import DEFAULT_TOLERANCE_CP, validate_tolerance
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "game_analysis"
THINK_KEY = "review.think_s"
THRESHOLDS_KEY = "review.thresholds"
TOLERANCE_KEY = "review.tolerance_cp"
KEY_MOMENTS_KEY = "review.key_moments"
DEFAULT_THINK_S = 0.3
THINK_RANGE = (0.1, 5.0)
DEFAULT_KEY_MOMENTS = 5
KEY_MOMENTS_RANGE = (1, 10)
MULTIPV = 3


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class Games(Protocol):
    def get(self, game_id: int) -> GameRow | None: ...


class AnalysisStore(Protocol):
    def replace(self, game_id: int, rows: Sequence[MoveRow], status: str, think_s: float, engine: str) -> None: ...

    def rows(self, game_id: int) -> list[MoveRow]: ...

    def regrade(self, fn: Callable[[MoveRow], MoveRow]) -> int: ...

    def set_tags(self, game_id: int, tags: Sequence[tuple[int, Sequence[str], Sequence[str]]]) -> None: ...

    def analyzed_games(self) -> list[int]: ...


class BackgroundEngine(Protocol):
    def analyse_background(self, board: chess.Board, think_s: float, multipv: int = ...) -> list[EngineLine]: ...

    def engine_id(self) -> str: ...


@dataclass(frozen=True)
class ReviewSettings:
    think_s: float
    thresholds: Thresholds
    tolerance_cp: int
    key_moments: int


@dataclass(frozen=True)
class QueueStatus:
    job_id: str | None
    current: int | None  # the game being analyzed
    waiting: tuple[int, ...]


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


class AnalysisService:
    def __init__(
        self, games: Games, store: AnalysisStore, engine: BackgroundEngine, settings: Settings, runner: JobRunner
    ) -> None:
        self._games = games
        self._store = store
        self._engine = engine
        self._settings = settings
        self._runner = runner
        self._lock = threading.Lock()
        self._queue: deque[int] = deque()
        self._current: int | None = None
        self._job: str | None = None
        self._draining = False  # set under the lock: a game queued as the job exits starts a new one
        self._listeners: list[Callable[[int, ProgressFn, CancelToken], None]] = []

    def add_listener(self, fn: Callable[[int, ProgressFn, CancelToken], None]) -> None:
        """Called in the analysis job after each game is stored (v0.10: puzzles from your games)."""
        self._listeners.append(fn)

    def thresholds_decided(self) -> int:
        return self.settings().thresholds.decided

    # ------------------------------------------------------------ settings

    def settings(self) -> ReviewSettings:
        think = self._settings.get(THINK_KEY)
        th = self._settings.get(THRESHOLDS_KEY)
        tol = self._settings.get(TOLERANCE_KEY)
        km = self._settings.get(KEY_MOMENTS_KEY)
        thresholds = Thresholds()
        if isinstance(th, dict):
            try:
                candidate = Thresholds(
                    **{k: int(th[k]) for k in ("inaccuracy", "mistake", "blunder", "decided") if k in th}
                )
                candidate.validate()
                thresholds = candidate
            except (TypeError, ValueError):
                pass
        return ReviewSettings(
            think_s=float(think)
            if isinstance(think, int | float)
            and not isinstance(think, bool)
            and THINK_RANGE[0] <= think <= THINK_RANGE[1]
            else DEFAULT_THINK_S,
            thresholds=thresholds,
            tolerance_cp=tol if isinstance(tol, int) and not isinstance(tol, bool) else DEFAULT_TOLERANCE_CP,
            key_moments=km if isinstance(km, int) and not isinstance(km, bool) else DEFAULT_KEY_MOMENTS,
        )

    def set_settings(
        self,
        *,
        think_s: Any = None,
        thresholds: Any = None,
        tolerance_cp: Any = None,
        key_moments: Any = None,
    ) -> ReviewSettings:
        if think_s is not None:
            if not _num(think_s) or not THINK_RANGE[0] <= think_s <= THINK_RANGE[1]:
                raise ValidationError(f"The think time must be {THINK_RANGE[0]}–{THINK_RANGE[1]} s per position.")
            self._settings.set(THINK_KEY, round(float(think_s), 2))
        if thresholds is not None:
            if not isinstance(thresholds, dict) or not all(
                isinstance(thresholds.get(k), int) and not isinstance(thresholds.get(k), bool)
                for k in ("inaccuracy", "mistake", "blunder")
            ):
                raise ValidationError("thresholds need whole-number inaccuracy, mistake and blunder values")
            t = Thresholds(
                int(thresholds["inaccuracy"]), int(thresholds["mistake"]), int(thresholds["blunder"]),
                int(thresholds.get("decided", Thresholds().decided)),
            )  # fmt: skip
            try:
                t.validate()
            except ValueError as e:
                raise ValidationError(str(e)) from None
            self._settings.set(
                THRESHOLDS_KEY,
                {"inaccuracy": t.inaccuracy, "mistake": t.mistake, "blunder": t.blunder, "decided": t.decided},
            )
            # v0.8-B1: games already analyzed are regraded from their stored evals (no engine pass).
            if self._store.regrade(lambda row: regrade(row, t)):
                self.retag()  # v0.10: a new Missed / Allowed / error set means new tags
        if tolerance_cp is not None:
            try:
                self._settings.set(TOLERANCE_KEY, validate_tolerance(tolerance_cp))
            except ValueError as e:
                raise ValidationError(str(e)) from None
        if key_moments is not None:
            lo, hi = KEY_MOMENTS_RANGE
            if not isinstance(key_moments, int) or isinstance(key_moments, bool) or not lo <= key_moments <= hi:
                raise ValidationError(f"Key moments must be a whole number from {lo} to {hi}.")
            self._settings.set(KEY_MOMENTS_KEY, key_moments)
        return self.settings()

    # ------------------------------------------------------------ tags (v0.10)

    def regrade_stored(self) -> int:
        """Grade every stored move again at today's thresholds and rules (no engine). The v0.10 backfill
        uses it so moves analyzed before v0.10 get the v0.10-B2 Missed/Allowed rule."""
        th = self.settings().thresholds
        return self._store.regrade(lambda row: regrade(row, th))

    def retag(self, game_ids: Sequence[int] | None = None, cancel: CancelToken | None = None) -> int:
        """Work out the themes and habits again from the stored analysis (no engine), for these games or
        every analyzed game. Used after a threshold change and as the v0.10 backfill. Returns the games
        whose tags changed."""
        changed = 0
        for gid in self._store.analyzed_games() if game_ids is None else game_ids:
            if cancel is not None:
                cancel.raise_if_cancelled()
            rows = self._store.rows(gid)
            tagged = tag_game(rows)
            diff = [(n.ply, n.themes, n.habits) for o, n in zip(rows, tagged, strict=True) if o != n]
            if diff:
                self._store.set_tags(gid, diff)
                changed += 1
        return changed

    # ------------------------------------------------------------ the queue

    def is_current(self, game: GameRow) -> bool:
        """Analyzed at today's think time with today's engine (FR-11.31)."""
        return (
            game.analysis_status != "none"
            and game.analysis_think_s is not None
            and abs(game.analysis_think_s - self.settings().think_s) < 1e-9
            and game.analysis_engine == self._engine.engine_id()
        )

    def queue(self, game_ids: Sequence[int], *, force: bool = False) -> str | None:
        """Add games to the queue (in order, no duplicates) and make sure the job runs. Games already
        analyzed at the current settings are skipped unless `force`. Returns the job id, or None when
        there was nothing to do."""
        added = False
        for gid in game_ids:
            if not isinstance(gid, int) or isinstance(gid, bool):
                raise ValidationError("game ids must be whole numbers")
            game = self._games.get(gid)
            if game is None:
                continue
            if not force and self.is_current(game):
                continue
            with self._lock:
                if gid != self._current and gid not in self._queue:
                    self._queue.append(gid)
                    added = True
        with self._lock:
            if self._draining:
                return self._job
            if not added and not self._queue:
                return None
            self._draining = True
            self._job = self._runner.submit(JOB_KIND, self._drain)
            return self._job

    def status(self) -> QueueStatus:
        with self._lock:
            return QueueStatus(self._job if self._draining else None, self._current, tuple(self._queue))

    def _drain(self, progress: ProgressFn, cancel: CancelToken) -> str:
        done = 0
        try:
            while True:
                with self._lock:
                    if not self._queue:
                        self._current = None
                        self._draining = False
                        break
                    gid = self._queue.popleft()
                    self._current = gid
                    total = done + 1 + len(self._queue)
                game = self._games.get(gid)
                if game is None:
                    continue
                self._analyze(game, progress, cancel, done, total)
                done += 1
        except BaseException:
            with self._lock:
                self._queue.clear()  # cancel stops the whole queue (FR-11.8)
                self._current = None
                self._draining = False
            raise
        return f"Analyzed {done} game{'s' if done != 1 else ''}"

    def _analyze(self, game: GameRow, progress: ProgressFn, cancel: CancelToken, done: int, total: int) -> None:
        try:
            parsed = parse_single_pgn(game.pgn)
        except GameError as e:  # stored games were validated on import; be safe anyway
            log.warning("game %s can't be analyzed: %s", game.id, e.reason)
            return
        st = self.settings()
        engine = self._engine.engine_id()
        board = chess.Board(parsed.start_fen)
        n = len(parsed.moves)
        analyses: list[list[EngineLine] | None] = []
        label = f"{game.white or '?'} – {game.black or '?'}"
        for i in range(n + 1):
            cancel.raise_if_cancelled()
            frac = (done + i / (n + 1)) / total
            progress(frac, f"Analyzing game {done + 1} of {total} ({label}): move {min(i + 1, n)} of {n}")
            try:
                lines = self._engine.analyse_background(board, st.think_s, MULTIPV)
            except Exception as e:
                if isinstance(e, EngineNotInstalled):
                    raise JobFailed(
                        "engine_not_installed", "Install Stockfish to analyze games.", retryable=False
                    ) from None
                raise JobFailed(
                    "engine_error", f"Stockfish stopped while analyzing: {getattr(e, 'message', e)}"
                ) from None
            analyses.append(lines or None)
            if i < n:
                board.push(chess.Move.from_uci(parsed.moves[i]))
        tc = game.time_control
        division = game.extra.get("division") if isinstance(game.extra.get("division"), dict) else None
        rows = grade_game(
            parsed.start_fen,
            parsed.moves,
            analyses,
            clocks=parsed.clocks,
            low_clock_of=lambda s: low_clock(s, tc),
            division=division,
            th=st.thresholds,
        )
        now = self.settings().thresholds
        if now != st.thresholds:  # v0.8-B10: the thresholds changed while this game was analyzed
            rows = [regrade(r, now) for r in rows]
        rows = tag_game(rows)  # v0.10: themes and habits (FR-10.12, 10.27), from the analysis only
        self._store.replace(game.id, rows, "analyzed", st.think_s, engine)
        for fn in self._listeners:
            fn(game.id, lambda f, m: progress((done + 1) / total if f is None else f, m), cancel)
