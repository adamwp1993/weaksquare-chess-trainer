"""v0.2 mixer UI against the mock client: presets, ratios, openings, quality, history, order and the
puzzle-database upgrade screen (FR-3.6–3.11, FR-3.13).

The mock scales each of its 10 puzzles to 61,573, so one puzzle reads "61,573 puzzles match".
"""

from __future__ import annotations

import re

import pytest

from tests.e2e.conftest import continue_past_startup, play
from tests.e2e.test_qa_v01_ui import count_text, ready, your_turn

pytestmark = pytest.mark.e2e
ONE = 61_573


def matches(n: int) -> str:
    return f"{n * ONE:,} puzzles match"


def open_more(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("more-filters").click()
    page.get_by_test_id("min-popularity").wait_for()


def pick_theme(page, test_id: str, search: str, name: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id(test_id).click()
    page.get_by_role("textbox", name=re.compile("^Search")).last.fill(search)
    page.get_by_role("checkbox", name=re.compile(f"^{name}")).last.check()  # .last: a closing picker may linger
    page.keyboard.press("Escape")


def test_more_filters_summary_shows_the_defaults(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    summary = page.get_by_test_id("more-summary").inner_text()
    assert "popularity ≥ 50" in summary and "≥ 100 plays" in summary
    assert "solved or played on Lichess left out" in summary  # v0.3: Exclude played on Lichess is on by default


def test_quality_thresholds_change_the_count_and_clear_to_off(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    open_more(page)
    box = page.get_by_test_id("min-popularity")
    box.fill("70")
    box.press("Enter")
    assert count_text(page) == matches(9)  # 0OT49 has popularity 60
    box.fill("")
    box.press("Enter")
    assert count_text(page) == matches(10)
    assert "no quality filter" in page.get_by_test_id("more-summary").inner_text() or "≥ 100 plays" in (
        page.get_by_test_id("more-summary").inner_text()
    )


def test_opening_filter(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    open_more(page)
    page.get_by_test_id("openings-select").click()
    page.keyboard.type("Russian")
    page.get_by_role("option", name=re.compile("^Russian Game \\(any variation\\)")).click()
    page.keyboard.press("Escape")
    assert count_text(page) == matches(1)  # only 01RLM has an opening in the mock


def solve_first_mate_in_one(page) -> None:  # type: ignore[no-untyped-def]
    """Mate in 1, a queue of 1: the mock serves 001KR first (white mates with f1f8)."""
    ready(page)
    pick_theme(page, "themes-picker", "mate in 1", "Mate in 1")
    page.get_by_label("Puzzles", exact=True).fill("1")
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    assert "you play white" in page.get_by_test_id("puzzle-header").inner_text()
    play(page, "f1f8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


def test_solved_puzzle_is_left_out_by_default_and_back_when_unticked(page) -> None:  # type: ignore[no-untyped-def]
    solve_first_mate_in_one(page)
    assert count_text(page) == matches(1)  # 001KR solved: only 01RLM is left
    page.get_by_test_id("next-button").click()
    page.get_by_role("button", name="New session").click()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    assert "001KR" not in page.get_by_test_id("puzzle-header").inner_text()
    assert "rated 883" in page.get_by_test_id("puzzle-header").inner_text()  # 01RLM, not 001KR (563)
    open_more(page)
    page.get_by_test_id("exclude-solved").uncheck()
    # v0.3: signed in, the solve synced to Lichess, so "Exclude played on Lichess" still hides it.
    assert count_text(page) == matches(1)
    page.get_by_test_id("exclude-played").uncheck()
    assert count_text(page) == matches(2)


def test_only_my_misses(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    pick_theme(page, "themes-picker", "mate in 1", "Mate in 1")
    page.get_by_label("Puzzles", exact=True).fill("1")
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    page.get_by_test_id("next-button").click()  # skip: a miss
    page.get_by_role("button", name="New session").click()
    open_more(page)
    page.get_by_test_id("only-misses").check()
    assert page.get_by_test_id("exclude-solved").is_disabled()
    assert count_text(page) == matches(1)


def test_ratio_editor_counts_total_and_left_out_group(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_test_id("ratio-switch").click()
    page.get_by_test_id("ratio-editor").wait_for()
    pick_theme(page, "ratio-themes-0", "fork", "Fork")
    pick_theme(page, "ratio-themes-1", "promotion", "Promotion")
    page.get_by_test_id("ratio-weight-0").fill("70")
    page.get_by_test_id("ratio-total").filter(has_text="Total 120%").wait_for()
    assert "add up to 100%" in count_text(page)
    assert page.get_by_role("button", name="Start").is_disabled()
    page.get_by_test_id("ratio-weight-1").fill("30")
    page.get_by_test_id("ratio-total").filter(has_text="Total 100%").wait_for()
    assert count_text(page) == matches(6)  # 5 forks + 04TL9
    assert page.get_by_test_id("ratio-count-0").inner_text() == f"{5 * ONE:,} puzzles"
    page.get_by_role("button", name="Add group").click()
    page.get_by_test_id("ratio-total").filter(has_text="Total 100%").wait_for()  # re-split 34/33/33
    pick_theme(page, "ratio-themes-2", "skewer", "Skewer")
    page.get_by_test_id("ratio-count-2").filter(has_text="No puzzles").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("start-notice").filter(has_text="group 3").wait_for()
    your_turn(page)


def test_ratio_switch_keeps_your_themes(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    pick_theme(page, "themes-picker", "fork", "Fork")
    page.get_by_test_id("ratio-switch").click()
    assert page.get_by_test_id("ratio-themes-0").inner_text() == "1 selected"
    page.get_by_test_id("ratio-switch").click()
    assert page.get_by_test_id("themes-picker").inner_text() == "1 selected"


def test_presets_save_load_rename_delete(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    pick_theme(page, "themes-picker", "fork", "Fork")
    assert count_text(page) == matches(5)
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("Combo night")
    page.get_by_test_id("preset-confirm").click()
    page.get_by_test_id("preset-name").wait_for(state="hidden")

    # Change the filters, then load the preset back.
    page.get_by_test_id("themes-picker").click()
    page.get_by_role("button", name="Clear").click()
    page.keyboard.press("Escape")
    assert count_text(page) == matches(10)
    page.get_by_test_id("preset-select").click()
    page.get_by_role("option", name="Combo night").click()
    assert count_text(page) == matches(5)

    # Saving under an existing name asks before replacing.
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("combo NIGHT")
    page.get_by_test_id("preset-confirm").click()
    page.get_by_test_id("preset-error").filter(has_text="already exists").wait_for()
    page.get_by_test_id("preset-replace").click()
    page.get_by_test_id("preset-name").wait_for(state="hidden")

    page.get_by_test_id("preset-actions").click()
    page.get_by_role("menuitem", name="Rename…").click()
    page.get_by_test_id("preset-name").fill("Forks")
    page.get_by_test_id("preset-confirm").click()
    page.get_by_test_id("preset-name").wait_for(state="hidden")
    page.get_by_test_id("preset-actions").click()
    page.get_by_role("menuitem", name="Delete…").click()
    page.get_by_test_id("preset-delete-confirm").click()
    page.get_by_test_id("preset-select").click()
    assert page.get_by_role("option", name="Forks").count() == 0


def test_unusable_preset_explains_and_changes_nothing(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    before = count_text(page)
    page.get_by_test_id("preset-select").click()
    page.get_by_role("option", name=re.compile("^Endgame drill")).click()
    page.get_by_test_id("preset-load-error").filter(has_text="can't be used").wait_for()
    assert count_text(page) == before


def test_easy_to_hard_starts_with_the_easiest(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_text("Easy → hard", exact=True).click()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    assert "rated 485" in page.get_by_test_id("puzzle-header").inner_text()  # 04TL9, the easiest


def test_endless_note_for_sorted_orders(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_text("By theme", exact=True).click()
    assert page.get_by_test_id("order-endless-note").count() == 0
    page.get_by_role("switch", name="Endless").dispatch_event("click")
    page.get_by_test_id("order-endless-note").wait_for()


def test_upgrade_screen_runs_and_returns_to_the_mixer(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?scenario=upgrade")
    page.get_by_test_id("upgrade-view").wait_for()
    assert "nothing is downloaded" in page.get_by_test_id("upgrade-view").inner_text()
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=10_000)


def test_importer_names_the_whole_database_and_its_size(page) -> None:  # type: ignore[no-untyped-def]
    """FR-2.1a, in the first-run screen and in the update dialog."""
    page.goto(page.base_url + "/?scenario=empty")
    text = page.get_by_test_id("import-what").inner_text()
    for words in ("entire Lichess puzzle database", "not a sample", "about 300 MB", "6 million puzzles", "1.5 GB"):
        assert words in text, words


def test_user_guide_uses_the_same_wording() -> None:
    from pathlib import Path

    guide = (Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    for words in ("**entire** database", "not a sample", "about 300 MB", "about 6 million puzzles", "1.5 GB"):
        assert words in guide, words


@pytest.mark.parametrize("size", [(1280, 900), (1000, 700), (1920, 1080)])
def test_no_page_scrollbar_beside_the_filter_panel(browser, mock_url: str, size: tuple[int, int]) -> None:  # type: ignore[no-untyped-def]
    """v0.2-B9: the window showed a second, page-level scrollbar next to the filter panel's own.
    Without the update banner the page fits the window; only the panel scrolls."""
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
    page = ctx.new_page()
    try:
        page.goto(mock_url + "/")
        continue_past_startup(page)
        page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
        overflow = page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
        assert overflow <= 0, f"the page is {overflow}px taller than the window"
    finally:
        ctx.close()
