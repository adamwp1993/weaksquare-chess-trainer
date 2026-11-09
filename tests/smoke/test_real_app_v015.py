"""v0.15 in the real app (WebView2 over CDP), on the fixture DB and a temp data folder, signed out and without
Stockfish: the Analysis tab opens at the start, a FEN and a PGN go through the real bridge, an impossible position is
refused with its reason, popular replies say Sign in, and the engine panel offers to install Stockfish. Nothing is
sent anywhere."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PGN = '[White "player_a"]\n[Black "opponent_b"]\n\n1. e4 {A plain note} e5 (1... c5 2. Nf3) 2. Nf3 *\n'


def _games(data_dir: Path) -> int:
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        return int(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    finally:
        conn.close()


def test_the_analysis_tab_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("nav-analysis").click()
            view = page.get_by_test_id("analysis-view")
            view.wait_for()
            board = view.get_by_test_id("board")
            assert board.get_attribute("data-fen") == START
            page.get_by_test_id("popular-signed-out").wait_for()  # signed out: skipped cleanly
            page.get_by_test_id("engine-banner").wait_for()  # no Stockfish in this data folder

            # The real bridge refuses an impossible position with its reason.
            r = page.evaluate("window.pywebview.api.check_board_position('4k3/8/8/8/8/8/4R3/4K3 w - - 0 1')")
            assert r["ok"] and r["data"]["ok"] is False and "in check" in r["data"]["problems"][0]
            r = page.evaluate("window.pywebview.api.analyze_board_position('8/8/8/8/8/8/8/8 w - - 0 1', 'board')")
            assert r["ok"] is False and "empty" in r["error"]["message"]

            # A FEN through the set-up panel.
            page.get_by_test_id("analysis-setup").click()
            page.get_by_test_id("setup-fen").fill("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")
            page.get_by_test_id("setup-fen-use").click()
            page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
            assert board.get_attribute("data-fen") == "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"

            # A PGN with a side line: it replaces the board after asking, and isn't added to My games.
            before = _games(data_dir)
            page.get_by_test_id("analysis-import-pgn").click()
            page.get_by_test_id("analysis-pgn-text").fill(PGN)
            page.get_by_test_id("analysis-pgn-read").click()
            moves = page.get_by_test_id("analysis-moves")
            moves.get_by_text("c5").wait_for()
            assert "A plain note" in moves.inner_text()
            assert board.get_attribute("data-fen") == START
            assert _games(data_dir) == before
    finally:
        app.close()
