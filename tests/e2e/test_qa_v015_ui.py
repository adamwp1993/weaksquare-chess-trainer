"""QA v0.15 (independent), against the mock: Open in Analysis tab from every way a puzzle can end, the replace-board
confirm, the set-up palette by dragging, popular replies when unavailable, and the White's-side wording. Invented
data only. A test exposing an open bug is xfail (strict) with its ID."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_analysis_tab_ui import analysis, board, calls, fen, same, wait_fen
from tests.e2e.test_engine_ui import WRONG, solve
from tests.e2e.test_engine_ui import start as start_puzzle
from tests.e2e.test_modes import LINE, enter, open_app, start_session
from tests.e2e.test_qa_v01_ui import your_turn

pytestmark = pytest.mark.e2e


def moves_in_tab(page: Any) -> int:
    return int(page.get_by_test_id("analysis-moves").locator("[data-move-id]").count())


def open_in_tab(page: Any) -> str:
    """Open the puzzle's analysis board, then Open in Analysis tab; returns the FEN the board showed."""
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-controls").wait_for()
    here = fen(page)
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-view").wait_for()
    return here


# ---- FR-14.6 from every way a puzzle ends ------------------------------------------------------------------------


def test_qa_open_in_tab_after_show_answer_stepped_into_the_answer(page: Any) -> None:
    start_puzzle(page)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()
    page.get_by_role("button", name="Forward").click()
    page.get_by_role("button", name="Forward").click()
    here = open_in_tab(page)
    assert same(fen(page), here)
    assert moves_in_tab(page) >= 3  # the opponent's move, then two answer moves
    page.get_by_test_id("analysis-back").click()
    assert not same(fen(page), here)


def test_qa_open_in_tab_after_try_again(page: Any) -> None:
    start_puzzle(page)
    solve(page)
    page.get_by_test_id("try-again").click()
    page.get_by_test_id("practice-badge").wait_for()
    your_turn(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("trainer-message").filter(has_text="practice, not scored").wait_for()
    here = open_in_tab(page)
    assert same(fen(page), here)
    assert moves_in_tab(page) == 4  # opponent, d5c3, the reply, c3d1: the practice run only, not twice


def test_qa_open_in_tab_carries_your_own_moves_and_the_cursor(page: Any) -> None:
    start_puzzle(page)
    solve(page)
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-controls").wait_for()
    import chess

    b = chess.Board(fen(page))
    move = next(iter(b.legal_moves)).uci()
    play(page, move, "black")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=analysis-moves]').innerText !== 'Make a move on the board.'"
    )
    here = fen(page)
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-view").wait_for()
    assert same(fen(page), here)
    assert moves_in_tab(page) == 5
    assert page.get_by_test_id("analysis-forward").is_disabled()  # the cursor is on your last move


def test_qa_b3_open_in_tab_from_commit_the_line(page: Any) -> None:
    open_app(page, "?mode=commit_line")
    start_session(page)
    enter(page, LINE)
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    here = open_in_tab(page)
    assert same(fen(page), here)
    # v0.15-B3, FR-14.6: the puzzle from its start: the opponent's move and the line you entered.
    assert moves_in_tab(page) >= 1 + len(LINE), f"only {moves_in_tab(page)} moves came with the position"


