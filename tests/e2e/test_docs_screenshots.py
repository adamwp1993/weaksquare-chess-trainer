"""Regenerate the User Guide screenshots in docs/img/ from the mock client with fixed data.

    uv run pytest -m docs_screenshots

Never hand-edit the images: change the UI or the mock data, then re-run this.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.docs_screenshots
IMG = Path(__file__).resolve().parents[2] / "docs" / "img"


@pytest.fixture(scope="module")
def browser(pw):  # type: ignore[no-untyped-def]
    """Screenshots must come out byte for byte the same (v0.1-B14, v0.2-B5): GPU rasterization and
    LCD text antialiasing vary by a pixel between runs, so render in software, without them."""
    b = pw.chromium.launch(args=["--disable-gpu", "--disable-lcd-text", "--disable-partial-raster",
                                 "--font-render-hinting=none", "--force-color-profile=srgb"])  # fmt: skip
    yield b
    b.close()


def panel_top(page) -> None:  # type: ignore[no-untyped-def]
    """Scroll the filter panel to the top: where focus left it depends on timing (v0.2-B5), and the
    reader should see the panel's title, Preset and Mix by ratio."""
    page.locator("[data-testid=mixer-scroll] .mantine-ScrollArea-viewport").first.evaluate("e => e.scrollTo(0, 0)")
    page.mouse.move(1270, 890)  # no hover highlight anywhere


