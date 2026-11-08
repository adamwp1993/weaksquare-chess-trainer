"""v0.15 manual test M2 (Adam): text in the app can be selected and copied. pywebview turns text selection off for
the whole page unless the window asks for it; the board keeps its own user-select: none, so dragging pieces never
highlights anything."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke


def test_text_is_selectable_but_not_the_board(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            assert page.evaluate("getComputedStyle(document.body).userSelect") != "none"
            # Selecting the page really selects text (what Ctrl+C copies).
            page.evaluate("document.execCommand('selectAll')")
            assert "puzzles match" in page.evaluate("String(window.getSelection())")
            # The board doesn't: open the Analysis tab, where one is always drawn.
            page.get_by_test_id("nav-analysis").click()
            board = page.get_by_test_id("analysis-view").locator("cg-board")
            board.wait_for()
            assert board.evaluate("el => getComputedStyle(el).userSelect") == "none"
    finally:
        app.close()
