"""adapters/stockfish.py against the fake UCI engine (FR-7.6; v0.4 Done when): runs in CI, no binary."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import chess
import pytest

from weaksquare.adapters.stockfish import StockfishEngine, probe_engine
from weaksquare.core.engine import EngineError

FAKE = str(Path(__file__).resolve().parents[1] / "fakes" / "uci_engine.py")
NO_KINGS = chess.Board("8/8/8/8/8/8/8/8 w - - 0 1")  # what validation would refuse; sent past it here


def cmd(mode: str = "normal", state: Path | None = None) -> list[str]:
    return [sys.executable, FAKE, mode] + ([str(state)] if state else [])


@pytest.fixture
def engine():
    e = StockfishEngine(cmd())
    yield e
    e.close()


def test_analyse_returns_multipv_lines(engine: StockfishEngine) -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")  # back-rank mate: Ra8#
    lines = engine.analyse(board, 0.05, 3)
    assert len(lines) == 3
    assert lines[0].pv[0] == "a1a8" and lines[0].mate == 1 and lines[0].cp is None
    assert engine.info().name == "FakeFish 1"


def test_scores_are_white_relative(engine: StockfishEngine) -> None:
    board = chess.Board("r5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1")  # Black mates with Ra1#
    line = engine.analyse(board, 0.05, 1)[0]
    assert line.pv[0] == "a8a1" and line.mate == -1


def test_invalid_position_restarts_once_and_fails_cleanly(engine: StockfishEngine, caplog) -> None:
    engine.analyse(chess.Board(), 0.05, 1)
    caplog.set_level(logging.INFO, logger="weaksquare")
    started = time.monotonic()
    with pytest.raises(EngineError) as e:
        engine.analyse(NO_KINGS, 0.05, 1)
    assert time.monotonic() - started < 10  # no hang
    assert e.value.code == "engine_crashed"
    assert "restarted" in e.value.message
    assert any("CRITICAL ERROR" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)
    assert sum("engine restarted" in r.getMessage() for r in caplog.records) == 1
    assert engine.analyse(chess.Board(), 0.05, 1)[0].pv  # the next request works


def test_engine_debug_traffic_stays_out_of_the_log(engine: StockfishEngine, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    engine.analyse(chess.Board(), 0.05, 1)
    assert not [r for r in caplog.records if r.name.startswith("chess.engine") and r.levelno <= logging.DEBUG]


def test_hang_times_out_restarts_and_fails(monkeypatch) -> None:
    import weaksquare.adapters.stockfish as sf

    monkeypatch.setattr(sf, "TIMEOUT_S", 1.0)
    e = StockfishEngine(cmd("hang"))
    try:
        started = time.monotonic()
        with pytest.raises(EngineError) as err:
            e.analyse(chess.Board(), 0.1, 1)
        assert err.value.code == "engine_timeout"
        assert time.monotonic() - started < 8
    finally:
        e.close()


def test_a_failing_restart_gives_a_clean_error_without_looping(tmp_path: Path) -> None:
    e = StockfishEngine(cmd("once", tmp_path / "launches"))
    try:
        e.analyse(chess.Board(), 0.05, 1)
        with pytest.raises(EngineError) as err:
            e.analyse(NO_KINGS, 0.05, 1)
        assert err.value.code == "engine_crashed"
        with pytest.raises(EngineError) as err2:  # the next request tries one start, which fails
            e.analyse(chess.Board(), 0.05, 1)
        assert err2.value.code == "engine_start_failed"
        assert int((tmp_path / "launches").read_text()) == 3  # first, the restart, one retry: no loop
    finally:
        e.close()


def test_configure_applies_threads_and_hash(engine: StockfishEngine) -> None:
    engine.analyse(chess.Board(), 0.05, 1)
    engine.configure(2, 32)
    assert engine.analyse(chess.Board(), 0.05, 1)


def test_probe_passes_for_a_working_engine() -> None:
    assert probe_engine(cmd()).name == "FakeFish 1"
    assert probe_engine(cmd("noise")).name == "UCI engine"


def test_probe_fails_for_a_broken_engine(tmp_path: Path) -> None:
    (tmp_path / "launches").write_text("5")
    with pytest.raises(EngineError):
        probe_engine(cmd("once", tmp_path / "launches"))
    with pytest.raises(EngineError):
        probe_engine(str(tmp_path / "missing.exe"))
    not_an_engine = tmp_path / "x.cmd"
    not_an_engine.write_text("@echo hello\r\n")
    with pytest.raises(EngineError):
        probe_engine(str(not_an_engine))
