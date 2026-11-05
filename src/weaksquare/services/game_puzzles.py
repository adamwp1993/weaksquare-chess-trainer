"""Puzzles from your games (v0.10, REQUIREMENTS §10.9).

After any analysis of one of your games (Coach, Analyze selected, Review; Adam, v0.10 planning), your
mistakes at the chosen **severity level** (FR-10.40) go through the quality check ported from
lichess-puzzler (`core/puzzle_gen.py`, FR-10.41) on the **background** engine. Clean ones become
`custom_puzzles` with origin `coach`:

- **Missed:** the position before your move, solved as you.
- **Allowed:** the position after your move, solved as your opponent (FR-10.42).

Each check is cached in `coach_candidates`, so a level change runs no engine over the stored ones:
narrowing **archives** puzzles (never deletes them), widening restores them, and only mistakes never
checked before go to the engine. A puzzle you saved by hand at that move wins, and a puzzle you
archived yourself (`hidden`) stays archived. Another player's games never make puzzles.

Also the one-time v0.10 **backfill**: tags for games and puzzles from before v0.10, then puzzles for
your games that were already analyzed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import chess

from weaksquare.adapters.db.repos.coach import Candidate
from weaksquare.core.clock import Clock
from weaksquare.core.engine import EngineLine, EngineNotInstalled
from weaksquare.core.errors import ValidationError
from weaksquare.core.game_review import ERRORS, MoveRow, Score, missed_or_allowed
from weaksquare.core.games import GameRow
from weaksquare.core.puzzle import NewCustomPuzzle
from weaksquare.core.puzzle_gen import GEN_VERSION, GenSettings, PovScore, check_position, validate_margin
from weaksquare.core.tagging import tag_line
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "game_puzzles"
LEVEL_KEY = "coach.puzzle_level"
THINK_KEY = "coach.puzzle_think_s"
MARGIN_KEY = "coach.puzzle_margin"
BACKFILL_KEY = "coach.backfill_version"
BACKFILL_VERSION = 1
LEVELS: dict[str, tuple[str, ...]] = {
    "blunders": ("blunder",),
    "mistakes": ("mistake", "blunder"),
    "inaccuracies": ERRORS,
}
DEFAULT_LEVEL = "mistakes"
DEFAULT_THINK_S = 1.0
THINK_RANGE = (0.2, 5.0)
OPENING_PLIES = 12  # FR-10.10: the Coach skips the first 6 moves (v0.10 planning)
ME = "me"


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class Games(Protocol):
    def get(self, game_id: int) -> GameRow | None: ...

    def subjects(self, game_id: int) -> dict[str, str | None]: ...


class AnalysisStore(Protocol):
    def rows(self, game_id: int) -> list[MoveRow]: ...

    def analyzed_games(self) -> list[int]: ...


class CandidateStore(Protocol):
    def candidates(self, game_id: int) -> dict[int, Candidate]: ...

    def put_candidate(self, c: Candidate, checked_at: str) -> None: ...


class Puzzles(Protocol):
    def add(self, p: NewCustomPuzzle, created_at: str) -> tuple[int, bool]: ...

    def at(self, game_id: int, ply: int) -> tuple[int, str, str] | None: ...

    def coach_puzzles(self) -> list[tuple[int, int, int, str | None, str]]: ...

    def set_status(self, ids: list[int], status: str) -> None: ...

    def untagged(self) -> list[tuple[int, str, tuple[str, ...], int | None, int | None]]: ...

    def set_themes(self, items: list[tuple[int, tuple[str, ...]]]) -> None: ...


class BackgroundEngine(Protocol):
    def analyse_background(self, board: chess.Board, think_s: float, multipv: int = ...) -> list[EngineLine]: ...


class Retagger(Protocol):
    def retag(self, game_ids: Sequence[int] | None = None, cancel: CancelToken | None = None) -> int: ...

    def thresholds_decided(self) -> int: ...

    def regrade_stored(self) -> int: ...


@dataclass(frozen=True)
class PuzzleSettings:
    level: str
    think_s: float
    margin: float


@dataclass(frozen=True)
class Target:
    """A mistake that could become a puzzle, and the position it's solved from."""

    row: MoveRow
    kind: str  # missed / allowed
    fen: str
    first_lines: tuple[EngineLine, ...]
    prev: PovScore | None
    solver: str  # white / black
    premove: tuple[str, str] | None  # (the position before it, the move) for the tagger


