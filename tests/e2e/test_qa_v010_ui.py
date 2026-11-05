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


# ---- round 2 ----------------------------------------------------------------------------------------


def test_qa_r2_the_mix_reloads_on_the_puzzles_page_with_its_mode(page) -> None:  # type: ignore[no-untyped-def]
    """B3 fix: after a run that ended elsewhere, the Mixer shows the suggestion's filters and mode."""
    coach(page)
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("nav-puzzles").click()
    page.get_by_test_id("suggestion-label").wait_for(timeout=5000)
    mode = page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value")
    assert mode == "danger_spotting", mode  # the mock report's mix
    shot(page, "r2-mix-after-leaving")


def test_qa_r2_a_run_ending_mid_session_keeps_the_mode_shown_and_the_session_in_step(page) -> None:  # type: ignore[no-untyped-def]
    """B3 fix side effect: a run that ends while a Standard session is running."""
    coach(page)
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("nav-puzzles").click()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("board").wait_for()
    page.get_by_test_id("suggestion-label").wait_for(timeout=5000)
    shown = page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value")
    running = page.get_by_test_id("session-mode").inner_text()
    shot(page, "r2-mid-session", full=True)
    # The Mixer and the running session must agree on the mode (§6: a mode change starts a new session).
    labels = {"standard": "Standard", "danger_spotting": "Danger spotting", "commit_line": "Commit the line"}
    assert labels.get(str(shown)) == running, (shown, running)


# ---- round 3 (B9 fix) -----------------------------------------------------------------------------------


def _run_then_session(page) -> None:  # type: ignore[no-untyped-def]
    coach(page)
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("nav-puzzles").click()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("board").wait_for()
    page.get_by_test_id("suggestion-label").wait_for(timeout=5000)
    assert page.get_by_test_id("session-mode").inner_text() == "Standard"


def _shown(page) -> str | None:  # type: ignore[no-untyped-def]
    return page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value")  # type: ignore[no-any-return]


def test_qa_r3_starting_again_after_the_run_uses_the_suggested_mode(page) -> None:  # type: ignore[no-untyped-def]
    """The guide: the new mix's mode waits until that session ends. Pressing Start ends it too."""
    _run_then_session(page)
    page.get_by_role("button", name="Start").click()  # a new session from the Mixer
    page.wait_for_timeout(500)
    running = page.get_by_test_id("session-mode").inner_text()
    stored = page.evaluate("window.__mockApi.settings.mode") if page.evaluate("!!window.__mockApi.settings") else None
    assert running == "Danger spotting", (running, _shown(page), stored)


def test_qa_r3_a_mode_you_pick_mid_session_is_not_replaced_later(page) -> None:  # type: ignore[no-untyped-def]
    _run_then_session(page)
    page.get_by_test_id("mode-control").get_by_text("Commit the line", exact=True).click()  # your own choice
    page.get_by_test_id("session-mode").filter(has_text="Commit the line").wait_for()
    for _ in range(25):  # finish the session
        if page.get_by_role("button", name="New session").count():
            break
        page.get_by_test_id("next-button").click()
        page.wait_for_timeout(100)
    page.get_by_role("button", name="New session").click()
    page.wait_for_timeout(300)
    assert _shown(page) == "commit_line", _shown(page)


def test_qa_r3_the_ai_coaching_box_with_its_model_picker(page) -> None:  # type: ignore[no-untyped-def]
    """M1: the picker sits in the box, its options are priced per report, and the same setting as Settings → AI."""
    coach(page, "?ai=on&coach=report")
    box = page.get_by_test_id("coach-ai")
    box.get_by_test_id("ai-feature-model-coach").click()
    page.get_by_role("option", name="claude-sonnet-5-5  ·  about").filter(has_text="per report").wait_for()
    page.get_by_role("option", name="claude-sonnet-5-5  ·  about").click()
    box.get_by_test_id("coach-ai-start").wait_for()
    box.scroll_into_view_if_needed()
    shot(page, "r3-ai-coaching-box")
    page.get_by_test_id("gear").click()
    picker = page.get_by_test_id("settings-ai").get_by_test_id("ai-feature-model-coach")
    picker.scroll_into_view_if_needed()
    assert picker.input_value().startswith("claude-sonnet-5-5"), picker.input_value()
