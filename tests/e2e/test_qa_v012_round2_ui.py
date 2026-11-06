"""QA v0.12 round 2 in the UI on the mock client: the composer's new tags, the Game filter, the tooltip walk over the new
controls, and long words everywhere a note is shown. A test exposing an open bug is marked xfail with its ID."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_v012_tooltips import _assert_all_have_tips, _tips
from tests.e2e.test_v012_ui import _coach, _expand_all, _in_plan, _task_of_type

pytestmark = pytest.mark.e2e
ART = Path("tests/e2e/artifacts")


def _open(page: Page, query: str) -> None:
    page.goto(f"{page.base_url}/?{query}")  # type: ignore[attr-defined]


def _journal(page: Page, query: str = "coach=report&plan=current&journal=some") -> None:
    _open(page, query)
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-journal").click()
    page.get_by_test_id("journal-tab").wait_for()


def _pick(page: Page, testid: str, index: int = 0) -> str:
    page.get_by_test_id(testid).click()
    option = page.get_by_role("option").locator("visible=true").nth(index)
    text = option.inner_text()
    option.click()
    return text


def _shot(page: Page, name: str, full: bool = True) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v012-r2-{name}.png"), full_page=full)


def _no_sideways_scroll(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def test_qa2_the_composer_tags_a_game_and_a_day_and_they_clear_after_saving(page: Page) -> None:
    _journal(page)
    game = _pick(page, "journal-tag-game")
    assert "–" in game
    day = _pick(page, "journal-tag-day")
    assert "Week" in day
    page.get_by_test_id("journal-text").fill("Tagged by hand.")
    _shot(page, "composer-tags")
    page.get_by_test_id("journal-save").click()
    entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="Tagged by hand.")
    expect(entry).to_contain_text("Game reflection")
    expect(entry.locator('[data-testid^="journal-open-"]')).to_be_visible()
    expect(page.get_by_test_id("journal-tag-game")).to_have_value("")
    expect(page.get_by_test_id("journal-tag-day")).to_have_value("")
    expect(page.get_by_test_id("journal-text")).to_have_value("")


def test_qa2_the_game_tag_search_finds_a_game_and_clears(page: Page) -> None:
    _journal(page)
    box = page.get_by_test_id("journal-tag-game")
    box.click()
    box.fill("zzz-nothing")
    expect(page.get_by_role("option").locator("visible=true")).to_have_count(0)
    box.fill("")
    box.press("Escape")


@pytest.mark.xfail(strict=True, reason="v0.12-B24: a plan-day tag is saved but shown nowhere")
def test_qa2_a_plan_day_tag_can_be_seen_on_the_entry(page: Page) -> None:
    _journal(page)
    day = _pick(page, "journal-tag-day", 1)  # not today, so the entry's own date can't stand in for it
    page.get_by_test_id("journal-text").fill("On a day.")
    page.get_by_test_id("journal-save").click()
    entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="On a day.")
    expect(entry).to_be_visible()
    expect(entry).to_contain_text(day.split("·")[-1].strip(), timeout=1500)


def test_qa2_the_game_filter_really_filters_and_hides_the_log(page: Page) -> None:
    _journal(page)
    timeline = page.get_by_test_id("journal-timeline")
    expect(page.get_by_test_id("journal-log").first).to_be_visible()
    before = page.locator('[data-testid^="journal-entry-"]').count()
    assert before >= 2
    _pick(page, "journal-filter-game")
    expect(page.get_by_test_id("journal-log")).to_have_count(0)
    expect(timeline.locator('[data-testid^="journal-entry-"]').first).to_contain_text("Game reflection")
    assert page.locator('[data-testid^="journal-entry-"]').count() < before
    expect(page.get_by_test_id("journal-older")).to_have_count(0)
    # Clear it: all back.
    page.get_by_test_id("journal-filter-game").locator(
        "xpath=ancestor::*[contains(@class,'InputWrapper-root')]"
    ).locator("button").last.click()
    expect(page.get_by_test_id("journal-log").first).to_be_visible()
    assert page.locator('[data-testid^="journal-entry-"]').count() == before


def test_qa2_the_game_filter_can_be_cleared_after_its_last_entry_is_deleted(page: Page) -> None:
    _journal(page)
    _pick(page, "journal-filter-game")
    rows = page.locator('[data-testid^="journal-delete-"]')
    expect(rows.first).to_be_visible()
    for _ in range(rows.count()):
        rows.first.click()
        page.wait_for_timeout(100)
    expect(page.get_by_test_id("journal-empty")).to_be_visible()
    _shot(page, "filter-after-delete")
    clear = (
        page.get_by_test_id("journal-filter-game")
        .locator("xpath=ancestor::*[contains(@class,'InputWrapper-root')]")
        .locator("button")
    )
    assert clear.count() >= 1
    # With the filter's choice gone the box must not leave you with an empty list you can't explain or clear.
    clear.last.click()
    expect(page.get_by_test_id("journal-log").first).to_be_visible()


def test_qa2_a_reflection_task_fills_its_tag_and_saving_ticks_it_and_clears_the_tags(page: Page) -> None:
    _open(page, "coach=report&plan=current&journal=some")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Reflection:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("journal-prompt").wait_for()
    expect(page.get_by_test_id("journal-tag")).not_to_have_value("")
    page.get_by_test_id("journal-text").fill("My reflection.")
    _pick(page, "journal-tag-game")
    page.get_by_test_id("journal-save").click()
    expect(page.locator('[data-testid^="journal-entry-"]').filter(has_text="My reflection.")).to_be_visible()
    expect(page.get_by_test_id("journal-prompt")).to_have_count(0)
    expect(page.get_by_test_id("journal-tag-game")).to_have_value("")


@pytest.mark.xfail(strict=True, reason="v0.12-B27: closing a reflection's question throws away what you wrote")
def test_qa2_closing_a_reflections_question_keeps_what_you_wrote(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Reflection:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("journal-prompt").wait_for()
    page.get_by_test_id("journal-text").fill("Half a thought.")
    page.get_by_test_id("journal-prompt").get_by_role("button").click()
    expect(page.get_by_test_id("journal-prompt")).to_have_count(0)
    expect(page.get_by_test_id("journal-text")).to_have_value("Half a thought.")


def test_qa2_the_new_controls_have_tooltips_with_their_own_words(page: Page) -> None:
    _journal(page)
    _assert_all_have_tips(page, "Journal tab with the new tags")
    assert {"journal.tag", "journal.tagGame", "journal.tagDay", "journal.filterGame", "journal.filterWeakness"} <= set(
        _tips(page)
    )
    for key, word in (
        ("journal.tagGame", "latest games"),
        ("journal.tagDay", "day of your plan"),
        ("journal.filterGame", "only entries"),
    ):
        page.locator(f'[data-option-info="{key}"]').hover()
        expect(page.get_by_role("tooltip")).to_contain_text(word)
        page.mouse.move(0, 0)
        expect(page.get_by_role("tooltip")).to_have_count(0)


def test_qa2_the_counter_and_a_narrow_window(page: Page) -> None:
    page.set_viewport_size({"width": 900, "height": 800})
    _journal(page)
    page.get_by_test_id("journal-text").fill("y" * 1234)
    expect(page.get_by_test_id("journal-count")).to_have_text("1,234 / 5,000")
    _no_sideways_scroll(page)
    _shot(page, "journal-900")


def test_qa2_a_long_word_stays_inside_the_edit_box_and_the_game_notes(page: Page) -> None:
    _journal(page)
    page.get_by_test_id("journal-text").fill("z" * 5000)
    _pick(page, "journal-tag-game")
    page.get_by_test_id("journal-save").click()
    entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="zzzz")
    expect(entry).to_be_visible()
    _no_sideways_scroll(page)
    entry.locator('[data-testid^="journal-edit-"]').first.click()
    _no_sideways_scroll(page)
    page.get_by_role("button", name="Cancel").click()
    # The same note in Game Review's list.
    entry.locator('[data-testid^="journal-open-"]').click()
    page.get_by_test_id("review-back").wait_for()
    expect(page.locator('[data-testid^="game-note-"]').filter(has_text="zzzz").first).to_be_visible()
    _no_sideways_scroll(page)
    _shot(page, "review-long-note")


@pytest.mark.xfail(strict=True, reason="v0.12-B25: the Include my journal preview doesn't wrap one long word")
def test_qa2_a_long_word_stays_inside_the_journal_preview(page: Page) -> None:
    _open(page, "ai=on&coach=report&journal=some")
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-ai-journal").check()
    line = page.get_by_test_id("coach-journal-line").first
    expect(line).to_be_visible()
    # The mock's preview is fixed text, so put the backend's longest (1,000 characters, one word) into the real element.
    line.locator("p").last.evaluate("el => { el.textContent = 'q'.repeat(1000); }")
    _shot(page, "preview-long-word")
    assert not line.evaluate("el => el.scrollWidth > el.clientWidth + 1")