def _pov(s: Score) -> PovScore:
    return PovScore(cp=s.cp, mate=s.mate)


def _other(color: str) -> str:
    return "black" if color == "white" else "white"


def targets(rows: Sequence[MoveRow], colors: set[str], severities: tuple[str, ...]) -> list[Target]:
    """Your mistakes at these severities, past the opening, as puzzle positions (FR-10.40, 10.42)."""
    out: list[Target] = []
    for i, row in enumerate(rows):
        if row.mover not in colors or row.classification not in severities or row.ply < OPENING_PLIES:
            continue
        kind = (
            row.kind
            if row.classification != "inaccuracy"
            else missed_or_allowed(row.eval_before, row.eval_after, "mistake")
        )
        if kind == "missed":
            prev = rows[i - 1] if i > 0 else None
            out.append(
                Target(
                    row, kind, row.fen_before, row.lines, _pov(prev.eval_before.negate()) if prev else None,
                    row.mover, (prev.fen_before, prev.move_uci) if prev else None,
                )
            )  # fmt: skip
        elif kind == "allowed" and i + 1 < len(rows):
            nxt = rows[i + 1]
            out.append(
                Target(
                    row, kind, nxt.fen_before, nxt.lines, _pov(row.eval_before.negate()), _other(row.mover),
                    (row.fen_before, row.move_uci),
                )
            )  # fmt: skip
    return out


