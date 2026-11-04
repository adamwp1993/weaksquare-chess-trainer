"""v0.10 puzzles from your games with the real Stockfish 19 (`uv run pytest -m engine`): the ported
lichess-puzzler check keeps a clean back-rank mate and rejects a quiet opening position."""

from __future__ import annotations

import chess
import pytest

from tests.engine.test_game_analysis_real import real_services  # noqa: F401 - fixture
from weaksquare.core.puzzle_gen import PovScore, check_position

pytestmark = pytest.mark.engine


def _check(s, fen: str):  # type: ignore[no-untyped-def]
    board = chess.Board(fen)
    first = s.engine.analyse_background(board, 1.0, 3)
    return check_position(fen, first, PovScore(cp=0), lambda b, n: s.engine.analyse_background(b, 1.0, n))


def test_a_back_rank_mate_is_a_clean_puzzle(real_services) -> None:  # noqa: F811
    s, _ = real_services
    v = _check(s, "6k1/5ppp/7q/8/8/8/5PPP/3R2K1 w - - 0 1")
    assert v.passed, v.reason
    assert v.line == ("d1d8",)


def test_a_quiet_opening_position_is_not_a_puzzle(real_services) -> None:  # noqa: F811
    s, _ = real_services
    v = _check(s, "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    assert not v.passed and v.reason in ("no_tactic", "not_only_move")
