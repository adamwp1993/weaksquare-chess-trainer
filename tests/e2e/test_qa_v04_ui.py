"""QA v0.4: engine UI edge cases against the mock, plus screenshots of every v0.4 screen in Light and
Dark into tests/e2e/artifacts/qa-v04/ (gitignored) for the visual check. Written by the independent QA
pass (qa/QA-v0.4.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.e2e.test_engine_ui import WRONG, open_settings, solve, start

pytestmark = pytest.mark.e2e
ART = Path(__file__).resolve().parent / "artifacts" / "qa-v04"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(ART / f"{name}.png"), full_page=True)


def calls(page) -> list[str]:  # type: ignore[no-untyped-def]
    return page.evaluate("window.__mockApi.calls")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_qa_screenshots_of_every_v04_screen(page, scheme: str) -> None:  # type: ignore[no-untyped-def]
    q = f"?scheme={scheme}"
    start(page, q)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("refutation-label").filter(
        has_text="fails"
    ).wait_for()  # beside the answer since the v0.4 manual test
    page.get_by_test_id("refutation-show").click()
    page.get_by_test_id("line-preview").get_by_role("button", name="Forward").click()
    page.get_by_test_id("line-preview").get_by_role("button", name="Forward").click()
    page.get_by_test_id("engine-line").first.wait_for()
    shot(page, f"{scheme}-refutation-step2")

    start(page, q)
    solve(page)
    page.get_by_test_id("engine-line").first.wait_for()
    shot(page, f"{scheme}-engine-panel")
    page.get_by_test_id("analyze-button").click()
    fen = page.get_by_test_id("board").get_attribute("data-fen")
    move = next(iter(chess.Board(fen).legal_moves)).uci()
    play(page, move, "black")
    page.get_by_test_id("analysis-moves").filter(has_text=re.compile(r"[a-hNBRQKO]")).wait_for()
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=engine-thinking]')"
        " && document.querySelector('[data-testid=board]').getAttribute('data-arrows') !== ''"
    )
    shot(page, f"{scheme}-analysis-board")

    start(page, q + "&engine=missing")
    solve(page)
    page.get_by_test_id("engine-banner").wait_for()
    shot(page, f"{scheme}-install-banner")
    page.get_by_test_id("engine-install").click()
    page.get_by_test_id("engine-install-progress").wait_for()
    shot(page, f"{scheme}-install-progress")

    page.goto(page.base_url + "/" + q)
    open_settings(page)
    page.get_by_test_id("engine-in-use").wait_for()
    shot(page, f"{scheme}-settings-engine")
    page.goto(page.base_url + "/" + q + "&engine=custom")
    open_settings(page)
    page.get_by_test_id("engine-in-use").filter(has_text="your own engine").wait_for()
    shot(page, f"{scheme}-settings-custom-engine")

    page.goto(page.base_url + "/" + q)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="About").click()
    page.get_by_test_id("about-engine").wait_for()
    shot(page, f"{scheme}-about")


def test_qa_rapid_stepping_asks_about_the_newest_position_only(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    solve(page)
    page.get_by_test_id("engine-line").first.wait_for()
    page.get_by_test_id("answer-button").click()  # free after the end: replays the line
    page.get_by_test_id("answer-player").wait_for()
    page.wait_for_timeout(600)
    before = len([c for c in calls(page) if c == "analyze:panel"])
    for _ in range(3):
        page.get_by_role("button", name="Forward").click()
    for _ in range(2):
        page.get_by_role("button", name="Back").click()
    page.wait_for_timeout(1200)
    after = len([c for c in calls(page) if c == "analyze:panel"])
    assert after - before <= 1, calls(page)  # 5 steps in a burst: one request (debounced)
    page.get_by_test_id("engine-line").first.wait_for()
    assert page.get_by_test_id("engine-thinking").count() == 0


def test_qa_next_while_the_panel_is_thinking_leaks_nothing(page) -> None:  # type: ignore[no-untyped-def]
    """FR-7.3: an analysis still in flight when you move on never shows up on the next puzzle."""
    start(page, "?engine=slow")
    solve(page)
    page.get_by_test_id("engine-thinking").wait_for()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    page.wait_for_timeout(2000)  # the slow (1.5 s) answer has arrived by now
    no_engine_output_except_calls(page)


def no_engine_output_except_calls(page) -> None:  # type: ignore[no-untyped-def]
    for testid in ("engine-panel", "engine-line", "engine-start-eval", "answer-segment", "analyze-button"):
        assert page.get_by_test_id(testid).count() == 0, testid
    text = page.locator("body").inner_text()
    assert "for you" not in text and "You mate in" not in text and "Stockfish is thinking" not in text


def test_qa_next_while_the_refutation_loads(page) -> None:  # type: ignore[no-untyped-def]
    """The refutation request is in flight when you click Next: nothing from it shows on the next puzzle."""
    start(page, "?engine=slow")
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("refutation-loading").wait_for()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    page.wait_for_timeout(2000)
    no_engine_output_except_calls(page)
    assert page.get_by_test_id("refutation-loading").count() == 0


def test_qa_refutation_error_after_next_is_not_shown_on_the_next_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    page.evaluate(
        """() => { window.__mockApi.getRefutation = () => new Promise((_, reject) =>
             setTimeout(() => reject(new Error('Stockfish stopped unexpectedly and was restarted. Try again.')), 1200)); }"""
    )
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("refutation-loading").wait_for()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    page.wait_for_timeout(1800)
    assert page.get_by_test_id("refutation-error").count() == 0, page.get_by_test_id("refutation-error").inner_text()


def test_qa_analysis_board_underpromotion(page) -> None:  # type: ignore[no-untyped-def]
    """FR-7.7: promoting on the analysis board offers the piece choice, and a knight is a knight."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill("promotion")
    page.get_by_role("checkbox", name=re.compile("^Promotion")).check()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-player").wait_for()
    board = page.get_by_test_id("board")
    for _ in range(12):  # step to the position with the black pawn on a2, black to move
        b = chess.Board(board.get_attribute("data-fen"))
        if b.piece_at(chess.A2) == chess.Piece(chess.PAWN, chess.BLACK) and b.turn == chess.BLACK:
            break
        page.get_by_role("button", name="Forward").click()
        page.wait_for_timeout(150)
    else:
        pytest.fail("never reached a2 with black to move")
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-controls").wait_for()
    play(page, "a2a1", "black")
    page.get_by_role("button", name="Knight").click()
    page.get_by_test_id("analysis-moves").filter(has_text="=N").wait_for()
    after = chess.Board(board.get_attribute("data-fen"))
    assert after.piece_at(chess.A1) == chess.Piece(chess.KNIGHT, chess.BLACK)
    page.get_by_test_id("engine-line").first.wait_for()
    # exact: "Back to the answer" also matches "Back"
    page.get_by_role("button", name="Back", exact=True).last.click()
    assert chess.Board(board.get_attribute("data-fen")).piece_at(chess.A2) is not None
    page.get_by_test_id("analysis-close").click()
    page.get_by_test_id("answer-player").wait_for()  # back to the answer
