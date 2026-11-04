"""v0.8 in the real app (WebView2 over CDP), on the fixture DB, a temp data folder and the dev folder's
real Stockfish: paste a game, say which side you played, analyze it on the background engine, read the
review (eval graph, key moments, the blunder and its refutation), save a moment as a puzzle, and find it
under My games. No account is linked, so nothing is synced."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v04_real_app import managed_install

pytestmark = pytest.mark.smoke

# Black's 3...Nf6?? walks into 4.Qxf7#.
SCHOLAR = '[White "opponent_b"]\n[Black "player_x"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'


def test_paste_analyze_review_and_save_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path, request) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    (data_dir / "engines").mkdir(parents=True)
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(managed_install(request), data_dir / "engines" / "sf_19")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("nav-games").click()
            page.get_by_test_id("games-empty").wait_for()
            page.get_by_test_id("games-refresh").click()
            page.get_by_test_id("games-notice").filter(
                has_text="link a chess.com username"
            ).wait_for()  # nothing linked
            page.get_by_test_id("games-import").click()
            page.get_by_test_id("import-pgn-text").fill(SCHOLAR)
            page.get_by_test_id("import-pgn").click()
            dialog = page.get_by_test_id("import-game-dialog")
            dialog.get_by_text("Black", exact=True).click()
            page.get_by_test_id("import-color-ok").click()
            page.get_by_test_id("review-analyze").click()
            page.get_by_test_id("eval-graph").wait_for(timeout=60_000)
            moment = page.get_by_test_id("moment-5")
            moment.wait_for()
            assert "Played Nf6??" in moment.inner_text()
            page.get_by_test_id("move-5").click()
            assert "Blunder" in page.get_by_test_id("review-current").inner_text().title()
            page.get_by_test_id("review-refutation").click()
            page.get_by_test_id("answer-player").wait_for()
            page.get_by_test_id("save-5").click()
            page.get_by_test_id("saved-note").filter(has_text="Saved to My puzzles").wait_for()
            page.get_by_test_id("review-back").click()
            page.get_by_test_id("games-count").filter(has_text="1 game").wait_for()
            row = page.get_by_test_id("game-row-1").inner_text().lower()
            assert "analyzed" in row and "not analyzed" not in row
    finally:
        app.close()
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM game_analysis WHERE game_id = 1").fetchone() == (7,)
        assert conn.execute("SELECT classification, kind FROM game_analysis WHERE ply = 5").fetchone() == (
            "blunder",
            "allowed",
        )
        assert conn.execute("SELECT analysis_status, analysis_engine FROM games").fetchone()[0] == "analyzed"
        assert conn.execute("SELECT origin, strict, player_color FROM custom_puzzles").fetchone() == (
            "manual",
            0,
            "black",
        )
        assert conn.execute("SELECT COUNT(*) FROM account_sync").fetchone() == (0,)
    finally:
        conn.close()
