"""v0.4 engine UI against the mock: FR-7.3 (nothing while solving), the refutation in Show answer
(§7.2 step 2), the post-puzzle panel and the analysis board (FR-7.2, 7.7), Install (FR-7.5),
Settings → Engine (FR-7.4) and About (NFR-7).

The mock serves DtKOy first: you play black; the solution is d5c3 (then b1b5) c3d1.
"""

from __future__ import annotations

import re

import chess
import pytest

from tests.e2e.conftest import play
from tests.e2e.test_qa_v01_ui import your_turn

pytestmark = pytest.mark.e2e

WRONG = "h7h6"  # legal for black at the start, not the solution, no check


def start(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    your_turn(page)


def solve(page) -> None:  # type: ignore[no-untyped-def]
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


def no_engine_output(page) -> None:  # type: ignore[no-untyped-def]
    for testid in ("engine-panel", "engine-line", "engine-start-eval", "answer-segment", "analyze-button"):
        assert page.get_by_test_id(testid).count() == 0, testid
    text = page.locator("body").inner_text()
    assert "for you" not in text and "You mate in" not in text and "Stockfish is thinking" not in text
    calls = page.evaluate("window.__mockApi.calls")
    assert not [c for c in calls if c.startswith("analyze:") or c == "refutation"], calls


def test_no_eval_or_lines_while_solving(page) -> None:  # type: ignore[no-untyped-def]
    """FR-7.3 (v0.4 Done when): at the start, after a correct move, after a wrong move, after a hint."""
    start(page)
    no_engine_output(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    no_engine_output(page)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()  # decided, still in progress
    page.wait_for_timeout(500)
    no_engine_output(page)
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Hint").wait_for()
    page.wait_for_timeout(500)
    no_engine_output(page)


def test_panel_appears_after_the_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    solve(page)
    panel = page.get_by_test_id("engine-panel")
    panel.wait_for()
    page.get_by_test_id("engine-start-eval").filter(has_text=re.compile("for you|You mate|level")).wait_for()
    page.get_by_test_id("engine-line").first.wait_for()
    assert page.get_by_test_id("engine-line").count() == 3  # MultiPV 3 (FR-7.2)
    first = page.get_by_test_id("engine-line").first.inner_text()
    assert re.search(r"(for you|level|You mate|mated)", first) and re.search(r"\d+\.", first)  # eval + SAN


def test_show_answer_is_the_solution_with_the_refutation_beside_it(page) -> None:  # type: ignore[no-untyped-def]
    """Show answer always shows the correct solution; "Why h6 fails" sits above it with its own Show me
    (Adam, v0.4 manual test: the answer used to start with the refutation)."""
    start(page)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()
    assert page.get_by_test_id("answer-step").inner_text() == "Start"
    page.get_by_role("button", name="Forward").click()
    assert page.get_by_test_id("answer-step").inner_text().startswith("1/3: N")  # d5c3, the correct move
    label = page.get_by_test_id("refutation-label")
    label.filter(has_text="Why h6 fails").wait_for()
    assert "for you" in label.inner_text() or "mate" in label.inner_text()
    page.get_by_test_id("engine-panel").wait_for()  # Show answer ended the puzzle: the panel is allowed now
    board = page.get_by_test_id("board")
    on_answer = board.get_attribute("data-fen")
    page.get_by_test_id("refutation-show").click()
    preview = page.get_by_test_id("line-preview")
    preview.get_by_role("button", name="Forward").click()
    assert "h6" in preview.get_by_test_id("answer-step").inner_text()  # your move, then Stockfish's reply
    page.get_by_test_id("line-preview-done").click()
    assert board.get_attribute("data-fen") == on_answer
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()


def test_no_refutation_segment_without_a_wrong_move(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-player").wait_for()
    page.wait_for_timeout(500)
    assert page.get_by_test_id("refutation").count() == 0


def test_analysis_board(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    solve(page)
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-controls").wait_for()
    board = page.get_by_test_id("board")
    fen = board.get_attribute("data-fen")
    move = next(iter(chess.Board(fen).legal_moves)).uci()  # white to move after the solution
    play(page, move, "black")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=analysis-moves]').innerText !== 'Make a move on the board.'"
    )  # the move landed (the placeholder also has letters, so wait for it to change)
    assert board.get_attribute("data-fen") != fen
    page.get_by_test_id("engine-line").first.wait_for()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=board]').getAttribute('data-arrows') !== ''"
    )  # the best move's arrow
    arrow = board.get_attribute("data-arrows").split()[0]
    assert chess.Move.from_uci(arrow) in chess.Board(board.get_attribute("data-fen")).legal_moves
    page.get_by_test_id("analysis-reset").click()
    assert page.get_by_test_id("analysis-moves").inner_text() == "Make a move on the board."
    page.get_by_test_id("analysis-close").click()
    page.get_by_test_id("analyze-button").wait_for()
    assert board.get_attribute("data-arrows") == ""
    assert "Solved 1" in page.get_by_test_id("session-bar").inner_text()  # nothing on the board is scored


