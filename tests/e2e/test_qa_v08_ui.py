"""QA v0.8 (independent), against the mock: the User Guide's new chapters followed step by step, screenshots
of each new screen (tests/e2e/artifacts/, gitignored), and edge cases of the source control. Tests marked
xfail(strict=True) document an open bug by its ID (qa/QA-v0.8.md)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.e2e

ART = Path(__file__).resolve().parent / "artifacts"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v08-{name}.png"), full_page=True)


def test_qa_user_guide_my_games_and_review_steps(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(
        page.base_url + "/?showbest=1"
    )  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    page.get_by_role("button", name="My games").click()  # "Press My games at the top of the window"
    page.get_by_test_id("games-table").wait_for()
    shot(page, "my-games")
    for label in ("Refresh", "Analyze selected", "Import game"):
        assert page.get_by_role("button", name=label).count() >= 1, label
    header = page.get_by_test_id("games-table").locator("thead").inner_text().lower()
    for col in ("date", "platform", "result", "opening", "accuracy", "status"):
        assert col in header, col
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("eval-graph").wait_for()
    shot(page, "review")
    assert page.get_by_text("Engine lines here").count() >= 1
    page.keyboard.press("ArrowRight")  # "or the ← and → keys"
    page.get_by_test_id("retry-start").click()
    page.get_by_test_id("retry-mode").wait_for()
    shot(page, "retry")
    play(page, "f3d4", "white")
    page.get_by_test_id("retry-result").wait_for()
    shot(page, "retry-result")


def test_qa_user_guide_settings_games_labels_and_defaults(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("settings-games")
    panel.scroll_into_view_if_needed()
    shot(page, "settings-games")
    text = panel.inner_text()
    for label in (
        "chess.com username",
        "Sync new games when the app opens",
        "First sync: days back",
        "First sync: at most (games)",
        "Analysis: seconds per position",
        "Key moments",
        "Retry tolerance (cp)",
        "Inaccuracy from (cp)",
        "Mistake from (cp)",
        "Blunder from (cp)",
    ):
        assert label in text, label
    values = [panel.get_by_label(lbl, exact=True).input_value() for lbl in (
        "First sync: days back", "First sync: at most (games)", "Analysis: seconds per position", "Key moments",
        "Retry tolerance (cp)", "Inaccuracy from (cp)", "Mistake from (cp)", "Blunder from (cp)")]  # fmt: skip
    assert values == ["90", "200", "0.3", "5", "30", "50", "100", "200"]  # the guide's defaults
    assert panel.get_by_test_id("games-sync-on-open").is_checked()
    # Settings → Training → "Ask why you missed" offers Game Review only (FR-5.8)
    assert page.get_by_text("Game Review only").count() >= 1


def test_qa_user_guide_import_puzzles_steps(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name=re.compile("Import puzzles from a file")).click()
    page.get_by_test_id("import-puzzles-label").wait_for()
    shot(page, "import-puzzles-dialog")
    assert page.get_by_test_id("import-puzzles-choose").is_disabled()  # no label yet: step 2 comes first
    page.get_by_test_id("import-puzzles-label").fill("QA book")
    page.get_by_test_id("import-puzzles-choose").click()
    report = page.get_by_test_id("import-report")
    report.wait_for()
    shot(page, "import-report")
    assert re.search(r"\d+ added, \d+ already there, \d+ skipped", report.inner_text())


def test_qa_my_puzzles_source_greys_lichess_filters_and_both_keeps_them(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("lichess-only-note").wait_for()
    shot(page, "mixer-my-puzzles")
    page.get_by_test_id("source-select").get_by_text("Both").click()
    page.get_by_test_id("my-puzzles-filters").wait_for()
    assert page.get_by_test_id("lichess-only-note").count() == 0  # with Both, Lichess filters still apply
    shot(page, "mixer-both")


# Regression test for v0.8-B4 (fixed in the QA fix loop).
def test_qa_a_lichess_only_mode_after_choosing_my_puzzles_can_start(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("my-puzzles-filters").wait_for()
    page.get_by_test_id("mode-control").get_by_text("Danger spotting", exact=True).click()
    page.wait_for_timeout(300)
    shot(page, "locked-source")
    page.get_by_role("button", name="Start").click()
    page.wait_for_timeout(1000)
    shot(page, "locked-source-start")
    # The control shows "Lichess DB" (locked, with a tooltip), so Start should run a Lichess session.
    assert page.get_by_text("Choose Lichess DB for this mode").count() == 0


# Regression test for v0.8-B6 (fixed in the QA fix loop).
def test_qa_a_my_puzzle_has_no_lichess_link_and_no_rated_promise(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("match-count").filter(has_text="1 puzzle").wait_for()
    rated_text = page.get_by_test_id("rated-switch").locator("xpath=ancestor::div[1]").inner_text()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("puzzle-header").filter(has_text="my puzzle").wait_for()
    page.wait_for_timeout(700)
    play(page, "d1d8", "white")
    page.get_by_test_id("outcome").wait_for()
    shot(page, "my-puzzle-outcome")
    links = page.get_by_text("Open this puzzle on Lichess")
    href = links.first.get_attribute("href") if links.count() else None
    # Your own puzzle isn't on Lichess, and it never counts toward your Lichess rating (FR-3.15).
    assert href is None, href
    assert "count toward your Lichess puzzle rating" not in rated_text


def test_v08_b7_long_engine_lines_are_shortened(page) -> None:  # type: ignore[no-untyped-def]
    """Regression test for v0.8-B7: at most 8 moves of a line are shown, then an ellipsis."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("move-5").click()
    for text in page.get_by_test_id("review-lines").get_by_role("button").all_inner_texts():
        assert len(text.replace(" …", "").split()) <= 8


def test_qa_r2_b8_a_saved_game_puzzle_without_stockfish_shows_the_strict_note(page) -> None:  # type: ignore[no-untyped-def]
    """QA round 2 (v0.8-B8): Save a key moment with no engine installed, then drill it from My puzzles."""
    page.goto(page.base_url + "/?engine=missing")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("save-6").click()
    page.get_by_test_id("saved-note").filter(has_text="Saved to My puzzles").wait_for()
    page.get_by_test_id("nav-puzzles").click()
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("puzzle-header").filter(has_text="my puzzle").wait_for()
    page.get_by_test_id("strict-note").filter(has_text="only this puzzle's saved line counts").wait_for()
    page.wait_for_timeout(1200)  # the board is set up after the usual short delay
    shot(page, "r2-strict-note")


def test_qa_r2_b4_the_source_follows_a_lichess_only_mode(page) -> None:  # type: ignore[no-untyped-def]
    """QA round 2 (v0.8-B4): the shown source and the filters agree after the mode switch."""
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("my-puzzles-filters").wait_for()
    page.get_by_test_id("mode-control").get_by_text("Name the idea first", exact=True).click()
    page.get_by_test_id("my-puzzles-filters").wait_for(state="detached")
    assert page.get_by_test_id("lichess-only-note").count() == 0
    page.get_by_test_id("mode-control").get_by_text("Standard", exact=True).click()
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()  # it can be chosen again
    page.get_by_test_id("my-puzzles-filters").wait_for()
    shot(page, "r2-source-after-mode")
