"""The interactive engine for the app (FR-7.1–7.6; ARCHITECTURE §3 decision 12).

- Which binary: the custom path if set (it passed the smoke test when saved), else the managed install.
- Every position is validated with python-chess before the engine sees it (FR-7.6).
- Settings (FR-7.4): think time, threads and hash, validated and kept in `settings`.
- Latest request wins: each caller key (a session's panel, its analysis board…) has a generation
  number; a request that's no longer the newest when its turn comes answers `superseded` at once,
  so stepping quickly through a line runs one search, not ten.
- Engine calls are bridge calls the UI awaits (about the think time), not jobs; the install and the
  custom-engine check are jobs.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import chess

from weaksquare.core.engine import (
    EngineClient,
    EngineError,
    EngineLine,
    EngineNotInstalled,
    EngineProbe,
    UnsupportedPlatform,
    format_score,
    game_over_text,
    score_for,
)
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.puzzle import Color
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn
from weaksquare.services.engine_install import EngineInstaller, run_install
from weaksquare.services.ui_settings import SettingsStore

log = logging.getLogger(__name__)

INSTALL_JOB = "stockfish_install"
CHECK_JOB = "engine_check"
MULTIPV = 3  # FR-7.2
MAX_PV_PLIES = 12
THINK_RANGE = (0.2, 10.0)
HASH_RANGE = (16, 2048)
KEYS = {"think_s": "engine.think_s", "threads": "engine.threads", "hash_mb": "engine.hash_mb"}
CUSTOM_PATH = "engine.custom_path"
CUSTOM_NAME = "engine.custom_name"


@dataclass(frozen=True)
class EngineSettings:
    think_s: float
    threads: int
    hash_mb: int
    custom_path: str | None
    max_threads: int  # this PC's logical CPUs: the threads limit


EngineState = Literal["ready", "not_installed", "unsupported_platform", "custom_invalid"]


@dataclass(frozen=True)
class EngineStatus:
    state: EngineState
    source: Literal["managed", "custom"] | None
    name: str | None  # e.g. "Stockfish 19"
    path: str | None
    tag: str  # the pinned release (sf_19)
    install_job_id: str | None  # the running install, so a reopened view can follow it
    message: str | None = None


@dataclass(frozen=True)
class AnalysisLine:
    score: str  # from your side (FR-7.2): "+3.2 for you"
    cp: int | None  # from your side
    mate: int | None  # from your side
    pv: tuple[str, ...]  # UCI


@dataclass(frozen=True)
class Analysis:
    fen: str
    lines: tuple[AnalysisLine, ...]
    game_over: str | None = None  # "Checkmate: you win", … (the engine wasn't asked)
    superseded: bool = False  # a newer request for the same view replaced this one


def _default_threads(cpu_count: int) -> int:
    return max(1, cpu_count - 1)


class EngineService:
    def __init__(
        self,
        installer: EngineInstaller,
        settings: SettingsStore,
        runner: JobRunner,
        make_engine: Callable[[str, int, int], EngineClient],
        probe: EngineProbe,
        cpu_count: int,
        path_exists: Callable[[str], bool] = lambda p: Path(p).is_file(),
    ) -> None:
        self._installer = installer
        self._settings = settings
        self._runner = runner
        self._make_engine = make_engine
        self._probe = probe
        self._cpus = max(1, cpu_count)
        self._exists = path_exists
        self._engine: EngineClient | None = None
        self._engine_path: str | None = None
        self._engine_lock = threading.Lock()  # one search at a time; also guards _engine
        self._gen_lock = threading.Lock()
        self._gens = itertools.count(1)
        self._latest: dict[Any, int] = {}

    # ---- settings (FR-7.4, 7.5) ---------------------------------------------------------------------

    def settings(self) -> EngineSettings:
        s = self._settings
        think = s.get(KEYS["think_s"])
        threads = s.get(KEYS["threads"])
        hash_mb = s.get(KEYS["hash_mb"])
        return EngineSettings(
            think_s=float(think) if isinstance(think, int | float) else 1.0,
            threads=min(int(threads), self._cpus) if isinstance(threads, int) else _default_threads(self._cpus),
            hash_mb=int(hash_mb) if isinstance(hash_mb, int) else 256,
            custom_path=s.get(CUSTOM_PATH) or None,
            max_threads=self._cpus,
        )

    def set_settings(self, think_s: Any = None, threads: Any = None, hash_mb: Any = None) -> EngineSettings:
        if think_s is not None:
            if isinstance(think_s, bool) or not isinstance(think_s, int | float):
                raise ValidationError("Think time must be a number of seconds.")
            if not THINK_RANGE[0] <= float(think_s) <= THINK_RANGE[1]:
                raise ValidationError(f"Think time must be between {THINK_RANGE[0]:g} and {THINK_RANGE[1]:g} seconds.")
        if threads is not None and (
            isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= self._cpus
        ):
            raise ValidationError(f"Threads must be a whole number from 1 to {self._cpus}.")
        if hash_mb is not None and (
            isinstance(hash_mb, bool) or not isinstance(hash_mb, int) or not HASH_RANGE[0] <= hash_mb <= HASH_RANGE[1]
        ):
            raise ValidationError(f"Hash must be a whole number of MB from {HASH_RANGE[0]} to {HASH_RANGE[1]}.")
        if think_s is not None:
            self._settings.set(KEYS["think_s"], round(float(think_s), 2))
        if threads is not None:
            self._settings.set(KEYS["threads"], threads)
        if hash_mb is not None:
            self._settings.set(KEYS["hash_mb"], hash_mb)
        st = self.settings()
        if threads is not None or hash_mb is not None:
            with self._engine_lock:
                if self._engine is not None:
                    self._engine.configure(st.threads, st.hash_mb)
        return st

    # ---- status, install, custom engine -------------------------------------------------------------

    def status(self) -> EngineStatus:
        jobs = self._runner.active(INSTALL_JOB)
        installing = jobs[0].id if jobs else None
        tag = self._installer.tag
        custom = self._settings.get(CUSTOM_PATH)
        if custom:
            name = self._settings.get(CUSTOM_NAME)
            if self._exists(custom):
                return EngineStatus("ready", "custom", name or "Custom engine", custom, tag, installing)
            return EngineStatus(
                "custom_invalid", "custom", name, custom, tag, installing,
                "Your custom engine can't be found. Choose it again, or switch back to the managed Stockfish.",
            )  # fmt: skip
        try:
            self._installer.asset()
        except UnsupportedPlatform as e:
            return EngineStatus("unsupported_platform", None, None, None, tag, installing, e.message)
        installed = self._installer.installed()
        if installed is None:
            return EngineStatus("not_installed", None, None, None, tag, installing, "Stockfish isn't installed.")
        return EngineStatus("ready", "managed", installed.name, str(installed.exe), tag, installing)

    def start_install(self, force: bool = False) -> str:
        if self._runner.active(INSTALL_JOB):
            raise ConflictError("Stockfish is already being installed.")
        if force:
            self.close()  # a running exe can't be replaced on Windows

        def job(progress: ProgressFn, token: CancelToken) -> str:
            return run_install(self._installer, progress, token, force)

        return self._runner.submit(INSTALL_JOB, job)

    def start_custom_check(self, path: Any) -> str:
        """FR-7.5 advanced setting: the path is saved only after the same smoke test passes."""
        if not isinstance(path, str) or not path.strip() or len(path) > 1000:
            raise ValidationError("Choose the engine's .exe file.")
        path = path.strip()
        if not path.lower().endswith(".exe"):
            raise ValidationError("Choose the engine's .exe file.")
        if self._runner.active(CHECK_JOB):
            raise ConflictError("An engine check is already running.")

        def job(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, "Testing the engine…")
            if not self._exists(path):
                raise JobFailed("not_found", "That file doesn't exist.", False)
            try:
                info = self._probe(path)
            except EngineError as e:
                raise JobFailed(
                    "smoke_test_failed", f"That engine didn't pass the test, so it wasn't saved. ({e.message})", False
                ) from None
            token.raise_if_cancelled()
            self._settings.set(CUSTOM_PATH, path)
            self._settings.set(CUSTOM_NAME, info.name)
            self.close()
            log.info("custom engine set: %s", info.name)
            return f"Using {info.name}."

        return self._runner.submit(CHECK_JOB, job)

    def clear_custom(self) -> None:
        self._settings.set(CUSTOM_PATH, None)
        self._settings.set(CUSTOM_NAME, None)
        self.close()

    # ---- analysis -------------------------------------------------------------------------------------

    def _exe(self) -> str:
        st = self.status()
        if st.state != "ready" or st.path is None:
            raise EngineNotInstalled(st.message or "Stockfish isn't installed.")
        return st.path

    def _client(self) -> EngineClient:
        """The running engine for the current binary (call with _engine_lock held)."""
        path = self._exe()
        if self._engine is not None and self._engine_path != path:
            self._engine.close()
            self._engine = None
        if self._engine is None:
            st = self.settings()
            self._engine = self._make_engine(path, st.threads, st.hash_mb)
            self._engine_path = path
        return self._engine

    def ticket(self, key: Any) -> int:
        """A new generation for `key`: any older request for the same key becomes superseded."""
        with self._gen_lock:
            gen = next(self._gens)
            self._latest[key] = gen
            return gen

    def _is_latest(self, key: Any, gen: int) -> bool:
        with self._gen_lock:
            return self._latest.get(key) == gen

    def analyse(
        self, board: chess.Board, player: Color, *, multipv: int = MULTIPV, key: Any = None, gen: int | None = None
    ) -> Analysis:
        """Analyse a position that core.engine.validate_fen / validate_line already accepted."""
        fen = board.fen()
        over = game_over_text(board, player)
        if over is not None or not any(board.legal_moves):
            return Analysis(fen, (), over or "No legal moves")
        if not board.is_valid():  # defence in depth: callers validate first (FR-7.6)
            raise ValidationError("That position isn't legal.")
        with self._engine_lock:
            if key is not None and gen is not None and not self._is_latest(key, gen):
                return Analysis(fen, (), superseded=True)
            client = self._client()
            lines = client.analyse(board.copy(), self.settings().think_s, multipv)
        return Analysis(fen, tuple(self._line(board, line, player) for line in lines))

    @staticmethod
    def _line(board: chess.Board, line: EngineLine, player: Color) -> AnalysisLine:
        cp, mate = score_for(line, player)
        pv: list[str] = []
        b = board.copy()
        for uci in line.pv[:MAX_PV_PLIES]:  # keep only the legal prefix: engine output is checked too
            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                break
            if move not in b.legal_moves:
                break
            b.push(move)
            pv.append(uci)
        return AnalysisLine(format_score(line, player), cp, mate, tuple(pv))

    def close(self) -> None:
        """Stop the engine process (NFR-6; also before a reinstall or a binary change)."""
        with self._engine_lock:
            engine, self._engine, self._engine_path = self._engine, None, None
        if engine is not None:
            engine.close()


def with_pv(analysis: Analysis, pv: tuple[str, ...]) -> Analysis:
    """A copy whose first line has `pv` (used to trim the refutation)."""
    if not analysis.lines:
        return analysis
    first = replace(analysis.lines[0], pv=pv)
    return replace(analysis, lines=(first, *analysis.lines[1:]))
