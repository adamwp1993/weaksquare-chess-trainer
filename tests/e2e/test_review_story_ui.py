"""v0.14 UI against the mock: Game Review in three parts (FR-11.36): Summary, What to improve, What you did well.
No AI key needed: the sections come with the review."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.e2e


def review(page: Any, query: str = "") -> None:
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-table").wait_for()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-view").wait_for()


def test_the_review_has_a_summary_what_to_improve_and_what_you_did_well(page: Any) -> None:
    review(page)
    summary = page.get_by_test_id("review-story-summary")
    summary.wait_for()
    text = summary.inner_text()
    assert "Summary" in text and "Stockfish found" in text and "turning point" in text
    assert "What to improve: key moments" in page.get_by_test_id("key-moments").inner_text()
    strengths = page.get_by_test_id("review-strengths")
    assert "What you did well" in strengths.inner_text()
    # The parts come in this order on the page.
    tops = [
        page.get_by_test_id(t).bounding_box()["y"] for t in ("review-story-summary", "key-moments", "review-strengths")
    ]
    assert tops == sorted(tops)


def test_a_lost_game_with_blunders_gets_no_invented_praise(page: Any) -> None:
    """Mock game 1 is a loss with two blunders and nothing the engine counts as a strength."""
    review(page)
    strengths = page.get_by_test_id("review-strengths")
    strengths.wait_for()
    assert strengths.get_by_test_id("review-strength").count() == 0
    assert "Nothing stood out" in strengths.get_by_test_id("review-strengths-none").inner_text()
    assert "You lost" in page.get_by_test_id("review-story-summary").inner_text()


def test_the_ai_narrative_adds_no_strengths_of_its_own(page: Any) -> None:
    """FR-11.36: with nothing computed, Explain my game shows no What you did well at all."""
    review(page, "?ai=on")
    page.get_by_test_id("narrative-button").filter(has_text="≈ $").click()
    page.get_by_test_id("narrative-confirm-button").click()
    page.get_by_test_id("narrative-takeaways").wait_for()
    assert page.get_by_test_id("narrative-did-well").count() == 0
