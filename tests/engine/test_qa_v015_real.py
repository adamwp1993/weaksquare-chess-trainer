"""QA v0.15 against the real Stockfish 19 (`uv run pytest -m engine`): the Analysis tab's service on awkward but
legal positions (FR-14.2, 14.4). Each must come back with White's-side wording and never crash the engine."""

from __future__ import annotations

from typing import Any

import pytest

from tests.engine.test_qa_v04_real_engine import real_services  # noqa: F401  (fixture)
from weaksquare.services.analysis_tab import AnalysisTabService

pytestmark = pytest.mark.engine


class _NoSources:
    def signed_in(self) -> bool:
        return False

    def fetch_explorer(self, board: Any) -> None:
        return None


@pytest.mark.parametrize(
    "fen",
    [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w HAha - 0 1",  # Shredder castling letters
        "rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",  # en passant available
        "4k3/8/8/8/8/8/8/4K3 w - - 0 1",  # bare kings
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",  # stalemate
        "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",  # checkmate
        "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",  # promotion next
        "k7/8/8/8/8/8/8/1QQQQQQK w - - 0 1",  # many queens, legal
    ],
)
def test_qa_awkward_legal_positions_analyze_from_whites_side(real_services: Any, fen: str) -> None:  # noqa: F811
    svc = AnalysisTabService(real_services.engine, _NoSources())
    a = svc.analyze(fen, "board")
    texts = [line.score for line in a.lines] + ([a.game_over] if a.game_over else [])
    assert all("you" not in t.lower() for t in texts), texts
    again = svc.analyze("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "board")
    assert again.lines  # the engine is still alive
