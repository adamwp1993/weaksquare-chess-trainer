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


def shot(page, name: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
    IMG.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)  # let animations settle
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
    page.get_by_label("Maximum rating").fill("1700")
    page.get_by_label("2 moves").check()
    page.get_by_test_id("match-count").filter(has_text="307,865").wait_for()
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
