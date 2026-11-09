"""QA v0.15 (independent), in the real app over CDP: PGN edge cases through the real python-chess parser, which the
mock client can't imitate. Fixture DB, temp data folder, signed out, no Stockfish. Invented data only."""

from __future__ import annotations

import shutil
from pathlib import Path

import chess
import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke

NESTED = '[Event "x"]\n\n1. e4 $1 e5 (1... c5 2. Nf3 (2. c3 d5) d6) 2. Nf3 {<b>bold</b> [%clk 0:01:00] note} Nc6 *\n'
NULL_IN_CHECK = "1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- 4. Qxe8 *\n"


def _import(page, text: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill(text)
    page.get_by_test_id("analysis-pgn-read").click()


def test_qa_pgn_edge_cases_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("nav-analysis").click()
            view = page.get_by_test_id("analysis-view")
            view.wait_for()
            board = view.get_by_test_id("board")

            # Nested side lines, glyphs and markup in a comment: shown as text, never as HTML.
            _import(page, NESTED)
            moves = page.get_by_test_id("analysis-moves")
            moves.get_by_text("c3").wait_for()
            text = moves.inner_text()
            assert "<b>bold</b>" in text and "clk" not in text and "e4!" in text
            assert moves.locator("b").count() == 0
            assert page.get_by_test_id("analysis-variation").count() >= 2

            # A bad PGN onto a board with moves: the error, and the board unchanged.
            before = board.get_attribute("data-fen")
            _import(page, "1. e4 e5 2. Ke3 *")
            page.get_by_test_id("analysis-pgn-error").filter(has_text="illegal or unreadable").wait_for()
            page.keyboard.press("Escape")
            assert board.get_attribute("data-fen") == before
            assert errors == []
    finally:
        app.close()


def test_qa_b1_a_null_move_in_check_never_puts_an_impossible_position_on_the_board(  # type: ignore[no-untyped-def]
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:
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
            _import(page, NULL_IN_CHECK)
            page.wait_for_timeout(1500)
            if page.get_by_test_id("analysis-pgn-error").count():
                return  # refused with a message: fixed
            for _ in range(8):
                page.keyboard.press("ArrowRight")
            page.wait_for_timeout(500)
            fen = str(board.get_attribute("data-fen"))
            assert chess.Board(fen).is_valid(), f"the board shows an impossible position: {fen}"
    finally:
        app.close()


def test_qa_r2_b2_a_palette_drag_lands_on_its_square_in_the_real_window(  # type: ignore[no-untyped-def]
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:
    """Round 2: real mouse drags in WebView2 from both palette rows, before any press on the board (v0.15-B2)."""
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
            page.get_by_test_id("analysis-setup").click()
            page.get_by_test_id("analysis-setup-panel").wait_for()
            page.get_by_test_id("setup-clear").click()  # a button, not a press on the board

            def drag(testid: str, file: int, rank: int) -> None:
                spare = page.get_by_test_id(testid)
                spare.scroll_into_view_if_needed()
                s = spare.bounding_box()
                box = view.get_by_test_id("board").bounding_box()
                assert s is not None and box is not None
                size = box["width"] / 8
                to = (box["x"] + (file + 0.5) * size, box["y"] + (8 - rank + 0.5) * size)
                page.mouse.move(s["x"] + s["width"] / 2, s["y"] + s["height"] / 2)
                page.mouse.down()
                page.mouse.move((s["x"] + to[0]) / 2, (s["y"] + to[1]) / 2, steps=5)
                page.mouse.move(*to, steps=5)
                page.mouse.up()
                page.wait_for_timeout(300)

            drag("spare-white-king", 3, 4)  # d4, the first drag
            drag("spare-black-king", 5, 6)  # f6, from the other row
            drag("spare-white-queen", 0, 1)  # a1
            assert view.get_by_test_id("board").get_attribute("data-fen") == "8/8/5k2/8/3K4/8/8/Q7"
            page.get_by_test_id("setup-done").click()
            page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
            assert view.get_by_test_id("board").get_attribute("data-fen") == "8/8/5k2/8/3K4/8/8/Q7 w - - 0 1"
    finally:
        app.close()
