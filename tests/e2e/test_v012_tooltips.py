"""FR-10.72: every setting and option control has a tooltip from the one text table. This walks the screens and fails on
any control without one, so a later version can't add an option and forget it. A control may only opt out with a
`data-no-tip` reason: free text you type, a row you select, a key (see REQUIREMENTS FR-10.72 and plans/v0.12.md)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]

# For every visible option control: is it opted out, or does it have its own tooltip mark? "Its own" means inside the
# control's label, in the group it belongs to, or named by data-option-for. A neighbour's mark doesn't count.
WALK = """
() => {
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const bad = [];
  const seen = new Set();
  const controls = document.querySelectorAll(
    'input:not([type=hidden]), textarea, [role=radiogroup], [role=combobox]'
  );
  for (const el of controls) {
    if (el.getAttribute('aria-hidden') === 'true') continue; // Mantine's hidden autosize copy of a textarea
    const root = el.closest('.mantine-SegmentedControl-root');
    const target = root || el;
    if (seen.has(target)) continue;
    seen.add(target);
    const measured = target.matches('input[type=checkbox], input[type=radio]') ? (target.closest('label, .mantine-Checkbox-root, .mantine-Radio-root, .mantine-Switch-root, .mantine-Chip-root') || target) : target;
    if (!visible(measured)) continue;
    if (el.closest('[data-no-tip]') || (root && root.closest('[data-no-tip]'))) continue;
    const wrapper = el.closest('.mantine-InputWrapper-root, .mantine-Checkbox-root, .mantine-Switch-root, .mantine-Radio-root');
    if (wrapper && wrapper.querySelector('[data-option-info]')) continue;
    const named = el.closest('[data-option-for]');
    if (named && document.querySelector(`[data-option-info="${named.getAttribute('data-option-for')}"]`)) continue;
    const group = target.closest('[data-option-group]');
    if (group && group.querySelector('[data-option-info]')) continue;
    bad.push(el.getAttribute('aria-label') || el.getAttribute('placeholder') || (wrapper && wrapper.textContent) || el.getAttribute('data-testid') || el.outerHTML.slice(0, 120));
  }
  return bad;
}
"""


def _missing(page: Page) -> list[str]:
    return list(page.evaluate(WALK))


def _assert_all_have_tips(page: Page, where: str) -> None:
    missing = _missing(page)
    assert missing == [], f"{where}: option controls with no tooltip: {missing}"


def _tips(page: Page) -> list[str]:
    return list(
        page.evaluate(
            "[...document.querySelectorAll('[data-option-info]')].map((e) => e.getAttribute('data-option-info'))"
        )
    )


def test_the_walk_really_catches_a_control_without_a_tooltip(page: Page) -> None:
    page.goto(page.base_url + "/?coach=report")  # type: ignore[attr-defined]
    page.evaluate(
        "() => { const i = document.createElement('input'); i.type = 'number'; i.setAttribute('aria-label', 'planted'); document.body.appendChild(i); }"
    )
    assert "planted" in _missing(page)


def test_the_mixer(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("trainer-page").wait_for()
    _assert_all_have_tips(page, "Mixer")
    assert "mixer.mode" in _tips(page) and "filters.rating" in _tips(page)


def test_the_mixer_with_ratios_and_my_puzzles(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("trainer-page").wait_for()
    page.get_by_test_id("ratio-switch").check(force=True)
    _assert_all_have_tips(page, "Mixer with ratios")
    page.get_by_test_id("ratio-switch").uncheck(force=True)
    page.get_by_text("My puzzles", exact=True).first.click()
    _assert_all_have_tips(page, "Mixer on My puzzles")


def test_settings(page: Page) -> None:
    page.goto(page.base_url + "/?ai=on&dev=1")  # type: ignore[attr-defined]
    page.get_by_test_id("gear").click()
    page.get_by_test_id("coordinates-switch").wait_for(state="attached")
    # Every panel of the dialog is on one scrolling page.
    expect(page.get_by_test_id("coach-settings")).to_be_visible()
    _assert_all_have_tips(page, "Settings")
    assert len(_tips(page)) > 25


def test_the_coach_report_with_ai(page: Page) -> None:
    page.goto(page.base_url + "/?ai=on&coach=report")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-ai").wait_for()
    _assert_all_have_tips(page, "Coach")
    page.get_by_test_id("coach-ai-advanced").check()
    _assert_all_have_tips(page, "Coach, Advanced on")
    assert {"coach.detail", "coach.advanced", "coach.gameCap", "coach.includeNotes", "coach.includeJournal"} <= set(
        _tips(page)
    )


def test_the_coach_for_another_player(page: Page) -> None:
    page.goto(page.base_url + "/?coach=report")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-page").wait_for()
    page.get_by_text("Another player", exact=True).click()
    _assert_all_have_tips(page, "Coach, another player")


def test_the_plan_and_journal_tabs(page: Page) -> None:
    page.goto(page.base_url + "/?coach=report&plan=current&journal=some")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-plan").click()
    page.get_by_test_id("plan-tab").wait_for()
    _assert_all_have_tips(page, "Plan tab")
    assert {"plan.weeks", "plan.minutes", "plan.weekdays", "plan.carry"} <= set(_tips(page))
    page.get_by_test_id("coach-tab-journal").click()
    page.get_by_test_id("journal-tab").wait_for()
    _assert_all_have_tips(page, "Journal tab")


def test_my_games_and_game_review(page: Page) -> None:
    page.goto(page.base_url + "/?ai=on")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-count").wait_for()
    _assert_all_have_tips(page, "My games")
    page.get_by_role("button", name="Review", exact=True).first.click()
    page.get_by_test_id("review-show-best").wait_for(state="attached")
    _assert_all_have_tips(page, "Game Review")
    page.get_by_test_id("game-note-add").click()
    page.get_by_test_id("game-note-text").wait_for()
    _assert_all_have_tips(page, "Add a note")


def test_the_import_dialog(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-import-game").click()
    page.get_by_test_id("import-url").wait_for(state="attached")
    _assert_all_have_tips(page, "Import a game")


def test_a_tooltip_opens_on_hover_and_on_keyboard_focus_with_its_text(page: Page) -> None:
    page.goto(page.base_url + "/?coach=report")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-page").wait_for()
    info = page.locator('[data-option-info="coach.detail"]')
    info.hover()
    tip = page.get_by_role("tooltip")
    expect(tip).to_contain_text("Summary")
    expect(tip).to_contain_text("Detailed")
    expect(tip).to_contain_text("cost")
    page.mouse.move(0, 0)
    expect(tip).to_have_count(0)
    # By keyboard, as a person would: from the select back onto the mark in its label.
    info.locator("xpath=ancestor::*[contains(@class, 'InputWrapper-root')]//input").first.focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.getAttribute('data-option-info')") == "coach.detail"
    expect(page.get_by_role("tooltip")).to_contain_text("Summary")


def test_the_mark_adds_nothing_to_the_controls_name_and_describes_itself(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("trainer-page").wait_for()
    expect(page.get_by_label("Puzzles", exact=True)).to_be_visible()
    expect(page.get_by_role("switch", name="Endless", exact=True)).to_be_attached()
    mark = page.locator('[data-option-info="mixer.ratio"]')
    assert "shares of different themes" in (mark.get_attribute("aria-description") or "")


def test_clicking_the_mark_does_not_change_the_option(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("trainer-page").wait_for()
    box = page.get_by_test_id("ratio-switch")
    before = box.is_checked()
    page.locator('[data-option-info="mixer.ratio"]').click()
    assert box.is_checked() == before


# ---- the table itself ----


def _table() -> dict[str, str]:
    text = (ROOT / "web/src/text/tooltips.ts").read_text(encoding="utf-8")
    body = text.split("export const TOOLTIPS = {", 1)[1].split("} as const;", 1)[0]
    return dict(re.findall(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",\s*$', body, flags=re.M))


def _used() -> set[str]:
    used: set[str] = set()
    for f in (ROOT / "web/src").rglob("*.tsx"):
        src = f.read_text(encoding="utf-8")
        used |= set(re.findall(r'(?:<Labeled|<OptionInfo) id="([^"]+)"', src))
    return used


def test_the_table_has_plain_non_empty_text() -> None:
    table = _table()
    assert len(table) > 100
    for key, text in table.items():
        assert len(text) >= 15, key
        assert "<" not in text and "http://" not in text, key


def test_every_literal_id_used_is_in_the_table_and_almost_every_entry_is_used() -> None:
    table, used = _table(), _used()
    assert used - set(table) == set()
    # A few ids are built at run time (per feature, per threshold, per picker).
    dynamic = {k for k in table if k.startswith(("ai.model.", "games.inaccuracy", "games.mistake", "games.blunder"))}
    dynamic |= {"filters.themes", "filters.excludeThemes", "filters.ratioThemes"}
    assert set(table) - used - dynamic == set()


def test_no_tooltip_text_lives_outside_the_table() -> None:
    for f in (ROOT / "web/src").rglob("*.tsx"):
        if f.name == "OptionInfo.tsx":
            continue
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"<OptionInfo[^>]*\b(label|text)=", src), f.name
        any_arg: Any = re.search(r"<Labeled[^>]*\b(label|text)=", src)
        assert not any_arg, f.name
