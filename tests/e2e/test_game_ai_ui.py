"""v0.9 UI against the mock: a model per AI feature (FR-1.15) in Settings → AI, on the startup page and on
the Review page; Explain this move (FR-11.17); Explain my game with its Confirm dialog, the moments' notes
and Train these (FR-11.18); the AI-reviewed status and Review + Explain my game (FR-11.25, 11.29); the
budget blocking a new request while a saved one stays free (§9.3).

Mock game 1 is the Blackburne Shilling trap, analyzed: you are White and blunder with 4.Nxe5 (ply 6) and
5.Nxf7 (ply 8). Mock game 2 isn't analyzed yet.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def review(page, query: str = "?ai=on", game: int = 1) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-table").wait_for()
    page.get_by_test_id(f"review-{game}").click()
    page.get_by_test_id("review-view").wait_for()


def pick(page, testid: str, option: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id(testid).first.click()
    page.get_by_role("option", name=option).click()


def test_no_ai_means_no_game_review_ai(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "")
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("review-current").wait_for()
    assert page.get_by_test_id("move-explain").count() == 0
    assert page.get_by_test_id("narrative-panel").count() == 0


def test_settings_have_a_game_review_model_that_follows_explain(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("settings-ai")
    model = panel.get_by_test_id("ai-feature-model-game_review")
    model.scroll_into_view_if_needed()
    assert model.input_value() == "Same as Explain (claude-haiku-5-5)"
    model.click()
    page.get_by_role("option", name="claude-sonnet-5-5  ·  about").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=ai-feature-model-game_review]').value.startsWith('claude-sonnet-5-5')"
    )
    panel.get_by_test_id("ai-feature-reasoning-game_review").get_by_text("Medium").click()
    panel.get_by_test_id("ai-spend-by-feature").filter(has_text="Game Review $0.00").wait_for()
    assert panel.get_by_test_id("ai-model").input_value() == "claude-haiku-5-5"  # Explain's own model is untouched
    # An OpenAI model needs an OpenAI key: the field appears right there (keys are per provider).
    model.click()
    page.get_by_role("option", name="gpt-5.4-mini  ·  about").click()
    panel.get_by_test_id("ai-feature-key-game_review").wait_for()


def test_the_startup_page_shows_both_pickers(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?startup=show&ai=on")
    page.get_by_test_id("startup-more").click()
    page.get_by_test_id("ai-model").wait_for()
    page.get_by_test_id("ai-feature-model-game_review").wait_for()


def test_explain_this_move_on_your_mistake(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=on&showbest=1")  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    page.get_by_test_id("move-5").click()  # Black's move: not yours, no button
    page.get_by_test_id("review-current").wait_for()
    assert page.get_by_test_id("move-explain-button").count() == 0
    page.get_by_test_id("move-6").click()
    button = page.get_by_test_id("move-explain-button")
    button.filter(has_text="≈ $").wait_for()
    button.click()
    page.get_by_test_id("explanation").wait_for()
    assert "Nxd4" in page.get_by_test_id("explanation-summary").inner_text()
    page.get_by_test_id("answer-player").wait_for()  # Show me starts on its own
    assert page.locator(".cg-wrap svg.cg-shapes path, .cg-wrap svg g").count() > 0
    page.get_by_test_id("review-back").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("explanation").wait_for()  # it comes back with no new request (the button's gone)
    assert page.get_by_test_id("move-explain-button").count() == 0


def test_explain_my_game_confirm_cancel_then_run(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=on&showbest=1")  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    button = page.get_by_test_id("narrative-button")
    button.filter(has_text="≈ $").wait_for()
    button.click()
    estimate = page.get_by_test_id("narrative-estimate").inner_text()
    assert (
        "10,000 input tokens" in estimate and "4,000 output" in estimate and "left in this month's budget" in estimate
    )
    page.get_by_test_id("narrative-cancel").click()
    page.get_by_test_id("narrative-cancel").wait_for(state="detached")
    assert page.get_by_test_id("narrative").count() == 0
    button.click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative").wait_for()
    assert "Opening." in page.get_by_test_id("narrative-opening").inner_text()
    assert page.get_by_test_id("narrative-takeaways").locator("li").count() == 2
    page.get_by_test_id("narrative-discarded").wait_for()
    # The key moments carry the AI's notes, and Show on the board draws them.
    page.get_by_test_id("moment-note-6").wait_for()
    page.get_by_test_id("moment-show-6").click()
    page.get_by_test_id("review-show-note").wait_for()
    page.get_by_test_id("narrative-turning-point").click()
    assert "Nxf7" in page.get_by_test_id("review-move").inner_text()
    # Saved: the button is free now, and the library shows the game as AI-reviewed.
    button.filter(has_text="(saved)").wait_for()
    page.get_by_test_id("review-back").click()
    assert "ai-reviewed" in page.get_by_test_id("status-1").inner_text().lower()


def test_train_these_applies_the_preset_only_after_the_confirm(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative-train").click()
    page.get_by_test_id("train-confirm").get_by_text("Your saved presets don't change").wait_for()
    page.get_by_test_id("train-apply").click()
    page.get_by_test_id("trainer-page").wait_for()
    page.get_by_test_id("themes-picker").filter(has_text="2 selected").wait_for()


def test_the_review_page_model_dropdown_changes_game_reviews_model(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    panel = page.get_by_test_id("narrative-panel")
    panel.get_by_test_id("ai-feature-model-game_review").click()
    page.get_by_role("option", name="claude-opus-5-5  ·  about").click()
    panel.get_by_test_id("narrative-button").filter(has_text="≈ $").wait_for()
    page.get_by_test_id("narrative-button").click()
    assert "claude-opus-5-5" in page.get_by_test_id("narrative-estimate").inner_text()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative-cost").filter(has_text="claude-opus-5-5").wait_for()


def test_over_budget_blocks_a_new_explanation(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=over")
    page.get_by_test_id("narrative-why").filter(has_text="this month's AI budget").wait_for()
    assert page.get_by_test_id("narrative-button").is_disabled()
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("move-explain-why").filter(has_text="budget").wait_for()


def test_review_and_explain_my_game_from_the_library(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-explain-2").click()  # game 2 isn't analyzed yet: it's analyzed first
    page.get_by_test_id("narrative-confirm-button").click(timeout=15000)
    page.get_by_test_id("narrative").wait_for()


def test_the_library_filters_by_ai_reviewed(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative").wait_for()
    page.get_by_test_id("review-back").click()
    page.get_by_test_id("filter-status").click(force=True)
    page.get_by_role("option", name="AI-reviewed").click()
    page.get_by_test_id("games-count").filter(has_text="1 game").wait_for()
