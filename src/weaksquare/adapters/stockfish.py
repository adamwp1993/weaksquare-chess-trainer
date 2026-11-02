"""EngineClient over python-chess UCI (FR-7.1, 7.6; ARCHITECTURE §3 decision 12).

- One process, started lazily on the first request and kept until `close()` (NFR-6).
- Requests are serialized by a lock and bounded by python-chess's timeout (think time + TIMEOUT_S),
  so a call never hangs. A timeout kills the process, restarts it once and fails that request.
- Stockfish 19 prints `info string CRITICAL ERROR …` and exits on invalid input. Callers validate
  first (core.engine); if the process dies anyway, the CRITICAL ERROR line is logged, the engine is
  restarted once, and that one request fails with a clear error. The next request works.
- On Windows the process gets CREATE_NO_WINDOW, so no console flashes up behind the app.
"""

from __future__ import annotations

import collections
import contextlib
import logging
import subprocess
import sys
import threading
from typing import Any, NoReturn

import chess
import chess.engine

from weaksquare.core.engine import EngineError, EngineInfo, EngineLine

log = logging.getLogger(__name__)

TIMEOUT_S = 10.0  # extra time python-chess allows on top of the think time
PROBE_THINK_S = 0.2
_POPEN: dict[str, Any] = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

# ---- CRITICAL ERROR capture -----------------------------------------------------------------------
# python-chess logs every line it receives at DEBUG on the "chess.engine" logger. This filter keeps
# the CRITICAL ERROR lines (with the pid python-chess prefixes) and stops all DEBUG traffic from
# propagating into the app's log files.
_critical: collections.deque[str] = collections.deque(maxlen=20)


