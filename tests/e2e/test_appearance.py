"""FR-1.12: every main screen in Light and Dark, with WCAG AA text contrast; Match system follows the
OS setting live; and the choice never touches browser storage.

The contrast check walks every visible text node and compares its color with the first opaque
background behind it: 4.5:1 for normal text, 3:1 for large text (24 px, or 18.66 px bold).
Disabled controls are exempt, as in WCAG.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_qa_v01_ui import your_turn

pytestmark = pytest.mark.e2e

CONTRAST_JS = r"""
() => {
  const parse = (c) => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : [0, 0, 0, 0]; };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const bgOf = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c.length < 4 || c[3] > 0.9) return c;
    }
    return parse(getComputedStyle(document.body).backgroundColor);
  };
  const bad = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent.trim();
    const el = n.parentElement;
    if (!text || !el || !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
    if (el.closest("[disabled], [data-disabled], [aria-disabled='true'], cg-board")) continue;
    const s = getComputedStyle(el);
    const fg = parse(s.color);
    const bg = bgOf(el);
    const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    const ratio = (l1 + 0.05) / (l2 + 0.05);
    const size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (ratio < need) bad.push(`${ratio.toFixed(2)} < ${need}: "${text.slice(0, 40)}" (${s.color} on rgb(${bg.slice(0, 3)}))`);
  }
  return bad;
}
"""


def scheme(page) -> str:  # type: ignore[no-untyped-def]
    return page.evaluate("document.documentElement.getAttribute('data-mantine-color-scheme')")


def check(page, label: str) -> None:  # type: ignore[no-untyped-def]
    page.wait_for_timeout(300)
    bad = page.evaluate(CONTRAST_JS)
    assert bad == [], f"{label}: low contrast\n" + "\n".join(bad)


def go(page, scheme_name: str, scenario: str = "") -> None:  # type: ignore[no-untyped-def]
    q = f"?scheme={scheme_name}" + (f"&scenario={scenario}" if scenario else "")
    page.goto(page.base_url + "/" + q)


def menu(page, item: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name=item).click()


@pytest.mark.parametrize("name", ["light", "dark"])
def test_main_screens_readable(page, name: str) -> None:  # type: ignore[no-untyped-def]
    go(page, name)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    assert scheme(page) == name
    check(page, "mixer")
    page.get_by_test_id("more-filters").click()
    check(page, "more filters")

    page.get_by_role("button", name="Start").click()
    your_turn(page)
    check(page, "trainer")
    play(page, "g7g6", "black")  # wrong: the outcome panel appears
    page.get_by_test_id("outcome").wait_for()
    check(page, "outcome")
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-player").wait_for()
    check(page, "answer")

    for item, test_id in (("Stats", "stats-view"), ("Settings…", "settings"), ("Keyboard shortcuts", "shortcuts-list")):
        menu(page, item)
        page.get_by_test_id(test_id).wait_for()
        check(page, item)
        page.keyboard.press("Escape")
        page.get_by_test_id(test_id).wait_for(state="hidden")
    menu(page, "About")
    page.get_by_role("dialog").get_by_text("Data folder").wait_for()
    check(page, "about")
    page.keyboard.press("Escape")
    menu(page, "Update puzzle database…")
    page.get_by_test_id("import-view").wait_for()
    check(page, "update dialog")


@pytest.mark.parametrize("name", ["light", "dark"])
def test_startup_and_lichess_states_readable(page, name: str) -> None:  # type: ignore[no-untyped-def]
    """v0.3: the startup page in each account state, and the offline sync chip."""
    for account in ("signed_in", "signed_out", "offline", "expired"):
        page.goto(page.base_url + f"/?startup=show&scheme={name}&account={account}")
        page.get_by_test_id("startup").wait_for()
        check(page, f"startup ({account})")
    page.get_by_test_id("startup-continue").click()
    page.goto(page.base_url + f"/?scheme={name}&account=offline")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "g7g6", "black")
    page.get_by_test_id("sync-chip").wait_for()
    check(page, "offline outcome and sync chip")


@pytest.mark.parametrize("name", ["light", "dark"])
def test_first_run_importer_readable(page, name: str) -> None:  # type: ignore[no-untyped-def]
    go(page, name, "empty")
    page.get_by_test_id("import-view").wait_for()
    assert scheme(page) == name
    check(page, "importer")


def test_switching_applies_at_once_and_is_saved_not_stored_in_the_browser(page) -> None:  # type: ignore[no-untyped-def]
    go(page, "light")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    menu(page, "Settings…")
    page.get_by_test_id("color-scheme").get_by_text("Dark", exact=True).click()
    assert scheme(page) == "dark"
    calls = page.evaluate("window.__mockApi.calls")
    assert 'setting:ui.color_scheme="dark"' in calls
    storage = page.evaluate("[localStorage.length, sessionStorage.length, document.cookie]")
    assert storage == [0, 0, ""]


def test_match_system_follows_the_os_live(page) -> None:  # type: ignore[no-untyped-def]
    page.emulate_media(color_scheme="light")
    go(page, "auto")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    assert scheme(page) == "light"
    page.emulate_media(color_scheme="dark")
    for _ in range(20):  # (wait_for_function would eval a string, which the strict CSP forbids)
        if scheme(page) == "dark":
            break
        page.wait_for_timeout(100)
    assert scheme(page) == "dark"


@pytest.mark.parametrize("name", ["light", "dark"])
def test_messages_ratios_and_dialogs_readable(page, name: str) -> None:  # type: ignore[no-untyped-def]
    go(page, name)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("ratio-switch").click()
    page.get_by_test_id("ratio-editor").wait_for()
    page.get_by_test_id("ratio-weight-0").fill("70")  # total 120%: the red total and error count
    check(page, "ratio editor")
    page.get_by_test_id("ratio-weight-0").fill("50")
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("x")
    check(page, "preset dialog")
    page.keyboard.press("Escape")
    page.get_by_test_id("ratio-switch").click()

    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    check(page, "correct message")
    page.wait_for_timeout(600)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    check(page, "solved")


@pytest.mark.parametrize("name", ["light", "dark"])
def test_update_banner_readable(page, name: str) -> None:  # type: ignore[no-untyped-def]
    go(page, name, "update")
    page.get_by_test_id("update-banner").wait_for()
    check(page, "update banner")
