"""QA v0.4 rc2 (Adam's manual-test changes) against the mock: how Show me, Show answer re-opening, the
analysis board's "Back to the answer" and Try again interact with each other and with the keyboard;
FR-7.3 during a practice run; screenshots into tests/e2e/artifacts/qa-v04-rc2/ (gitignored).
Written by the independent QA pass (qa/QA-v0.4.md)."""

from __future__ import annotations

from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.e2e.test_engine_ui import WRONG, counts, solve, start

pytestmark = pytest.mark.e2e
ART = Path(__file__).resolve().parent / "artifacts" / "qa-v04-rc2"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(ART / f"{name}.png"), full_page=True)


def calls(page) -> list[str]:  # type: ignore[no-untyped-def]
    return page.evaluate("window.__mockApi.calls")


def fen(page) -> str:  # type: ignore[no-untyped-def]
    return page.get_by_test_id("board").get_attribute("data-fen")


def lost_with_answer(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    start(page, query)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()
    page.get_by_test_id("refutation-label").wait_for()
    page.get_by_test_id("engine-line").first.wait_for()


def test_qa_show_me_then_show_answer_returns_to_the_solution_start(page) -> None:  # type: ignore[no-untyped-def]
    lost_with_answer(page)
    answer_start = fen(page)
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert page.get_by_test_id("answer-step").inner_text().startswith("2/")
    on_step2 = fen(page)
    page.get_by_test_id("engine-line").first.wait_for()
    page.get_by_test_id("show-line").first.click()
    preview = page.get_by_test_id("line-preview")
    preview.wait_for()
    assert fen(page) == on_step2  # nothing moves until you step
    page.keyboard.press("ArrowRight")  # arrows step the line, not the answer
    assert preview.get_by_test_id("answer-step").inner_text().startswith("1/")
    assert fen(page) != on_step2
    shot(page, "show-me-on-the-answer")
    page.keyboard.press("a")  # Show answer re-opens (FR-5.4): back to the start of the solution
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()
    assert page.get_by_test_id("line-preview").count() == 0
    assert page.get_by_test_id("answer-step").inner_text() == "Start"
    assert fen(page) == answer_start
    page.keyboard.press("ArrowRight")  # arrows step the answer again
    assert page.get_by_test_id("answer-step").inner_text().startswith("1/")


def test_qa_done_returns_to_the_answer_step(page) -> None:  # type: ignore[no-untyped-def]
    lost_with_answer(page)
    page.keyboard.press("ArrowRight")
    on_step1 = fen(page)
    page.get_by_test_id("refutation-show").click()  # the refutation's own Show me
    preview = page.get_by_test_id("line-preview")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    assert preview.get_by_test_id("answer-step").inner_text().startswith("3/")
    for _ in range(9):  # past both ends: clamped
        page.keyboard.press("ArrowLeft")
    assert preview.get_by_test_id("answer-step").inner_text() == "Start"
    page.get_by_test_id("line-preview-done").click()
    assert fen(page) == on_step1
    assert page.get_by_test_id("answer-step").inner_text().startswith("1/")


def test_qa_show_me_on_the_analysis_board_then_back_to_the_answer(page) -> None:  # type: ignore[no-untyped-def]
    lost_with_answer(page)
    page.keyboard.press("ArrowRight")
    page.get_by_test_id("analyze-button").click()
    close = page.get_by_test_id("analysis-close")
    assert close.inner_text() == "Back to the answer"
    move = next(iter(chess.Board(fen(page)).legal_moves)).uci()
    play(page, move, "black")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=analysis-moves]').innerText !== 'Make a move on the board.'"
    )
    page.get_by_test_id("engine-line").first.wait_for()
    page.get_by_test_id("show-line").first.click()
    page.get_by_test_id("line-preview").wait_for()
    assert page.get_by_test_id("board").get_attribute("data-arrows") == ""  # no arrow while showing a line
    page.get_by_test_id("answer-button").click()  # re-open: closes the analysis board and the line
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()
    assert page.get_by_test_id("analysis-controls").count() == 0
    assert page.get_by_test_id("line-preview").count() == 0
    assert page.get_by_test_id("answer-step").inner_text() == "Start"
    # and the Close label without an answer: a solved puzzle
    start(page)
    solve(page)
    page.get_by_test_id("analyze-button").click()
    assert page.get_by_test_id("analysis-close").inner_text() == "Close"
    page.get_by_test_id("analysis-close").click()
    page.get_by_test_id("analyze-button").wait_for()


def test_qa_try_again_hides_the_engine_and_records_nothing(page) -> None:  # type: ignore[no-untyped-def]
    """FR-5.12 + FR-7.3: during a practice run nothing from the engine is visible or even requested;
    a wrong move, a hint and Next record nothing."""
    start(page)
    page.keyboard.press("r")  # before the end: nothing
    page.wait_for_timeout(300)
    assert not [c for c in calls(page) if "retry" in c.lower()]
    assert page.get_by_test_id("try-again").count() == 0
    solve(page)
    page.get_by_test_id("engine-line").first.wait_for()
    page.get_by_test_id("show-line").first.click()  # a Show me line open when Try again is pressed
    bar = counts(page)
    page.keyboard.press("r")
    page.get_by_test_id("practice-badge").wait_for()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn again").wait_for()
    n_analyze = len([c for c in calls(page) if c.startswith("analyze:") or c == "refutation"])
    for testid in ("engine-panel", "engine-line", "line-preview", "refutation", "analyze-button"):
        assert page.get_by_test_id(testid).count() == 0, testid
    assert "for you" not in page.locator("body").inner_text()
    shot(page, "practice-start")
    play(page, WRONG, "black")
    page.get_by_test_id("trainer-message").filter(has_text="practice, not scored").wait_for()
    page.wait_for_timeout(500)
    page.keyboard.press("h")
    page.wait_for_timeout(500)
    for testid in ("engine-panel", "engine-line", "refutation"):
        assert page.get_by_test_id(testid).count() == 0, testid
    after = [c for c in calls(page) if c.startswith("analyze:") or c == "refutation"]
    assert len(after) == n_analyze, after  # no engine request during the practice run
    assert counts(page) == bar
    assert page.get_by_test_id("outcome").filter(has_text="Solved").count() == 1  # the first result stays
    shot(page, "practice-after-wrong-and-hint")
    page.get_by_test_id("next-button").click()  # skipping a practice run records nothing
    page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 2").wait_for()
    page.wait_for_timeout(1000)
    assert counts(page) == bar  # (1 solved, 0 failed): the skipped practice run isn't a failure
