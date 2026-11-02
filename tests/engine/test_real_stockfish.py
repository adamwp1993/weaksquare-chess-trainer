"""The real Stockfish 19 (v0.4 Done when): known positions give the expected best move, the probe
passes, and invalid input sent past validation gets one restart and a clean error, not a hang."""

from __future__ import annotations

import logging
import time

import chess
import pytest

from weaksquare.adapters.stockfish import StockfishEngine, probe_engine
from weaksquare.core.engine import EngineError

pytestmark = pytest.mark.engine


@pytest.fixture
def engine(stockfish_path: str):  # type: ignore[no-untyped-def]
    e = StockfishEngine(stockfish_path, threads=2, hash_mb=32)
    yield e
    e.close()


def test_probe_reports_stockfish_19(stockfish_path: str) -> None:
    assert probe_engine(stockfish_path).name.startswith("Stockfish 19")


def test_mate_in_one(engine: StockfishEngine) -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")  # back rank: Ra8#
    best = engine.analyse(board, 0.5, 1)[0]
    assert best.pv[0] == "a1a8" and best.mate == 1


def test_takes_a_hanging_queen(engine: StockfishEngine) -> None:
    board = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")  # Rxd5 wins the queen
    best = engine.analyse(board, 0.5, 1)[0]
    assert best.pv[0] == "d2d5"
    assert (best.mate is not None and best.mate > 0) or (best.cp is not None and best.cp > 300)  # K+R v K: often a mate


def test_multipv_gives_three_distinct_lines(engine: StockfishEngine) -> None:
    lines = engine.analyse(chess.Board(), 0.5, 3)
    assert len(lines) == 3 and len({line.pv[0] for line in lines}) == 3


def test_black_to_move_scores_are_white_relative(engine: StockfishEngine) -> None:
    board = chess.Board("r5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1")  # Black mates with Ra1#
    best = engine.analyse(board, 0.5, 1)[0]
    assert best.pv[0] == "a8a1" and best.mate == -1


def test_invalid_input_restarts_once_and_fails_cleanly(engine: StockfishEngine, caplog) -> None:  # type: ignore[no-untyped-def]
    """FR-7.6: Stockfish 19 exits on an invalid position. Sent past validation on purpose here."""
    engine.analyse(chess.Board(), 0.2, 1)
    caplog.set_level(logging.INFO, logger="weaksquare")
    started = time.monotonic()
    with pytest.raises(EngineError) as e:
        engine.analyse(chess.Board("8/8/8/8/8/8/8/8 w - - 0 1"), 0.2, 1)
    assert time.monotonic() - started < 15
    assert e.value.code == "engine_crashed"
    logged = [r.getMessage() for r in caplog.records]
    assert sum("engine restarted" in m for m in logged) == 1
    print("\n".join(m for m in logged if "terminated" in m))
    assert engine.analyse(chess.Board(), 0.2, 1)[0].pv  # the next request works