class _CaptureCritical(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno <= logging.DEBUG:
            try:
                text = record.getMessage()
            except Exception:
                return False
            if "CRITICAL ERROR" in text:
                _critical.append(text)
            return False
        return True


def _install_capture() -> None:
    logger = logging.getLogger("chess.engine")
    if not any(isinstance(f, _CaptureCritical) for f in logger.filters):
        logger.addFilter(_CaptureCritical())
        logger.setLevel(logging.DEBUG)


_install_capture()


def _critical_line(pid: int | None) -> str | None:
    tag = f"pid={pid})" if pid is not None else ""
    for text in reversed(_critical):
        if tag in text:
            return text.split(">> ", 1)[-1]
    return None


def _open(path: str | list[str]) -> chess.engine.SimpleEngine:
    """`path` is the exe; tests pass a command list (python + the fake engine script)."""
    try:
        return chess.engine.SimpleEngine.popen_uci(path, timeout=TIMEOUT_S, **_POPEN)
    except (OSError, chess.engine.EngineError, TimeoutError) as e:
        raise EngineError(f"Stockfish couldn't be started ({type(e).__name__}).", code="engine_start_failed") from None


RELEASE_AFTER_S = 1.0


def _release_thread(engine: chess.engine.SimpleEngine) -> None:
    """Work around a python-chess 1.11.2 bug (v0.4-B1). When the process is killed mid-search (our
    timeout), its connection_lost handler raises InvalidStateError before it resolves the protocol's
    `returncode` future, so SimpleEngine's background thread (not a daemon) waits forever and the
    Python process can never exit. A moment after closing, resolve that future ourselves if nothing
    else has; the thread then finishes normally."""
    protocol = engine.protocol
    loop = protocol.loop

    def finish() -> None:
        if not protocol.returncode.done():
            log.info("releasing a stuck engine thread")
            protocol.returncode.set_result(-1)

    with contextlib.suppress(RuntimeError):  # the loop has already stopped: nothing is waiting
        loop.call_soon_threadsafe(loop.call_later, RELEASE_AFTER_S, finish)


def _close(engine: chess.engine.SimpleEngine | None) -> None:
    if engine is None:
        return
    try:
        engine.close()  # closes the transport: the process is killed if it doesn't exit
    except Exception:
        log.debug("engine close failed", exc_info=True)
    _release_thread(engine)


def _pid(engine: chess.engine.SimpleEngine | None) -> int | None:
    try:
        return engine.transport.get_pid() if engine is not None else None  # type: ignore[union-attr]
    except Exception:
        return None


def probe_engine(path: str | list[str]) -> EngineInfo:
    """FR-7.5 smoke test: `uci` → `uciok` (popen_uci does the handshake), then a short search from the
    start position must return a legal move. Raises EngineError otherwise; the process always exits."""
    engine = _open(path)
    try:
        name = str(engine.id.get("name", "")).strip() or "UCI engine"
        board = chess.Board()
        result = engine.play(board, chess.engine.Limit(time=PROBE_THINK_S))
        if result.move is None or result.move not in board.legal_moves:
            raise EngineError("The engine didn't return a legal move.", code="smoke_test_failed")
        return EngineInfo(name)
    except chess.engine.EngineTerminatedError:
        raise EngineError("The engine exited during its self-test.", code="smoke_test_failed") from None
    except (chess.engine.EngineError, TimeoutError):
        raise EngineError("The engine didn't answer its self-test in time.", code="smoke_test_failed") from None
    finally:
        _close(engine)


def _line(info: chess.engine.InfoDict) -> EngineLine | None:
    score = info.get("score")
    pv = info.get("pv") or []
    if score is None:
        return None
    white = score.white()
    mate = white.mate()
    return EngineLine(cp=None if mate is not None else white.score(), mate=mate, pv=tuple(m.uci() for m in pv))


class StockfishEngine:
    """The interactive engine. Thread-safe: one request runs at a time."""

    def __init__(self, path: str | list[str], threads: int = 1, hash_mb: int = 16) -> None:
        self._path = path
        self._options = {"Threads": threads, "Hash": hash_mb}
        self._engine: chess.engine.SimpleEngine | None = None
        self._info: EngineInfo | None = None
        self._lock = threading.Lock()
        self._closed = False  # set by close(): an in-flight search then fails quietly, no restart

    @property
    def path(self) -> str | list[str]:
        return self._path

    def _start(self) -> chess.engine.SimpleEngine:
        engine = _open(self._path)
        try:
            engine.configure(self._options)
        except chess.engine.EngineError:
            log.warning("engine refused options %s", self._options)
        self._info = EngineInfo(str(engine.id.get("name", "")).strip() or "UCI engine")
        log.info("engine started: %s (pid %s)", self._info.name, _pid(engine))
        return engine

    def _ensure(self) -> chess.engine.SimpleEngine:
        if self._closed:
            raise EngineError("The engine has been stopped.", code="engine_stopped")
        if self._engine is None:
            self._engine = self._start()
        return self._engine

    def _restart_after(self, reason: str) -> None:
        """Kill the current process and start one new one. A failing restart leaves the engine stopped
        (the next request tries again); it never loops."""
        _close(self._engine)
        self._engine = None
        try:
            self._engine = self._start()
            log.info("engine restarted after %s", reason)
        except EngineError:
            log.warning("engine restart after %s failed", reason)

    def info(self) -> EngineInfo:
        with self._lock:
            self._ensure()
            assert self._info is not None
            return self._info

    def configure(self, threads: int, hash_mb: int) -> None:
        with self._lock:
            self._options = {"Threads": threads, "Hash": hash_mb}
            if self._engine is not None:
                try:
                    self._engine.configure(self._options)
                except (chess.engine.EngineError, TimeoutError):
                    self._restart_after("a configure failure")

    def analyse(self, board: chess.Board, think_s: float, multipv: int) -> list[EngineLine]:
        """MultiPV analysis. The board must already be validated (core.engine.validate_fen)."""
        with self._lock:
            engine = self._ensure()
            pid = _pid(engine)
            try:
                infos = engine.analyse(
                    board,
                    chess.engine.Limit(time=think_s),
                    multipv=multipv,
                    info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
                )
            except (chess.engine.EngineError, TimeoutError) as e:
                self._handle_failure(e, pid, think_s)
        lines = [line for line in (_line(i) for i in infos) if line is not None]
        if not lines:
            raise EngineError("Stockfish returned no analysis.")
        return lines

    def _handle_failure(self, e: Exception, pid: int | None, think_s: float) -> NoReturn:
        """A search failed: report it as a clean EngineError, restarting the engine once (FR-7.6)."""
        if self._closed:  # close() killed it on purpose (v0.4-B5): no restart, no error log
            raise EngineError("The engine has been stopped.", code="engine_stopped") from None
        if isinstance(e, chess.engine.EngineTerminatedError):
            critical = _critical_line(pid)
            if critical:
                log.error("engine terminated: %s", critical)
            else:
                log.error("engine terminated unexpectedly")
            self._restart_after("a crash")
            raise EngineError(
                "Stockfish stopped unexpectedly and was restarted. Try again.", code="engine_crashed"
            ) from None
        if isinstance(e, TimeoutError):
            log.error("engine timed out (think time %.1fs)", think_s)
            self._restart_after("a timeout")
            raise EngineError("Stockfish didn't answer in time and was restarted.", code="engine_timeout") from None
        log.error("engine protocol error: %s", e)
        self._restart_after("a protocol error")
        raise EngineError("Stockfish sent something unexpected and was restarted.") from None

    def close(self) -> None:
        """Stop the process now (NFR-6; v0.4-B5). It doesn't wait for a search in progress: the process
        is killed, and that search fails quietly with `engine_stopped` instead of restarting."""
        self._closed = True
        engine, self._engine = self._engine, None
        if engine is None:
            return
        if self._lock.acquire(blocking=False):  # idle: a polite `quit`
            try:
                engine.quit()
            except Exception:
                _close(engine)
            finally:
                self._lock.release()
        else:  # mid-search: kill it rather than wait for the think time
            _close(engine)