def test_qa_open_in_tab_from_danger_spotting_after_the_punishment(page: Any) -> None:
    open_app(page, "?mode=danger_spotting")
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("danger-call").wait_for()
    page.keyboard.press("s")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("danger-call").wait_for()
    page.get_by_test_id("danger-unsafe").click()
    page.get_by_test_id("trainer-message").filter(has_text="punish it").wait_for()
    play(page, "d4e2", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    here = open_in_tab(page)
    assert same(fen(page), here)
    assert moves_in_tab(page) >= 2  # the candidate, then your punishing move


# ---- FR-14.1: the replace-board confirm ---------------------------------------------------------------------------


def test_qa_new_board_asks_and_keep_or_escape_keeps_your_lines(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-new").click()  # no moves: no question
    assert page.get_by_test_id("analysis-confirm-keep").count() == 0
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-new").click()
    page.get_by_test_id("analysis-confirm-keep").click()
    page.get_by_test_id("analysis-move").filter(has_text="1. e4").wait_for()
    page.get_by_test_id("analysis-new").click()
    page.get_by_test_id("analysis-confirm-keep").wait_for()
    page.keyboard.press("Escape")
    page.get_by_test_id("analysis-confirm-keep").wait_for(state="detached")
    page.get_by_test_id("analysis-move").filter(has_text="1. e4").wait_for()
    page.get_by_test_id("analysis-new").click()
    page.get_by_test_id("analysis-confirm-replace").click()
    page.get_by_test_id("analysis-move").filter(has_text="Start").wait_for()
    assert moves_in_tab(page) == 0


def test_qa_keep_my_board_on_open_in_tab_is_not_asked_again(page: Any) -> None:
    analysis(page)
    play(page, "b2b3", "white")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-analyze-here").click()
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-confirm-keep").click()
    page.get_by_test_id("nav-studies").click()
    page.get_by_test_id("nav-analysis").click()
    page.get_by_test_id("analysis-move").filter(has_text="1. b3").wait_for()
    page.wait_for_timeout(300)
    assert page.get_by_test_id("analysis-confirm-keep").count() == 0


def test_qa_replace_on_open_in_tab_takes_the_game_position(page: Any) -> None:
    analysis(page)
    play(page, "b2b3", "white")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-next").click()
    page.get_by_test_id("review-analyze-here").click()
    page.get_by_test_id("review-free").wait_for()
    here = fen(page)
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-confirm-replace").click()
    page.wait_for_timeout(200)
    assert same(fen(page), here)
    assert "b3" not in page.get_by_test_id("analysis-moves").inner_text()


# ---- FR-14.2: the palette by dragging, and drag off to remove -----------------------------------------------------


def _square_centre(page: Any, square: str) -> tuple[float, float]:
    box = board(page).bounding_box()
    size = box["width"] / 8
    col = "abcdefgh".index(square[0])
    row = 8 - int(square[1])
    return box["x"] + (col + 0.5) * size, box["y"] + (row + 0.5) * size


def _drag(page: Any, frm: tuple[float, float], to: tuple[float, float]) -> None:
    page.mouse.move(*frm)
    page.mouse.down()
    page.mouse.move((frm[0] + to[0]) / 2, (frm[1] + to[1]) / 2, steps=5)
    page.mouse.move(*to, steps=5)
    page.mouse.up()


def test_qa_b2_set_up_by_dragging_from_the_palette_and_off_the_board(page: Any) -> None:
    """v0.15-B2: the palette row above the board moves it down, chessground keeps the old position, and the first
    piece dragged from the palette lands one rank too low (d3 for d4) until something presses on the board."""
    analysis(page)
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("analysis-setup-panel").wait_for()
    queen = page.get_by_test_id("spare-white-queen").bounding_box()
    _drag(page, (queen["x"] + queen["width"] / 2, queen["y"] + queen["height"] / 2), _square_centre(page, "d4"))
    page.wait_for_function("() => document.querySelector('[data-testid=board]:not([style*=none])') !== null")
    # Drag the a2 pawn off the board: it's removed.
    box = board(page).bounding_box()
    _drag(page, _square_centre(page, "a2"), (box["x"] + box["width"] + 200, box["y"] + box["height"] / 2))
    page.get_by_test_id("setup-done").click()
    page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
    assert fen(page) == "rnbqkbnr/pppppppp/8/8/3Q4/8/1PPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_qa_done_with_moves_replaces_the_board_as_the_panel_says(page: Any) -> None:
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-setup").click()
    panel = page.get_by_test_id("analysis-setup-panel")
    assert "Done replaces your current board" in panel.inner_text()
    page.get_by_test_id("setup-done").click()
    panel.wait_for(state="detached")
    assert moves_in_tab(page) == 0 and same(fen(page), "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")


def test_qa_arrow_keys_do_nothing_while_typing_a_fen_or_pgn(page: Any) -> None:
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill("1. d4")
    page.get_by_test_id("analysis-pgn-text").press("ArrowLeft")
    page.keyboard.press("Escape")
    page.get_by_test_id("analysis-move").filter(has_text="1. e4").wait_for()


# ---- FR-14.4: popular replies unavailable, White's-side wording -------------------------------------------------


def test_qa_popular_replies_unavailable_is_quiet_and_the_board_still_works(page: Any) -> None:
    analysis(page)
    page.evaluate(
        "() => { window.__mockApi.getPopularReplies = async () => ({ state: 'unavailable', total: 0, moves: [] }); }"
    )
    play(page, "d2d4", "white")
    page.get_by_test_id("popular-unavailable").wait_for()
    page.evaluate("() => { window.__mockApi.getPopularReplies = async () => { throw new Error('offline'); }; }")
    play(page, "d7d5", "white")
    page.get_by_test_id("popular-unavailable").wait_for()
    page.get_by_test_id("engine-line").first.wait_for()
    assert page.get_by_test_id("analysis-error").count() == 0


def test_qa_the_engine_panel_never_says_for_you_on_this_tab(page: Any) -> None:
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("engine-line").first.wait_for()
    text = page.get_by_test_id("analysis-view").inner_text()
    assert "for you" not in text and "You mate" not in text and "You're mated" not in text
    assert any(c.startswith("analyzeBoard:") for c in calls(page))
    wait_fen(page, "rnbqkbnr/pppppppp/8/8/4P3")


# ---- Visual check: the dialogs and a narrow window (screenshots in tests/e2e/artifacts, gitignored) --------------


def test_qa_screenshots_of_the_dialogs(page: Any) -> None:
    from pathlib import Path

    from tests.e2e.test_analysis_tab_ui import PGN, SECOND

    out = Path(__file__).parent / "artifacts"
    out.mkdir(exist_ok=True)
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill(PGN + "\n" + SECOND)
    page.get_by_test_id("analysis-pgn-read").click()
    page.get_by_test_id("analysis-pgn-games").wait_for()
    page.screenshot(path=str(out / "qa-v015-pgn-pick.png"))
    page.get_by_test_id("analysis-pgn-open").click()
    page.get_by_test_id("analysis-confirm-keep").wait_for()
    page.screenshot(path=str(out / "qa-v015-confirm.png"))
    page.get_by_test_id("analysis-confirm-replace").click()
    page.set_viewport_size({"width": 900, "height": 650})
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / "qa-v015-narrow.png"), full_page=True)
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("analysis-setup-panel").wait_for()
    page.screenshot(path=str(out / "qa-v015-narrow-setup.png"), full_page=True)


def test_qa_b4_the_app_name_is_readable_in_a_900_px_window(page: Any) -> None:
    """v0.15-B4: the self-check fix keeps the header on one line, but at 900 px the title shrinks to "W…"."""
    page.set_viewport_size({"width": 900, "height": 650})
    analysis(page)
    title = page.locator("header h3")
    assert title.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), title.inner_text()
