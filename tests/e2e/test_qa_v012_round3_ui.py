"""QA v0.12 round 3 in the UI on the mock client: a reflection's question closed with its tags, what Send to Coach shows
from another Coach tab, and the checkbox on a row that says it moved. A test exposing an open bug is marked xfail with
its ID."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_qa_v012_round2_ui import _journal, _open, _pick
from tests.e2e.test_v012_ui import _coach, _expand_all, _in_plan, _task_of_type

pytestmark = pytest.mark.e2e


def test_qa3_closing_a_question_keeps_the_tags_and_a_new_start_brings_its_own(page: Page) -> None:
    _open(page, "coach=report&plan=current&journal=some")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Reflection:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("journal-prompt").wait_for()
    tag = page.get_by_test_id("journal-tag").input_value()
    assert tag
    page.get_by_test_id("journal-text").fill("Half a thought.")
    page.get_by_test_id("journal-prompt").get_by_role("button").click()
    expect(page.get_by_test_id("journal-prompt")).to_have_count(0)
    expect(page.get_by_test_id("journal-tag")).to_have_value(tag)
    # Leaving and coming back gives an empty composer, and Start on the same task brings its question and tag back.
    _coach(page, "plan")
    _expand_all(page)
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("journal-prompt").wait_for()
    expect(page.get_by_test_id("journal-tag")).to_have_value(tag)
    expect(page.get_by_test_id("journal-text")).to_have_value("")


def test_qa3_saving_after_the_question_was_closed_clears_the_composer(page: Page) -> None:
    _open(page, "coach=report&plan=current&journal=some")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Reflection:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("journal-prompt").wait_for()
    page.get_by_test_id("journal-text").fill("Saved after closing.")
    page.get_by_test_id("journal-prompt").get_by_role("button").click()
    page.get_by_test_id("journal-save").click()
    expect(page.locator('[data-testid^="journal-entry-"]').filter(has_text="Saved after closing.")).to_be_visible()
    expect(page.get_by_test_id("journal-text")).to_have_value("")
    expect(page.get_by_test_id("journal-tag")).to_have_value("")
    expect(page.get_by_test_id("journal-tag-day")).to_have_value("")


def test_qa3_a_day_tag_chosen_by_hand_shows_its_badge(page: Page) -> None:
    _journal(page)
    _pick(page, "journal-tag-day")
    page.get_by_test_id("journal-text").fill("With a day.")
    page.get_by_test_id("journal-save").click()
    entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="With a day.")
    expect(entry.locator('[data-testid^="journal-day-"]')).to_contain_text("Plan:")


def test_qa3_send_to_coach_from_my_games_shows_what_was_sent_whatever_tab_you_left(page: Page) -> None:
    _open(page, "coach=report&plan=current&games=some")
    _coach(page, "plan")
    page.get_by_test_id("nav-games").click()
    row = page.locator('[data-testid^="game-row-"]').first
    row.wait_for()
    row.get_by_role("checkbox").check()
    page.get_by_test_id("send-to-coach").click()
    expect(page.get_by_test_id("coach-sent")).to_be_visible(timeout=5_000)


def test_qa3_an_info_mark_opens_when_you_reach_it_with_tab(page: Page) -> None:
    _journal(page)
    page.get_by_test_id("journal-text").focus()
    for _ in range(15):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.getAttribute('data-option-info')") == "journal.show":
            break
    expect(page.get_by_role("tooltip").filter(has_text="Which kinds of entry")).to_be_visible()


def test_qa3_the_last_search_typed_is_the_one_shown(page: Page) -> None:
    _journal(page)
    box = page.get_by_test_id("journal-search")
    for _ in range(10):
        box.press_sequentially("zzzz-no-such-word", delay=0)
        expect(page.get_by_test_id("journal-empty")).to_be_visible()
        box.fill("")
        page.get_by_test_id("journal-log").first.wait_for()