def shot(page, name: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
    IMG.mkdir(parents=True, exist_ok=True)
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(1000)  # let transitions (focus rings, the segmented-control indicator) settle (v0.2-B5)
    page.screenshot(path=str(IMG / f"{name}.png"), animations="disabled", **kwargs)


def test_first_run(page) -> None:  # type: ignore[no-untyped-def]
    page.clock.install()  # the mock's import progress runs on timers; step through them exactly
    page.goto(page.base_url + "/?scenario=empty")
    page.get_by_test_id("import-view").wait_for()
    shot(page, "first-run")
    page.get_by_role("button", name="Download from Lichess").click()
    page.clock.run_for(650)
    page.get_by_test_id("import-message").filter(has_text="Importing").wait_for()
    page.screenshot(path=str(IMG / "first-run-importing.png"), animations="disabled")


def test_choosing_puzzles(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("themes-picker").click()
    page.get_by_role("checkbox", name=re.compile("^Fork")).check()
    shot(page, "theme-picker")
    page.keyboard.press("Escape")
    page.get_by_text("ALL", exact=True).click()
    page.get_by_label("Minimum rating").fill("1100")
    page.get_by_label("Minimum rating").press("Enter")
    page.get_by_label("Maximum rating").fill("1700")
    page.get_by_label("Maximum rating").press("Enter")
    page.get_by_label("2 moves").check()
    page.get_by_test_id("match-count").filter(has_text="307,865").wait_for()
    page.locator("body").click(position={"x": 1100, "y": 600})  # take focus out of the rating box
    page.set_viewport_size({"width": 1280, "height": 1180})  # the whole panel, down to Start
    panel_top(page)
    shot(page, "mixer")


def test_solving(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    shot(page, "trainer")
    play(page, "d5c3", "black")  # DtKOy, the mock's first puzzle
    page.wait_for_timeout(900)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    shot(page, "solved")


def test_about(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="About").click()
    page.get_by_role("dialog").get_by_text("Data folder").wait_for()
    shot(page, "about")


def _pick(page, test_id: str, name: str) -> None:  # type: ignore[no-untyped-def]
    """Tick one theme in a picker, then wait for its list to close, so the next picker's `.last`
    checkbox can't be one from this list while it's still fading out (v0.5-B8)."""
    page.get_by_test_id(test_id).click()
    dropdown_id = page.get_by_test_id(test_id).get_attribute("aria-controls")
    dropdown = page.locator(f"[id='{dropdown_id}']")
    dropdown.wait_for()
    dropdown.get_by_role("checkbox", name=re.compile(f"^{name}")).check()
    page.keyboard.press("Escape")
    dropdown.wait_for(state="hidden")


def test_presets(page) -> None:  # type: ignore[no-untyped-def]
    """A 50/30/20 ratio being saved as "Combo night" (v0.2)."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("ratio-switch").click()
    _pick(page, "ratio-themes-0", "Fork")
    _pick(page, "ratio-themes-1", "Discovered attack")
    page.get_by_role("button", name="Add group").click()
    _pick(page, "ratio-themes-2", "Mate in 1")
    for i, w in enumerate(("50", "30", "20")):
        page.get_by_test_id(f"ratio-weight-{i}").fill(w)
    page.get_by_test_id("ratio-total").filter(has_text="Total 100%").wait_for()
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.evaluate("document.activeElement && document.activeElement.blur()")  # the last share box (v0.2-B5)
    page.wait_for_timeout(500)
    panel_top(page)
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill("Combo night")
    shot(page, "presets")


def test_stats(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-view").wait_for()
    shot(page, "stats")


def test_hint_and_answer(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Hint").wait_for()
    shot(page, "hint")
    page.get_by_test_id("answer-button").click()
    page.get_by_role("button", name="Forward").click()
    page.get_by_test_id("answer-step").filter(has_text="1/3").wait_for()
    shot(page, "answer")


def test_settings_and_dark_mode(page) -> None:  # type: ignore[no-untyped-def]
    """The Settings dialog, and the trainer in Dark (v0.2, FR-1.12, FR-1.13)."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Settings…").click()
    page.get_by_test_id("settings").wait_for()
    shot(page, "settings")

    page.goto(page.base_url + "/?scheme=dark")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    shot(page, "trainer-dark")


def test_update_banner(page) -> None:  # type: ignore[no-untyped-def]
    """FR-2.5: the banner offering a newer puzzle database (v0.2)."""
    page.goto(page.base_url + "/?scenario=update")
    page.get_by_test_id("update-banner").wait_for()
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    shot(page, "update-banner")


def test_startup(page) -> None:  # type: ignore[no-untyped-def]
    """v0.3: the startup page, signed out (the first thing a new user sees)."""
    page.goto(page.base_url + "/?startup=show&account=signed_out")
    page.get_by_test_id("startup").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "startup")


def test_rating_change(page) -> None:  # type: ignore[no-untyped-def]
    """v0.3: a solved, rated puzzle with Lichess's +8, the header rating and the session total."""
    from tests.e2e.test_mixer_v02 import pick_theme
    from tests.e2e.test_qa_v01_ui import your_turn

    page.goto(page.base_url + "/?sync=slow")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    pick_theme(page, "themes-picker", "mate in 1", "Mate in 1")
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "f1f8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    page.evaluate("window.__mockSyncNow()")
    page.get_by_test_id("rating-change").filter(has_text="+8").wait_for()
    page.get_by_test_id("session-rating").filter(has_text="+8 this session").wait_for()
    panel_top(page)
    shot(page, "rating-change")


def _start(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()


def _solve(page) -> None:  # type: ignore[no-untyped-def]
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


def test_engine_panel_and_analysis_board(page) -> None:  # type: ignore[no-untyped-def]
    """v0.4: the post-puzzle engine panel, and the analysis board after one move (FR-7.2, 7.7)."""
    _start(page)
    _solve(page)
    page.get_by_test_id("engine-line").first.wait_for()
    page.mouse.move(1270, 890)
    shot(page, "engine-panel")
    page.get_by_test_id("analyze-button").click()
    play(page, "b5b8", "black")  # Rb8 on the analysis board (white to move after the solution)
    page.get_by_test_id("analysis-moves").filter(has_text="Rb8").wait_for()
    page.get_by_test_id("engine-line").first.wait_for()
    page.wait_for_function("() => document.querySelector('[data-testid=board]').getAttribute('data-arrows') !== ''")
    page.mouse.move(1270, 890)
    shot(page, "analysis-board")


def test_refutation(page) -> None:  # type: ignore[no-untyped-def]
    """v0.4 (§7.2 step 2): after a wrong move, "Why h6 fails" sits above the answer; Show me steps it."""
    _start(page)
    play(page, "h7h6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("refutation-label").filter(has_text="Why h6 fails").wait_for()
    page.get_by_test_id("refutation-show").click()
    page.get_by_test_id("line-preview").get_by_role("button", name="Forward").click()
    page.get_by_test_id("line-preview").get_by_role("button", name="Forward").click()
    page.mouse.move(1270, 890)
    shot(page, "refutation")


def test_engine_install(page) -> None:  # type: ignore[no-untyped-def]
    """v0.4 (FR-7.5): the banner where the engine would be, when Stockfish isn't installed."""
    _start(page, "?engine=missing")
    _solve(page)
    page.get_by_test_id("engine-banner").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "engine-install")


def test_settings_engine(page) -> None:  # type: ignore[no-untyped-def]
    """v0.4 (FR-7.4, 7.5): Settings, scrolled to the Engine section."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("gear").click()
    section = page.get_by_test_id("engine-settings")
    section.get_by_test_id("engine-in-use").wait_for()
    section.scroll_into_view_if_needed()
    page.mouse.move(1270, 890)
    shot(page, "settings-engine")


def test_show_me(page) -> None:  # type: ignore[no-untyped-def]
    """v0.4 (FR-7.7): stepping through one of Stockfish's lines with Show me."""
    _start(page)
    _solve(page)
    page.get_by_test_id("engine-line").first.wait_for()
    page.get_by_test_id("show-line").first.click()
    preview = page.get_by_test_id("line-preview")
    preview.get_by_role("button", name="Forward").click()
    preview.get_by_role("button", name="Forward").click()
    page.mouse.move(1270, 890)
    shot(page, "show-me")


def test_try_again(page) -> None:  # type: ignore[no-untyped-def]
    """v0.4 (FR-5.12): a practice run of a finished puzzle, after one correct move."""
    _start(page)
    play(page, "h7h6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("try-again").click()
    page.get_by_test_id("trainer-message").filter(has_text="Your turn again").wait_for()
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    page.mouse.move(1270, 890)
    shot(page, "try-again")


def _mode(page, label: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("mode-control").get_by_text(label, exact=True).click()


def test_commit_the_line(page) -> None:  # type: ignore[no-untyped-def]
    """v0.5 (FR-4.2): a line entered on the board, then graded after Submit."""
    page.goto(page.base_url + "/?mode=commit_line")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("commit-controls").wait_for()
    page.wait_for_timeout(700)
    for uci in ("d5c3", "b1b5", "c3d1"):
        play(page, uci, "black")
        page.wait_for_timeout(150)
    page.mouse.move(1270, 890)
    shot(page, "commit-entry")
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("commit-result").wait_for()
    panel_top(page)
    shot(page, "commit-result")


def test_spaced_repetition(page) -> None:  # type: ignore[no-untyped-def]
    """v0.5 (FR-4.6): the filters panel in Spaced repetition."""
    page.goto(page.base_url + "/?mode=spaced_repetition")
    page.get_by_test_id("srs-due").filter(has_text="due now").wait_for()
    panel_top(page)
    shot(page, "spaced-repetition")


def test_depth_ladder(page) -> None:  # type: ignore[no-untyped-def]
    """v0.5 (FR-4.5): Order set to Depth ladder, with its status line."""
    page.goto(page.base_url + "/")
    page.get_by_label("Order").get_by_text("Depth ladder").click()
    page.get_by_test_id("ladder-status").wait_for()
    page.get_by_test_id("match-count").filter(has_text="at short").wait_for()
    page.get_by_test_id("ladder-status").scroll_into_view_if_needed()
    page.mouse.move(1270, 890)
    shot(page, "depth-ladder")


def test_filters_hidden(page) -> None:  # type: ignore[no-untyped-def]
    """v0.5 (FR-1.14): the filters panel hidden while you play."""
    _start(page)
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    page.get_by_test_id("filters-summary").filter(has_text="puzzles").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "filters-hidden")


def test_name_the_idea(page) -> None:  # type: ignore[no-untyped-def]
    """v0.6 (FR-4.3): tagging the idea before you move, then the tag score after the end."""
    page.goto(page.base_url + "/?mode=name_idea")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("idea-tags").wait_for()
    page.get_by_test_id("idea-setup").click()
    page.get_by_role("option", name="Deflection", exact=True).click()
    page.keyboard.press("Escape")
    page.get_by_test_id("idea-payoff").click()
    page.get_by_role("option", name="Fork", exact=True).click()
    page.keyboard.press("Escape")
    panel_top(page)
    shot(page, "name-the-idea")
    page.get_by_test_id("idea-start").click()
    play(page, "d5c3", "black")
    page.wait_for_timeout(600)
    play(page, "c3d1", "black")
    page.get_by_test_id("idea-result").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "name-the-idea-result")


def test_danger_spotting(page) -> None:  # type: ignore[no-untyped-def]
    """v0.6 (FR-4.4): the highlighted move and the Safe / Unsafe call; then punishing a blunder."""
    page.goto(page.base_url + "/?mode=danger_spotting")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("danger-call").wait_for()
    panel_top(page)
    shot(page, "danger-spotting")
    page.get_by_test_id("danger-safe").click()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("danger-call").wait_for()
    page.get_by_test_id("danger-unsafe").click()
    page.get_by_test_id("trainer-message").filter(has_text="punish it").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "danger-punish")


def test_mistake_reasons(page) -> None:  # type: ignore[no-untyped-def]
    """v0.6 (§7.3): the reason chips below the board after a miss, and the Stats breakdown."""
    _start(page)
    play(page, "f7f6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("reason-chips").wait_for()
    page.get_by_test_id("reason-didntLook").click()
    page.get_by_test_id("reason-saved").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "mistake-reasons")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-reasons-tab").click()
    page.get_by_test_id("reasons-trend-table").wait_for()
    shot(page, "stats-reasons")


def test_explain(page) -> None:  # type: ignore[no-untyped-def]
    """v0.7 (FR-8.1–8.5): Explain after a wrong move, with its arrows and circles on the board."""
    _start(page, "?ai=on")
    play(page, "h7h6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_text("Explain (≈ $0.0").wait_for()
    page.get_by_test_id("explain-button").click()
    page.get_by_test_id("explanation").wait_for()
    page.get_by_test_id("line-preview-note").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "explain", full_page=True)  # the explanation card sits below the help buttons


def test_settings_ai(page) -> None:  # type: ignore[no-untyped-def]
    """v0.7 (FR-1.2–1.4, §9.3): Settings → AI explanations, with a provider, model and key set up."""
    page.goto(page.base_url + "/?ai=on")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("gear").click()
    section = page.get_by_test_id("settings-ai")
    section.get_by_test_id("ai-model").wait_for()
    section.evaluate(
        "e => { e.scrollIntoView({block: 'start'}); e.closest('.mantine-Modal-content').scrollBy(0, -60); }"
    )
    page.mouse.move(1270, 890)
    shot(page, "settings-ai")


def test_explain_over_budget(page) -> None:  # type: ignore[no-untyped-def]
    """v0.7 (FR-1.10, 8.13): this month's budget used up: the red indicator and a blocked Explain."""
    _start(page, "?ai=over")
    _solve(page)
    page.get_by_test_id("explain-why").filter(has_text="budget").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "explain-over-budget")


# ---- v0.8: your games, Game Review, Retry, your own puzzles ---------------------------------------


def test_my_games(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-table").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "my-games")


def test_game_review(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("eval-graph").wait_for()
    page.get_by_test_id("move-6").click()
    page.mouse.move(1270, 890)
    shot(page, "game-review", full_page=True)


def test_retry_mode(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("retry-start").click()
    play(page, "e1g1", "white")  # castling: a fine move, but not close enough to Nxd4 (a miss, with the chips)
    page.get_by_test_id("retry-result").wait_for()
    page.mouse.move(1270, 890)
    shot(page, "retry-mode")


def test_import_puzzles_report(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_role("button", name="Menu").click()
    page.get_by_test_id("menu-import-puzzles").click()
    page.get_by_test_id("import-puzzles-label").fill("My book")
    page.get_by_test_id("import-puzzles-choose").click()
    page.get_by_test_id("import-report").wait_for()
    shot(page, "import-puzzles")


def test_my_puzzles_source(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("match-count").filter(has_text="1 puzzle").wait_for()
    panel_top(page)
    shot(page, "my-puzzles-source")