class GamePuzzlesService:
    def __init__(
        self,
        games: Games,
        store: AnalysisStore,
        checks: CandidateStore,
        puzzles: Puzzles,
        engine: BackgroundEngine,
        settings: Settings,
        retagger: Retagger,
        clock: Clock,
        runner: JobRunner,
    ) -> None:
        self._games = games
        self._store = store
        self._checks = checks
        self._puzzles = puzzles
        self._engine = engine
        self._settings = settings
        self._retagger = retagger
        self._clock = clock
        self._runner = runner

    # ------------------------------------------------------------ settings

    def settings(self) -> PuzzleSettings:
        level = self._settings.get(LEVEL_KEY)
        think = self._settings.get(THINK_KEY)
        margin = self._settings.get(MARGIN_KEY)
        try:
            m = validate_margin(margin) if margin is not None else GenSettings().margin
        except ValueError:
            m = GenSettings().margin
        return PuzzleSettings(
            level=level if level in LEVELS else DEFAULT_LEVEL,
            think_s=float(think)
            if isinstance(think, int | float)
            and not isinstance(think, bool)
            and THINK_RANGE[0] <= think <= THINK_RANGE[1]
            else DEFAULT_THINK_S,
            margin=m,
        )

    def set_settings(self, *, level: Any = None, think_s: Any = None, margin: Any = None) -> PuzzleSettings:
        """Changing the level rebuilds the set from the stored checks (no engine over them) and checks
        only mistakes never checked before, in a background job (FR-10.40)."""
        if level is not None:
            if level not in LEVELS:
                raise ValidationError("The level must be blunders, mistakes or inaccuracies.")
            self._settings.set(LEVEL_KEY, level)
        if think_s is not None:
            if not isinstance(think_s, int | float) or isinstance(think_s, bool):
                raise ValidationError("The think time must be a number.")
            if not THINK_RANGE[0] <= think_s <= THINK_RANGE[1]:
                raise ValidationError(f"The think time must be {THINK_RANGE[0]}–{THINK_RANGE[1]} s per position.")
            self._settings.set(THINK_KEY, round(float(think_s), 2))
        if margin is not None:
            try:
                self._settings.set(MARGIN_KEY, validate_margin(margin))
            except ValueError as e:
                raise ValidationError(str(e)) from None
        if level is not None:
            self.rebuild()
        return self.settings()

    # ------------------------------------------------------------ the work

    def _check_key(self, game: GameRow, st: PuzzleSettings) -> str:
        return f"{GEN_VERSION}|{game.analysis_think_s}|{game.analysis_engine}|{st.think_s}|{st.margin}"

    def _my_colors(self, game_id: int) -> set[str]:
        color = self._games.subjects(game_id).get(ME)
        if color == "both":
            return {"white", "black"}
        return {color} if color in ("white", "black") else set()

    def _targets(self, game_id: int, st: PuzzleSettings) -> tuple[GameRow, list[Target]] | None:
        game = self._games.get(game_id)
        if game is None or game.analysis_status == "none":
            return None
        colors = self._my_colors(game_id)
        if not colors:
            return None  # not your game (FR-10.3), or your color isn't known yet
        return game, targets(self._store.rows(game_id), colors, LEVELS[st.level])

    def pending(self, game_ids: Sequence[int] | None = None) -> list[int]:
        """Your analyzed games with a mistake at the current level that hasn't been checked yet."""
        st = self.settings()
        out = []
        for gid in self._store.analyzed_games() if game_ids is None else game_ids:
            found = self._targets(gid, st)
            if found is None:
                continue
            game, ts = found
            key = self._check_key(game, st)
            cached = self._checks.candidates(gid)
            if any(gid not in out and (t.row.ply not in cached or cached[t.row.ply].check_key != key) for t in ts):
                out.append(gid)
        return out

    def process_game(self, game_id: int, cancel: CancelToken | None = None, *, engine: bool = True) -> int:
        """Check this game's mistakes at the current level and make or restore its puzzles. With
        ``engine=False``, only stored checks are used. Returns the puzzles made or restored."""
        st = self.settings()
        found = self._targets(game_id, st)
        if found is None:
            return 0
        game, ts = found
        key = self._check_key(game, st)
        cached = self._checks.candidates(game_id)
        gen = GenSettings(margin=st.margin, decided_cp=self._retagger.thresholds_decided())
        made = 0
        for t in ts:
            if cancel is not None:
                cancel.raise_if_cancelled()
            c = cached.get(t.row.ply)
            if c is None or c.check_key != key or c.kind != t.kind:
                if not engine:
                    continue
                verdict = check_position(t.fen, t.first_lines, t.prev, self._analyse(st.think_s), gen)
                c = Candidate(
                    game_id, t.row.ply, key, t.kind, verdict.passed, None if verdict.passed else verdict.reason,
                    verdict.line, verdict.cp,
                )  # fmt: skip
                self._checks.put_candidate(c, self._clock.now().isoformat())
            made += self._apply(game, t, c)
        return made

    def _analyse(self, think_s: float):  # type: ignore[no-untyped-def]
        def run(board: chess.Board, multipv: int) -> list[EngineLine]:
            try:
                return self._engine.analyse_background(board, think_s, multipv)
            except EngineNotInstalled:
                raise JobFailed("engine_not_installed", "Install Stockfish to make puzzles.", retryable=False) from None

        return run

    def _apply(self, game: GameRow, t: Target, c: Candidate) -> int:
        existing = self._puzzles.at(game.id, t.row.ply)
        if existing is not None:
            pid, origin, status = existing
            if origin != "coach":
                return 0  # you saved this move yourself: yours wins
            if c.passed and status == "archived":
                self._puzzles.set_status([pid], "active")
                return 1
            if not c.passed and status == "active":
                self._puzzles.set_status([pid], "archived")
            return 0
        if not c.passed or not c.line:
            return 0
        premove_fen, premove = t.premove if t.premove else (t.fen, None)
        themes = tag_line(premove_fen, premove, c.line, c.cp) if t.premove else tag_line(t.fen, None, c.line, c.cp)
        _, created = self._puzzles.add(
            NewCustomPuzzle(
                fen=t.fen, solution=c.line, player_color=t.solver, origin="coach", strict=False,
                game_id=game.id, ply=t.row.ply, kind=t.kind, severity=t.row.classification,
                cp_loss=t.row.cp_loss, phase=t.row.phase, time_class=game.time_class,
                game_date=(game.played_at or "")[:10] or None, themes=themes,
                solve_as="opponent" if t.kind == "allowed" else "you",
            ),
            self._clock.now().isoformat(),
        )  # fmt: skip
        return int(created)

    def archive(self, puzzle_id: Any) -> None:
        """FR-10.44: you archived this puzzle (`hidden`): kept with its attempts, never served or restored."""
        if not isinstance(puzzle_id, int) or isinstance(puzzle_id, bool):
            raise ValidationError("puzzle_id must be a whole number")
        self._puzzles.set_status([puzzle_id], "hidden")

    def archive_outside_level(self) -> int:
        """Narrowing the level archives the Coach's puzzles outside it (never deletes them)."""
        keep = LEVELS[self.settings().level]
        out = [
            pid for pid, _, _, sev, status in self._puzzles.coach_puzzles() if status == "active" and sev not in keep
        ]
        if out:
            self._puzzles.set_status(out, "archived")
        return len(out)

    def rebuild(self) -> str | None:
        """FR-10.40: apply the level from the stored checks now; check new mistakes in the background."""
        self.archive_outside_level()
        for gid in self._store.analyzed_games():
            self.process_game(gid, engine=False)
        todo = self.pending()
        if not todo:
            return None
        return self._runner.submit(JOB_KIND, lambda p, c: self._run(todo, p, c))

    def _run(self, game_ids: Sequence[int], progress: ProgressFn, cancel: CancelToken) -> str:
        made = 0
        for n, gid in enumerate(game_ids):
            progress(n / max(1, len(game_ids)), f"Making puzzles from your games: game {n + 1} of {len(game_ids)}")
            made += self.process_game(gid, cancel)
        return f"{made} new puzzle{'s' if made != 1 else ''} from your games"

    def after_analysis(self, game_id: int, progress: ProgressFn, cancel: CancelToken) -> None:
        """The analysis hook: one pipeline, so any analysis of your game makes its puzzles."""
        progress(None, "Making puzzles from this game")
        try:
            self.process_game(game_id, cancel)
        except JobFailed:
            raise
        except Exception:  # a puzzle problem never fails the analysis itself
            log.exception("making puzzles from game %s failed", game_id)

    # ------------------------------------------------------------ the v0.10 backfill

    def backfill_needed(self) -> bool:
        return self._settings.get(BACKFILL_KEY) != BACKFILL_VERSION

    def start_backfill(self) -> str | None:
        if not self.backfill_needed() or self._runner.active(JOB_KIND):
            return None
        return self._runner.submit(JOB_KIND, self._backfill)

    def _backfill(self, progress: ProgressFn, cancel: CancelToken) -> str:
        progress(None, "Tagging your analyzed games")
        self._retagger.regrade_stored()  # moves analyzed before v0.10 get today's Missed/Allowed rule (v0.10-B2)
        self._retagger.retag(cancel=cancel)
        progress(None, "Tagging your puzzles")
        self.tag_puzzles()
        todo = self.pending()
        made = 0
        try:
            for n, gid in enumerate(todo):
                progress(n / max(1, len(todo)), f"Making puzzles from your games: game {n + 1} of {len(todo)}")
                made += self.process_game(gid, cancel)
        except JobFailed as e:
            if e.code != "engine_not_installed":
                raise
            return "Tagged your games; install Stockfish to make puzzles from them"  # tried again next launch
        self._settings.set(BACKFILL_KEY, BACKFILL_VERSION)
        return f"Tagged your games; {made} new puzzle{'s' if made != 1 else ''} from your games"

    def tag_puzzles(self) -> int:
        """Themes for saved and imported puzzles that have none (FR-11.16, 10.49)."""
        items: list[tuple[int, tuple[str, ...]]] = []
        rows_cache: dict[int, list[MoveRow]] = {}
        for pid, fen, solution, game_id, ply in self._puzzles.untagged():
            themes: tuple[str, ...] = ()
            if game_id is not None and ply is not None and ply > 0:
                rows = rows_cache.setdefault(game_id, self._store.rows(game_id))
                if ply < len(rows) and rows[ply].fen_before == fen:  # saved from Game Review: the move before
                    themes = tag_line(rows[ply - 1].fen_before, rows[ply - 1].move_uci, solution, None)
            items.append((pid, themes or tag_line(fen, None, solution, None)))
        if items:
            self._puzzles.set_themes(items)
        return len(items)
