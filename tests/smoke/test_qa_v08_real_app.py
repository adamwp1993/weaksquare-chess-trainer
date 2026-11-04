"""QA v0.8 (independent) in the real app (WebView2 over CDP), on the fixture DB, a temp data folder and a copy
of the dev folder's real Stockfish: import a game as White, analyze it, Retry a mistake with the real
interactive engine, save a key moment, drill it from My puzzles (an off-line move goes to the engine
tolerance check), and try a Lichess-only mode with My puzzles chosen (v0.8-B4). Screenshots go to
tests/e2e/artifacts/ (gitignored)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v04_real_app import managed_install

pytestmark = pytest.mark.smoke

ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts"
# The Blackburne Shilling trap: you (White, player_x) blunder with 4.Nxe5 and 5.Nxf7.
TRAP = (
    '[White "player_x"]\n[Black "opponent_c"]\n[Result "0-1"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1\n"
)


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v08-real-{name}.png"))


def test_qa_v08_import_analyze_retry_save_and_drill_in_the_real_app(  # type: ignore[no-untyped-def]
    pw, tmp_path: Path, fixture_puzzles_db: Path, request
) -> None:
    data_dir = tmp_path / "app-data"
    (data_dir / "engines").mkdir(parents=True)
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(managed_install(request), data_dir / "engines" / "sf_19")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("nav-import-game").click()
            page.get_by_test_id("import-pgn-text").fill(TRAP)
            page.get_by_test_id("import-pgn").click()
            dialog = page.get_by_test_id("import-game-dialog")
            dialog.get_by_text("White", exact=True).click()
            page.get_by_test_id("import-color-ok").click()
            page.get_by_test_id("review-analyze").click()
            page.get_by_test_id("eval-graph").wait_for(timeout=90_000)
            page.get_by_test_id("key-moments").wait_for()
            shot(page, "review")

            # Retry: the first of your mistakes, any legal move; the real interactive engine grades it.
            page.get_by_test_id("retry-start").click()
            page.get_by_test_id("retry-mode").wait_for()
            assert page.get_by_test_id("retry-result").count() == 0  # no answer before you try
            play(page, "f3d4", "white")  # Nxd4 (legal in front of 4.Nxe5 and of 5.Nxf7)
            page.get_by_test_id("retry-result").wait_for(timeout=30_000)
            shot(page, "retry-result")
            page.get_by_test_id("retry-exit").click()

            # Save the first key moment and drill it as one of My puzzles.
            moment = page.locator("[data-testid^=save-]").first
            moment.click()
            page.get_by_test_id("saved-note").filter(has_text="Saved to My puzzles").wait_for()
            page.get_by_test_id("review-back").click()
            page.get_by_test_id("games-view").wait_for()
            page.get_by_test_id("nav-puzzles").click()
            page.get_by_test_id("source-select").get_by_text("My puzzles").click()
            page.get_by_test_id("match-count").filter(has_text="1 puzzle").wait_for(timeout=15_000)
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("puzzle-header").filter(has_text="my puzzle").wait_for(timeout=15_000)
            page.wait_for_timeout(800)
            conn = sqlite3.connect(data_dir / "user.db")
            try:
                fen, line = conn.execute("SELECT fen, solution_uci FROM custom_puzzles").fetchone()
            finally:
                conn.close()
            board = chess.Board(fen)
            off_line = next(m.uci() for m in board.legal_moves if m.uci() != line.split()[0])
            play(page, off_line, "white")  # not the saved move: the engine tolerance decides
            page.get_by_test_id("outcome").wait_for(timeout=30_000)
            shot(page, "my-puzzle-outcome")

            # v0.8-B4: Danger spotting locks the source control to "Lichess DB"...
            page.get_by_test_id("mode-control").get_by_text("Danger spotting", exact=True).click()
            page.wait_for_timeout(1500)
            shot(page, "locked-source")
            locked_error = page.get_by_text("Choose Lichess DB for this mode").count()
    finally:
        app.close()
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM game_analysis").fetchone()[0] == 14
        assert conn.execute("SELECT COUNT(*) FROM retry_attempts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT puzzle_source, sync_status, puzzle_rating FROM attempts ORDER BY id DESC LIMIT 1"
        ).fetchone() == ("my", "local", None)
        assert conn.execute("SELECT COUNT(*) FROM attempts WHERE sync_status != 'local'").fetchone()[0] == 0
    finally:
        conn.close()
    # ...but the running My-puzzles session can't switch to it (the record for the report).
    request.node.user_properties.append(("locked_source_error_shown", locked_error))
