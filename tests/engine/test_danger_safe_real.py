"""Danger spotting with the real Stockfish 19 (v0.6, FR-4.4, FR-7.2): every safe candidate the 50 cp rule picks
really is safe when Stockfish looks at the position after it, and the real blunder never qualifies."""

from __future__ import annotations

import chess
import pytest

from tests.helpers import fixture_rows
from weaksquare.adapters.stockfish import StockfishEngine
from weaksquare.core.engine import score_for, validate_fen
from weaksquare.core.modes.danger import MAX_LOSS_CP, MULTIPV, ScoredMove, safe_candidates

pytestmark = pytest.mark.engine

THINK_S = 0.5
NOISE_CP = 40  # two separate searches of nearby positions don't agree to the centipawn
PUZZLES = 8


@pytest.fixture
def engine(stockfish_path: str):  # type: ignore[no-untyped-def]
    e = StockfishEngine(stockfish_path, threads=2, hash_mb=32)
    yield e
    e.close()


def _value(cp: int | None, mate: int | None) -> int:
    if mate is not None:
        return 100_000 - abs(mate) if mate > 0 else -100_000 + abs(mate)
    assert cp is not None
    return cp


def test_picked_safe_moves_hold_up_on_a_second_look(engine: StockfishEngine) -> None:
    checked = 0
    for row in fixture_rows()[:PUZZLES]:
        board = validate_fen(row["FEN"])
        mover = "white" if board.turn == chess.WHITE else "black"
        blunder = row["Moves"].split()[0]
        lines = engine.analyse(board.copy(), THINK_S, MULTIPV)
        scored = []
        for line in lines:
            cp, mate = score_for(line, mover)  # type: ignore[arg-type]
            scored.append(ScoredMove(line.pv[0], cp, mate))
        best = max(_value(m.cp, m.mate) for m in scored)
        safe = safe_candidates(scored, blunder)
        assert blunder not in {m.move for m in safe}
        for m in safe:
            after = board.copy()
            after.push_uci(m.move)
            if after.is_game_over():
                continue
            reply = engine.analyse(after, THINK_S, 1)[0]
            cp, mate = score_for(reply, mover)  # type: ignore[arg-type]
            assert mate is None or mate > 0, f"{row['PuzzleId']}: {m.move} allows a mate"
            assert best - _value(cp, mate) <= MAX_LOSS_CP + NOISE_CP, f"{row['PuzzleId']}: {m.move} isn't safe"
            checked += 1
    assert checked > 0, "no safe candidates in the fixture positions"
