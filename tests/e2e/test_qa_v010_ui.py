"""QA v0.10 against the mock (qa/QA-v0.10.md): Show best moves with the AI panels, the Suggested mix when you
leave the Coach page during a run, the User Guide's Coach steps, and screenshots of every v0.10 screen into
tests/e2e/artifacts/ (gitignored)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ART = Path(__file__).parent / "artifacts"


def shot(page, name: str, full: bool = False) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v010-{name}.png"), full_page=full)


def review(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-view").wait_for()


def coach(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-page").wait_for()


# ---- Show best moves (FR-11.35) -------------------------------------------------------------------------


def test_qa_show_best_off_explain_this_move_hides_the_board_arrows(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=on")
    page.get_by_test_id("move-6").click()  # 4.Nxe5??
    page.get_by_test_id("move-explain-button").filter(has_text="≈ $").click()
    page.get_by_test_id("explanation").wait_for()
    assert page.get_by_test_id("explain-show-me").count() == 0  # no Show me (its arrows give the move away)
    assert page.get_by_test_id("answer-player").count() == 0
    assert page.get_by_test_id("review-better").count() == 0
    shot(page, "review-explain-best-off", full=True)


def test_qa_show_best_off_hides_the_better_move_in_the_explanation_steps(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=on")
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("move-explain-button").filter(has_text="≈ $").click()
    page.get_by_test_id("explanation").wait_for()
    steps = page.get_by_test_id("explanation-steps").inner_text()
    assert "Nxd4" not in steps, steps  # the better move (Better was Nxd4) is hidden everywhere else


def test_qa_show_best_off_explain_my_game_hides_better_lines(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=on")
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative").wait_for(timeout=5000)
    assert page.locator("[data-testid^=moment-show-]").count() == 0  # no better line or arrows
    assert page.locator("[data-testid^=moment-note-]").count() > 0  # the AI's text stays
    assert "better was" not in page.get_by_test_id("key-moments").inner_text()
    shot(page, "review-narrative-best-off", full=True)
    page.get_by_test_id("review-show-best").click()
    page.locator("[data-testid^=moment-show-]").first.wait_for()


def test_qa_analyze_from_here_screens(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("review-analyze-here").click()
    page.get_by_test_id("review-free-hidden").wait_for()
    shot(page, "analyze-here-best-off")
    page.get_by_test_id("review-show-best").click()
    page.get_by_test_id("engine-lines").wait_for()
    assert "Game position:" in page.get_by_test_id("engine-start-eval").inner_text()
    shot(page, "analyze-here-best-on")
    page.get_by_test_id("analysis-close").click()
    assert page.get_by_test_id("review-move").inner_text().startswith("4.")  # back where you were


# ---- the Suggested mix --------------------------------------------------------------------------------


def test_qa_leaving_the_coach_page_during_a_run_still_applies_the_mix_on_screen(page) -> None:  # type: ignore[no-untyped-def]
    coach(page)
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("nav-puzzles").click()  # you go and train while it runs
    page.wait_for_timeout(2500)  # the mock's run is done after about a second
    page.get_by_test_id("suggestion-label").wait_for(timeout=3000)


def test_qa_staying_on_the_coach_page_applies_the_mix_on_screen(page) -> None:  # type: ignore[no-untyped-def]
    coach(page)
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-report").wait_for(timeout=5000)
    page.get_by_test_id("nav-puzzles").click()
    page.get_by_test_id("suggestion-label").wait_for(timeout=3000)
    shot(page, "mixer-suggested")
    page.get_by_test_id("suggestion-why-toggle").click()
    shot(page, "mixer-suggested-why")


# ---- screens -----------------------------------------------------------------------------------------


def test_qa_coach_screens(page) -> None:  # type: ignore[no-untyped-def]
    coach(page)
    shot(page, "coach-empty", full=True)
    page.get_by_test_id("coach-whose").get_by_text("Another player").click()
    page.get_by_test_id("coach-player").wait_for()
    shot(page, "coach-another-player", full=True)
    coach(page, "?coach=report&ai=on")
    page.get_by_test_id("coach-report").wait_for()
    shot(page, "coach-report", full=True)
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("narrative-estimate").wait_for()
    shot(page, "coach-ai-confirm")
    page.get_by_test_id("coach-ai-confirm-button").click()
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    shot(page, "coach-ai-result", full=True)


def test_qa_banner_and_compare_screens(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?coach=banner")
    page.get_by_test_id("suggestion-banner").wait_for()
    shot(page, "banner")
    page.get_by_test_id("suggestion-compare").click()
    page.get_by_test_id("compare-suggested").wait_for()
    shot(page, "compare")


def test_qa_settings_and_my_puzzles_screens(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1&ai=on")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("my-severities").wait_for()
    shot(page, "my-puzzles-filters", full=True)
    page.get_by_test_id("gear").click()
    page.wait_for_timeout(500)
    shot(page, "settings", full=True)
