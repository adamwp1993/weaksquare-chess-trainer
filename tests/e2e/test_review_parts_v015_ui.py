"""v0.15 UI against the mock: Explain my game fills the review's three parts (Adam's v0.15-rc1 feedback).

1. **Summary:** the AI's general summary of the game, in place of the computed sentences, with the turning point.
2. **What to improve:** the AI's own short summary, then the key moments with their notes, each tagged with the
   training ideas it points to, then the Suggested training box with Train these puzzles.
3. **What you did well:** the AI's own short summary, then each computed strength with the AI's words on it.

There is one What you did well section, not two, and the narrative panel holds only the controls and the cost."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.e2e


def review(page: Any, game: int, query: str = "?ai=on") -> None:
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-table").wait_for()
    page.get_by_test_id(f"review-{game}").click()
    page.get_by_test_id("review-view").wait_for()


def explain(page: Any) -> None:
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative").wait_for()


def _game_with_strengths(page: Any) -> int:
    """The first mock game whose review has a computed strength (only game 1 starts analyzed, and it has none)."""
    for game in (3, 2):
        review(page, game)
        page.get_by_test_id("review-analyze").click()
        page.get_by_test_id("review-strengths").wait_for()
        if page.get_by_test_id("review-strength").count() > 0:
            return game
    raise AssertionError("no mock game has a computed strength")


def test_summary_and_what_to_improve_open_with_their_own_summaries(page: Any) -> None:
    review(page, 1)
    explain(page)
    # 1. Summary: the AI's general summary replaces the computed sentences.
    summary = page.get_by_test_id("review-story-summary")
    ai = summary.get_by_test_id("review-ai-summary").inner_text()
    assert ai.startswith("You came out of the opening") and "Stockfish found" not in summary.inner_text()
    summary.get_by_test_id("narrative-turning-point").wait_for()
    # 2. What to improve: its summary comes before the first key moment, Suggested training after the last.
    improve = page.get_by_test_id("key-moments")
    assert improve.locator("h5").inner_text() == "What to improve"
    first = improve.get_by_test_id("moment-6")
    assert _y(improve.get_by_test_id("review-improve-summary")) < _y(first)
    assert _y(improve.get_by_test_id("suggested-training")) > _y(first)
    # The narrative panel keeps only its controls and the cost.
    panel = page.get_by_test_id("narrative-panel")
    assert panel.get_by_test_id("review-ai-summary").count() == 0
    assert panel.get_by_test_id("narrative-train").count() == 0


def test_what_you_did_well_opens_with_its_summary_and_notes_each_strength(page: Any) -> None:
    game = _game_with_strengths(page)
    explain(page)
    # 3. What you did well: its summary, then each strength with the AI's note on it.
    well = page.get_by_test_id("review-strengths")
    assert "noticed it straight away" in well.get_by_test_id("review-did-well-summary").inner_text()
    assert _y(well.get_by_test_id("review-did-well-summary")) < _y(well.get_by_test_id("review-strength").first)
    assert well.get_by_test_id("review-strength-note").count() >= 1
    # One What you did well on the page, not a second one from the AI.
    assert page.get_by_text("What you did well", exact=True).count() == 1
    # The parts come in order.
    tops = [_y(page.get_by_test_id(t)) for t in ("review-story-summary", "key-moments", "review-strengths")]
    assert tops == sorted(tops), game


def test_each_key_moment_is_tagged_with_its_training_ideas(page: Any) -> None:
    review(page, 1, "?ai=on&showbest=1")
    explain(page)
    ideas = page.get_by_test_id("moment-ideas-6")
    ideas.wait_for()
    assert "Train:" in ideas.inner_text()
    assert [b.inner_text() for b in ideas.get_by_test_id("moment-idea").all()] == ["Hanging piece", "Defensive move"]
    # Inside that moment's card, under its note.
    assert page.get_by_test_id("moment-6").get_by_test_id("moment-ideas-6").count() == 1


def test_without_the_ai_the_computed_parts_stay(page: Any) -> None:
    review(page, 1, "")
    summary = page.get_by_test_id("review-story-summary")
    assert "Stockfish found" in summary.inner_text()
    assert page.get_by_test_id("review-improve-summary").count() == 0
    assert page.get_by_test_id("review-did-well-summary").count() == 0


def _y(locator: Any) -> float:
    box = locator.bounding_box()
    assert box is not None
    return float(box["y"])


def test_suggested_training_is_its_own_box_and_takes_you_to_those_puzzles(page: Any) -> None:
    """v0.15 manual test M3 (Adam): the recommended puzzle set was a small "Practise:" line, easy to miss. It's now a
    Suggested training box at the end of What to improve, spelled "practice", with Train these puzzles."""
    review(page, 1)
    explain(page)
    box = page.get_by_test_id("key-moments").get_by_test_id("suggested-training")
    text = box.inner_text()
    assert "Suggested training" in text and "Practise" not in text and "practice" in text
    assert [b.inner_text() for b in box.get_by_test_id("suggested-theme").all()] == ["Hanging piece", "Fork"]
    assert box.get_by_test_id("suggested-range").inner_text() == "rated 1200–1700"
    box.get_by_test_id("narrative-train").click()
    page.get_by_test_id("train-apply").click()
    page.get_by_test_id("trainer-page").wait_for()
    page.get_by_test_id("themes-picker").filter(has_text="2 selected").wait_for()
