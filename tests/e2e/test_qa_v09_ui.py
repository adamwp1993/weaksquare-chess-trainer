"""QA v0.9 (independent), against the mock: the User Guide's new Game Review AI steps followed in order,
screenshots of each new screen (tests/e2e/artifacts/, gitignored), and edge cases (N, a saved narrative from
the library, Train these and the other Mixer filters). xfail(strict=True) marks an open bug by its ID
(qa/QA-v0.9.md).

Mock game 1 is analyzed; you are White with key moments at plies 6 and 8. Mock game 2 isn't analyzed."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ART = Path(__file__).resolve().parent / "artifacts"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v09-{name}.png"), full_page=True)


def review(page, query: str = "?ai=on", game: int = 1) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-table").wait_for()
    page.get_by_test_id(f"review-{game}").click()
    page.get_by_test_id("review-view").wait_for()


def explain_game(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative").wait_for()


def test_qa_user_guide_explain_my_game_steps_and_screens(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=on&showbest=1")  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    shot(page, "review-ai-before")
    # Step 1: key moments 1–10, default from the setting.
    n = page.get_by_test_id("narrative-n")
    assert n.get_attribute("placeholder") == "Moments: default"
    n.click()
    options = page.get_by_role("option")
    assert options.count() == 10
    assert options.first.inner_text() == "1 key moment" and options.last.inner_text() == "10 key moments"
    page.keyboard.press("Escape")
    # Step 2: the model is the Game Review setting, "Same as Explain" by default.
    model = page.get_by_test_id("narrative-panel").get_by_test_id("ai-feature-model-game_review")
    assert model.input_value().startswith("Same as Explain")
    # Step 3: the Confirm dialog shows tokens, cost, the most, the share of the budget left and the cap.
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    est = page.get_by_test_id("narrative-estimate").inner_text()
    for words in ("input tokens", "output", "About $", "at most $", "left in this month's budget", "per-run cap",
                  "no names, ratings, dates, links or clocks"):  # fmt: skip
        assert words in est, words
    shot(page, "narrative-confirm")
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative").wait_for()
    # v0.15: the narrative fills the review's three parts
    for tid in ("review-ai-summary", "narrative-turning-point", "review-improve-summary", "narrative-train",
                "moment-note-6", "moment-note-8"):  # fmt: skip
        page.get_by_test_id(tid).wait_for()
    assert "Suggested training" in page.get_by_test_id("suggested-training").inner_text()
    shot(page, "narrative")
    page.get_by_test_id("moment-show-8").click()
    page.get_by_test_id("review-show-note").wait_for()
    page.wait_for_timeout(600)  # let chessground finish its animation
    ART.mkdir(exist_ok=True)
    page.get_by_test_id("review-view").get_by_test_id("board").screenshot(path=str(ART / "qa-v09-moment-on-board.png"))
    # The position before 5.Nxf7 (your knight on e5), with the AI's arrows, not the game's start.
    assert (
        page.get_by_test_id("review-view").locator(".cg-wrap piece:not(.ghost):not(.fading)").count() == 31
    )  # 4.Nxe5 took a pawn
    # Its arrows: red on the move played (Nxf7 from e5), green on the better move (Ng4 from e5).
    hashes = (
        page.get_by_test_id("review-view")
        .locator(".cg-wrap g[cgHash]")
        .evaluate_all("els => els.map(e => e.getAttribute('cgHash'))")
    )
    assert any(",e5,f7,red" in h for h in hashes), hashes
    assert any(",e5,g4,green" in h for h in hashes), hashes


def test_qa_fewer_key_moments_cover_only_the_largest(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    page.get_by_test_id("narrative-n").click()
    page.get_by_role("option", name="1 key moment", exact=True).click()
    explain_game(page)
    assert page.locator("[data-testid^=moment-note-]").count() == 1
    # Another N is another request: the default (2 moments here) isn't saved yet.
    page.get_by_test_id("narrative-n").locator("..").locator("button").first.click(force=True)  # clear
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").wait_for()


def test_qa_review_and_explain_on_a_saved_game_opens_no_confirm(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    explain_game(page)
    page.get_by_test_id("review-back").click()
    page.get_by_test_id("status-1").filter(has_text="AI-reviewed").wait_for()
    shot(page, "library-ai-reviewed")
    page.get_by_test_id("review-explain-1").click()
    page.get_by_test_id("narrative").wait_for()
    page.get_by_test_id("narrative-button").filter(has_text="(saved)").wait_for()
    assert page.get_by_test_id("narrative-confirm-button").count() == 0
    # In the same run the panel still shows what the fresh answer cost (like puzzle Explain); the button is free.


def test_qa_settings_ai_and_startup_screens(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=split")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("settings-ai")
    panel.scroll_into_view_if_needed()
    text = panel.inner_text()
    for label in ("Puzzle Explain", "Game Review", "Puzzle Explain reasoning", "Game Review reasoning"):
        assert label in text, label
    assert panel.get_by_test_id("ai-feature-model-game_review").input_value().startswith("claude-sonnet-5-5")
    assert "Puzzle Explain $" in panel.get_by_test_id("ai-spend-by-feature").inner_text()
    shot(page, "settings-ai")
    page.goto(page.base_url + "/?startup=show&ai=on")
    page.get_by_test_id("startup-more").click()
    page.get_by_test_id("ai-feature-model-game_review").wait_for()
    shot(page, "startup-both-pickers")


def test_qa_over_budget_review_screen(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?ai=over")
    page.get_by_test_id("narrative-why").wait_for()
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("move-explain-why").wait_for()
    shot(page, "over-budget")


def test_qa_dark_mode_narrative(page) -> None:  # type: ignore[no-untyped-def]
    review(
        page, "?ai=on&scheme=dark&showbest=1"
    )  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    explain_game(page)
    page.get_by_test_id("move-6").click()
    page.get_by_test_id("move-explain-button").click()
    page.get_by_test_id("explanation").wait_for()
    page.wait_for_timeout(600)
    ART.mkdir(exist_ok=True)
    page.get_by_test_id("review-view").get_by_test_id("board").screenshot(
        path=str(ART / "qa-v09-dark-show-me-board.png")
    )
    hashes = (
        page.get_by_test_id("review-view")
        .locator(".cg-wrap g[cgHash]")
        .evaluate_all("els => els.map(e => e.getAttribute('cgHash'))")
    )
    assert any(",f3,d4,green" in h for h in hashes), hashes  # Explain this move's Show me: Nxd4
    shot(page, "dark-narrative")


# v0.9-B3 regression test (fixed: Match stays as you set it).
def test_qa_train_these_changes_only_themes_and_rating(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_label("Theme match mode").get_by_text("ALL").click()
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-view").wait_for()
    explain_game(page)
    page.get_by_test_id("narrative-train").click()
    page.get_by_test_id("train-apply").click()
    page.get_by_test_id("trainer-page").wait_for()
    page.get_by_test_id("themes-picker").filter(has_text="2 selected").wait_for()
    shot(page, "after-train-these")
    assert page.get_by_label("Theme match mode").locator("input:checked").get_attribute("value") == "all"


# v0.9-B4 regression test (fixed: the picker is searchable and takes a typed ID).
def test_qa_game_review_picker_takes_a_typed_model_id(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("gear").click()
    model = page.get_by_test_id("settings-ai").get_by_test_id("ai-feature-model-game_review")
    model.scroll_into_view_if_needed()
    assert model.get_attribute("readonly") is None


# v0.9-B5 regression test (fixed: the Game Review block is always shown).
def test_qa_game_review_can_be_set_up_without_puzzle_explain(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("settings-ai")
    panel.scroll_into_view_if_needed()
    assert panel.get_by_test_id("ai-feature-model-game_review").count() == 1


# ---- QA round 2 (fixes for B1–B6): regressions around the changed picker, Train these and Settings ----------


def _type(page, model, text: str) -> None:  # type: ignore[no-untyped-def]
    model.click()
    model.fill(text)


def test_qa_r2_typing_filters_the_list_and_picking_a_listed_model_still_works(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("gear").click()
    model = page.get_by_test_id("settings-ai").get_by_test_id("ai-feature-model-game_review")
    model.scroll_into_view_if_needed()
    _type(page, model, "sonnet")
    page.get_by_role("option", name="claude-sonnet-5-5  ·  about").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=ai-feature-model-game_review]').value.startsWith('claude-sonnet')"
    )
    # A listed ID typed in full isn't offered twice as "Use …".
    _type(page, model, "claude-opus-5-5")
    assert page.get_by_role("option", name="Use “claude-opus-5-5” with Anthropic").count() == 0
    page.keyboard.press("Escape")
    # Back to Same as Explain.
    _type(page, model, "Same")
    page.get_by_role("option", name="Same as Explain (claude-haiku-5-5)").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=ai-feature-model-game_review]').value.startsWith('Same as Explain')"
    )


def test_qa_r2_a_typed_unpriced_model_is_saved_but_blocked_with_a_reason(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("gear").click()
    model = page.get_by_test_id("settings-ai").get_by_test_id("ai-feature-model-game_review")
    model.scroll_into_view_if_needed()
    _type(page, model, "!! not a model")
    page.get_by_text("Not a model ID").wait_for()
    _type(page, model, "claude-qa-custom-9")
    page.get_by_role("option", name="Use “claude-qa-custom-9” with Anthropic").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=ai-feature-model-game_review]').value.includes('claude-qa-custom-9')"
    )
    shot(page, "r2-typed-model")
    page.keyboard.press("Escape")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    why = page.get_by_test_id("narrative-why")
    why.filter(has_text="price table").wait_for()
    assert page.get_by_test_id("narrative-button").is_disabled()
    compact = page.get_by_test_id("narrative-panel").get_by_test_id("ai-feature-model-game_review")
    assert "claude-qa-custom-9" in compact.input_value()
    shot(page, "r2-review-typed-model")


def test_qa_r2_the_compact_review_picker_takes_a_typed_id_and_a_listed_model(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    compact = page.get_by_test_id("narrative-panel").get_by_test_id("ai-feature-model-game_review")
    _type(page, compact, "gpt-qa-typed-1")
    page.get_by_role("option", name="Use “gpt-qa-typed-1” with OpenAI").click()
    page.get_by_test_id("narrative-why").wait_for()  # no OpenAI key and no price row: blocked with a reason
    assert page.get_by_test_id("ai-feature-key-game_review").count() == 1  # the key field appears in place
    shot(page, "r2-compact-typed")
    _type(page, compact, "opus")
    page.get_by_role("option", name="claude-opus-5-5  ·  about").click()
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").wait_for()
    page.get_by_test_id("narrative-button").click()
    assert "claude-opus-5-5" in page.get_by_test_id("narrative-estimate").inner_text()


def test_qa_r2_the_startup_short_form_with_no_ai_set_up(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?startup=show")
    more = page.get_by_test_id("startup-more")
    if more.count():
        more.click()
    page.get_by_test_id("ai-feature-model-game_review").wait_for()
    shot(page, "r2-startup-no-ai")
    assert page.get_by_test_id("ai-feature-model-game_review").input_value() == "Same as Explain"
    # Nothing is set up behind your back: the top bar shows no AI spend.
    assert page.get_by_text("AI $").count() == 0


def test_qa_r2_game_review_alone_on_openai_with_explain_off(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("settings-ai")
    model = panel.get_by_test_id("ai-feature-model-game_review")
    model.scroll_into_view_if_needed()
    model.click()
    page.get_by_role("option", name="gpt-5.4-mini  ·  about").click()
    panel.get_by_test_id("ai-feature-key-game_review").wait_for()
    assert panel.get_by_test_id("ai-provider").input_value() == "None"
    shot(page, "r2-game-review-alone")


@pytest.mark.parametrize(("source", "expected"), [("My puzzles", "my→lichess"), ("Both", "both")])
def test_qa_r2_train_these_switches_the_source_only_from_my_puzzles(page, source: str, expected: str) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("source-select").get_by_text(source).click()
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-view").wait_for()
    explain_game(page)
    page.get_by_test_id("narrative-train").click()
    page.get_by_test_id("train-apply").click()
    page.get_by_test_id("trainer-page").wait_for()
    want = "lichess" if expected == "my→lichess" else "both"
    assert page.get_by_test_id("source-select").locator("input:checked").get_attribute("value") == want
    page.get_by_test_id("themes-picker").filter(has_text="2 selected").wait_for()
