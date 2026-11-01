"""QA v0.2: UI edge cases against the mock, plus screenshots of every v0.2 screen in Light and Dark
into tests/e2e/artifacts/ (gitignored) for the visual check. Written by the independent QA pass
(qa/QA-v0.2.md).

The mock serves DtKOy first: you play black, the solution is d5c3 (then b1b5) c3d1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_qa_v01_ui import your_turn

pytestmark = pytest.mark.e2e
ART = Path(__file__).resolve().parent / "artifacts" / "qa-v02"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"), full_page=True)


def go(page, scheme: str = "light", scenario: str = "") -> None:  # type: ignore[no-untyped-def]
    q = f"?scheme={scheme}" + (f"&scenario={scenario}" if scenario else "")
    page.goto(page.base_url + "/" + q)
    if scenario not in ("empty", "upgrade"):
        page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()


def menu(page, item: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name=item).click()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_screenshots_of_every_v02_screen(page, scheme: str) -> None:  # type: ignore[no-untyped-def]
    go(page, scheme)
    page.get_by_test_id("more-filters").click()
    page.get_by_test_id("openings-select").wait_for()
    shot(page, f"{scheme}-mixer-more-filters")
    page.get_by_test_id("more-filters").click()
    page.get_by_test_id("ratio-switch").click()
    page.get_by_test_id("ratio-editor").wait_for()
    shot(page, f"{scheme}-ratio-editor")
    page.get_by_test_id("ratio-weight-0").fill("70")
    shot(page, f"{scheme}-ratio-editor-bad-total")
    page.get_by_test_id("ratio-weight-0").fill("50")
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("Combo night")
    shot(page, f"{scheme}-preset-save")
    page.keyboard.press("Escape")
    page.get_by_test_id("ratio-switch").click()

    page.get_by_role("button", name="Start").click()
    your_turn(page)
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    shot(page, f"{scheme}-hint")
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-player").wait_for()
    page.get_by_role("button", name="Forward").click()
    shot(page, f"{scheme}-answer")
    for item, test_id in (("Stats", "stats-view"), ("Settings…", "settings"), ("Keyboard shortcuts", "shortcuts-list")):
        menu(page, item)
        page.get_by_test_id(test_id).wait_for()
        shot(page, f"{scheme}-{test_id}")
        page.keyboard.press("Escape")
        page.get_by_test_id(test_id).wait_for(state="hidden")
    menu(page, "Update puzzle database…")
    page.get_by_test_id("import-view").wait_for()
    shot(page, f"{scheme}-update-dialog")

    go(page, scheme, "update")
    page.get_by_test_id("update-banner").wait_for()
    shot(page, f"{scheme}-update-banner")
    go(page, scheme, "empty")
    page.get_by_test_id("import-view").wait_for()
    shot(page, f"{scheme}-first-run")


def test_ratio_groups_without_themes_disable_start_and_say_why(page) -> None:  # type: ignore[no-untyped-def]
    go(page)
    page.get_by_test_id("ratio-switch").click()
    page.get_by_test_id("ratio-editor").wait_for()
    page.wait_for_timeout(700)
    assert page.get_by_test_id("start").is_disabled()
    text = page.get_by_test_id("match-count").inner_text()
    assert "theme" in text.lower(), text


def test_rapid_hint_clicks_fail_the_puzzle_once(page) -> None:  # type: ignore[no-untyped-def]
    go(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    page.evaluate(
        "() => { const b = document.querySelector('[data-testid=hint-button]'); b.click(); b.click(); b.click(); }"
    )
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.wait_for_timeout(500)
    assert page.get_by_test_id("stat-failed").inner_text() == "1"


def test_hint_key_after_solving_does_nothing(page) -> None:  # type: ignore[no-untyped-def]
    go(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert page.get_by_test_id("hint-button").is_disabled()
    page.keyboard.press("h")
    page.wait_for_timeout(300)
    assert page.get_by_test_id("board").get_attribute("data-hint") == ""
    assert page.get_by_test_id("stat-solved").inner_text() == "1"
    assert page.get_by_test_id("stat-failed").inner_text() == "0"


def test_shortcut_keys_ignored_in_the_preset_dialog(page) -> None:  # type: ignore[no-untyped-def]
    go(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("")
    page.get_by_test_id("preset-name").type("nhac")  # N, H, A and C are all shortcuts
    assert page.get_by_test_id("preset-name").input_value() == "nhac"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.get_by_test_id("stat-failed").inner_text() == "0"  # nothing skipped or hinted
    assert page.get_by_test_id("board").get_attribute("data-hint") == ""


def test_only_my_misses_greys_out_exclude_solved(page) -> None:  # type: ignore[no-untyped-def]
    go(page)
    page.get_by_test_id("more-filters").click()
    page.get_by_test_id("only-misses").check()
    assert page.get_by_test_id("exclude-solved").is_disabled()
    page.get_by_test_id("only-misses").uncheck()
    assert page.get_by_test_id("exclude-solved").is_enabled()


def test_preset_name_of_61_characters_is_refused(page) -> None:  # type: ignore[no-untyped-def]
    go(page)
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("x" * 61)
    page.get_by_test_id("preset-confirm").click()
    value = page.get_by_test_id("preset-name").input_value()
    err = page.get_by_test_id("preset-error")
    # Either the box stops at 60, or a clear error is shown; a 61-character preset must not exist.
    assert len(value) <= 60 or err.is_visible()
    names = page.evaluate("window.__mockApi.calls")
    assert not any(isinstance(c, str) and c.startswith("save_preset:" + "x" * 61) for c in names)


def test_enter_after_a_mouse_session_goes_to_the_next_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    """User Guide, Keyboard shortcuts: 'N or Enter: Next puzzle'. Start and solve with the mouse (focus
    stays on Start), then press Enter: you should get puzzle 2 of the same session."""
    go(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    page.keyboard.press("Enter")
    your_turn(page)
    assert page.get_by_test_id("stat-solved").inner_text() == "1"  # the session wasn't restarted
    assert page.get_by_test_id("puzzle-header").inner_text().startswith("Puzzle 2 of 20")