def test_install_banner_then_install(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?engine=missing")
    solve(page)
    banner = page.get_by_test_id("engine-banner")
    banner.filter(has_text="Stockfish isn't installed").wait_for()
    page.get_by_test_id("engine-install").click()
    page.get_by_test_id("engine-install-progress").wait_for()
    page.get_by_test_id("engine-panel").wait_for(timeout=5000)
    page.get_by_test_id("engine-line").first.wait_for()


def test_refutation_spot_shows_the_banner_when_not_installed(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?engine=missing")
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("engine-banner").wait_for()
    page.get_by_test_id("answer-player").wait_for()  # the solution still shows


def open_settings(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("gear").click()
    page.get_by_test_id("engine-settings").wait_for()


def test_settings_engine_section(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    open_settings(page)
    page.get_by_test_id("engine-in-use").filter(has_text="Stockfish 19").wait_for()
    threads = page.get_by_test_id("engine-threads")
    assert threads.input_value() == "7"  # CPU cores − 1 (FR-7.4)
    assert page.get_by_test_id("engine-hash").input_value() == "256"
    page.get_by_test_id("engine-think").fill("2.5")
    page.get_by_test_id("engine-think").blur()
    page.wait_for_function("() => window.__mockApi.calls.some(c => c.includes('think_s'))")
    page.get_by_test_id("engine-choose").click()
    page.get_by_test_id("engine-job-result").filter(has_text="Using Stockfish 18").wait_for()
    page.get_by_test_id("engine-in-use").filter(has_text="your own engine").wait_for()
    page.get_by_test_id("engine-use-managed").click()
    page.get_by_test_id("engine-in-use").filter(has_text="managed").wait_for()


def test_about_shows_stockfish(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="About").click()
    page.get_by_test_id("about-engine").filter(has_text="Stockfish 19 (sf_19)").wait_for()
    assert "stockfish.exe" in page.get_by_test_id("about-engine").inner_text()


def test_show_answer_closes_the_analysis_board(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    solve(page)
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-controls").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-player").wait_for()
    assert page.get_by_test_id("analysis-controls").count() == 0
    page.get_by_test_id("analyze-button").wait_for()


def test_a_refused_setting_snaps_back(page) -> None:  # type: ignore[no-untyped-def]
    """Regression (v0.4-B7): an out-of-range value shows the error and the box returns to the saved value."""
    page.goto(page.base_url + "/")
    open_settings(page)
    think = page.get_by_test_id("engine-think")
    think.fill("50")
    think.blur()
    page.get_by_test_id("engine-settings-error").filter(has_text="between 0.2 and 10").wait_for()
    page.wait_for_function("() => document.querySelector('[data-testid=engine-think]').value === '1'")


def test_about_shows_a_missing_custom_engine(page) -> None:  # type: ignore[no-untyped-def]
    """Regression (v0.4-B6): About says the custom engine can't be found instead of "Not installed"."""
    page.goto(page.base_url + "/?engine=custom_missing")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="About").click()
    page.get_by_test_id("about-engine").filter(has_text="can't be found").wait_for()


def test_show_me_steps_through_a_line_on_the_board(page) -> None:  # type: ignore[no-untyped-def]
    """FR-7.7 "Show me" (added during v0.4's manual test): each engine line can be stepped through on the
    board, read-only, starting at the position it came from; Done returns to that position."""
    start(page)
    solve(page)
    page.get_by_test_id("engine-line").first.wait_for()
    board = page.get_by_test_id("board")
    before = board.get_attribute("data-fen")
    first_line = page.get_by_test_id("engine-line").first.inner_text()
    page.get_by_test_id("show-line").first.click()
    preview = page.get_by_test_id("line-preview")
    preview.wait_for()
    assert preview.get_by_test_id("answer-segment").inner_text().startswith("Showing: ")
    first_san = first_line.split(". ", 1)[1].split()[0]  # "+1.2 for you 28. Rb8 …" -> "Rb8"
    assert first_san in preview.get_by_test_id("answer-segment").inner_text()
    assert preview.get_by_test_id("answer-step").inner_text() == "Start"
    assert board.get_attribute("data-fen") == before  # nothing moves until you step
    preview.get_by_role("button", name="Forward").click()
    assert preview.get_by_test_id("answer-step").inner_text().startswith("1/")
    assert first_san in preview.get_by_test_id("answer-step").inner_text()
    after_one = board.get_attribute("data-fen")
    assert after_one != before
    move = chess.Move.from_uci(next(iter(chess.Board(after_one).legal_moves)).uci())
    play(page, move.uci(), "black")  # the board is read-only while showing a line
    page.wait_for_timeout(300)
    assert board.get_attribute("data-fen") == after_one
    page.keyboard.press("ArrowRight")  # → steps the line too
    assert preview.get_by_test_id("answer-step").inner_text().startswith("2/")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    assert preview.get_by_test_id("answer-step").inner_text() == "Start"
    page.get_by_test_id("line-preview-done").click()
    assert page.get_by_test_id("line-preview").count() == 0
    assert board.get_attribute("data-fen") == before
    assert page.get_by_test_id("engine-line").first.inner_text() == first_line  # the panel didn't change


def test_show_me_on_the_analysis_board(page) -> None:  # type: ignore[no-untyped-def]
    """Show me also works on the analysis board; Done returns to your analysis position, where you can
    keep moving."""
    start(page)
    solve(page)
    page.get_by_test_id("analyze-button").click()
    board = page.get_by_test_id("board")
    play(page, "b5b8", "black")  # Rb8 on the analysis board
    page.get_by_test_id("analysis-moves").filter(has_text="Rb8").wait_for()
    analysed = board.get_attribute("data-fen")
    page.get_by_test_id("engine-line").first.wait_for()
    page.get_by_test_id("show-line").first.click()
    page.get_by_test_id("line-preview").get_by_role("button", name="Forward").click()
    assert board.get_attribute("data-fen") != analysed
    assert board.get_attribute("data-arrows") == ""  # no best-move arrow over a line being shown
    page.get_by_test_id("line-preview-done").click()
    assert board.get_attribute("data-fen") == analysed
    page.get_by_test_id("analysis-controls").wait_for()
    assert page.get_by_test_id("analysis-moves").inner_text() == "Rb8"


# ---- Adam's v0.4 manual-test requests: Show answer again, Back to the answer, Try again (FR-5.4, 5.12) ----


def test_show_answer_reopens_from_the_analysis_board(page) -> None:  # type: ignore[no-untyped-def]
    """FR-5.4: after the end, Show answer stays clickable and goes back to the start of the answer,
    closing the analysis board; the analysis board's Close says "Back to the answer"."""
    start(page)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("refutation-label").filter(has_text="Why h6 fails").wait_for()
    page.get_by_role("button", name="Forward").click()
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-close").filter(has_text="Back to the answer").wait_for()
    assert page.get_by_test_id("answer-player").count() == 0
    assert page.get_by_test_id("answer-button").is_enabled()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-player").wait_for()
    assert page.get_by_test_id("analysis-controls").count() == 0
    page.get_by_test_id("answer-segment").filter(has_text="The solution").wait_for()
    assert page.get_by_test_id("answer-step").inner_text() == "Start"
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-close").click()  # Back to the answer
    page.get_by_test_id("answer-player").wait_for()


def counts(page) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """The session's Solved / Failed counts (the rating total changes when the mock's sync lands)."""
    return (page.get_by_test_id("stat-solved").inner_text(), page.get_by_test_id("stat-failed").inner_text())


def test_try_again_is_practice_and_records_nothing(page) -> None:  # type: ignore[no-untyped-def]
    """FR-5.12: Try again replays the puzzle from its start; the first result and the session stay."""
    start(page)
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    assert page.get_by_test_id("try-again").count() == 0  # lost but still playing: not over yet
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("engine-panel").wait_for()
    bar = counts(page)
    page.get_by_test_id("try-again").click()
    page.get_by_test_id("practice-badge").wait_for()
    your_turn(page)
    for testid in ("engine-panel", "engine-line", "answer-player", "analysis-controls", "try-again"):
        assert page.get_by_test_id(testid).count() == 0, testid
    play(page, WRONG, "black")
    page.get_by_test_id("trainer-message").filter(has_text="practice, not scored").wait_for()
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("trainer-message").filter(has_text="full line (practice").wait_for()
    page.get_by_test_id("engine-panel").wait_for()  # over again: the engine is back
    assert "Failed" in page.get_by_test_id("outcome").inner_text()  # the first result stays
    assert counts(page) == bar  # nothing recorded
    page.get_by_test_id("try-again").click()  # again, and this time clean
    your_turn(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Solved! (practice, not scored)").wait_for()
    assert counts(page) == bar
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 2").wait_for()
    assert page.get_by_test_id("practice-badge").count() == 0
    page.wait_for_timeout(500)
    assert "Failed 1" in page.get_by_test_id("session-bar").inner_text()  # the practice run added nothing
