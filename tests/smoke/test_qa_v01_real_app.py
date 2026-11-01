"""QA v0.1: the main v0.1 flow in the real app (pywebview + WebView2 over CDP), on the fixture DB.

`uv run pytest -m smoke tests/smoke/test_qa_v01_real_app.py` (needs `npm.cmd --prefix web run build`).
Screenshots go to tests/e2e/artifacts/ (gitignored). xfail(strict=True) marks an open bug by its ID.
"""

from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path

import pytest

import weaksquare
from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke
ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts"
FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "puzzles_sample.csv"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(ART / f"qa-v01-real-{name}.png"))


@pytest.fixture
def data_dir(tmp_path: Path, fixture_puzzles_db: Path) -> Path:
    d = tmp_path / "app-data"
    d.mkdir()
    shutil.copyfile(fixture_puzzles_db, d / "puzzles.db")
    return d


def pick_theme(page, search: str, name: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill(search)
    page.get_by_role("checkbox", name=re.compile("^" + name)).check()
    page.keyboard.press("Escape")


def your_turn(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=15_000)


def test_main_flow_alternative_mate_wrong_move_persistence(pw, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    """Filters -> live count -> solve with the alternative mate (001KR: d1d8 instead of f1f8) ->
    wrong move on the next puzzle -> About paths -> close -> reopen: filters and totals persisted."""
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            count = page.get_by_test_id("match-count")
            count.filter(has_text="match").wait_for(timeout=30_000)
            everything = count.inner_text()
            shot(page, "mixer")
            pick_theme(page, "mate in 1", "Mate in 1")
            page.get_by_label("Minimum rating").fill("563")
            page.get_by_label("Minimum rating").press("Enter")
            page.get_by_label("Maximum rating").fill("563")
            page.get_by_label("Maximum rating").press("Enter")
            count.filter(has_text=re.compile(r"^1 puzzle matches$")).wait_for()  # v0.1-B5: singular
            assert count.inner_text() != everything
            page.get_by_label("Puzzles").fill("2")
            page.wait_for_timeout(800)  # let the filters save (500 ms debounce)
            page.get_by_role("button", name="Start").click()
            your_turn(page)
            assert page.get_by_test_id("outcome").count() == 0  # FR-3.14
            assert "you play white" in page.get_by_test_id("puzzle-header").inner_text()
            shot(page, "trainer")
            play(page, "d1d8", "white")  # the other mate
            page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
            assert "Mate in 1" in page.get_by_test_id("outcome-themes").inner_text()
            page.get_by_test_id("stat-solved").filter(has_text="1").wait_for()
            shot(page, "solved")
            page.get_by_test_id("next-button").click()
            # Only one puzzle matches, so a queue of 2 ends after it.
            page.get_by_test_id("session-complete").wait_for()
            shot(page, "session-complete")

            # About shows the real paths and the fixture's export date.
            page.get_by_role("button", name="Menu").click()
            page.get_by_role("menuitem", name="About").click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("Data folder").wait_for()
            text = dialog.inner_text()
            assert str(data_dir) in text and str(data_dir / "logs") in text
            assert "2026-10-02" in text
            shot(page, "about")
            page.keyboard.press("Escape")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()

    log = (data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    first = log.splitlines()[0]
    assert weaksquare.__version__ in first and "Python" in first, first  # NFR-4 version banner

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            # v0.2: Exclude solved (on by default) leaves out the puzzle solved above…
            page.get_by_test_id("match-count").filter(has_text=re.compile(r"^0 ")).wait_for(timeout=30_000)
            page.get_by_test_id("more-filters").click()
            page.get_by_test_id("exclude-solved").uncheck()  # …until you ask for it back
            page.get_by_test_id("match-count").filter(has_text=re.compile(r"^1 ")).wait_for()
            assert page.get_by_test_id("themes-picker").inner_text().strip() == "1 selected"
            assert page.get_by_label("Minimum rating").input_value() == "563"
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("stat-all-time").filter(has_text="1 solved, 0 failed").wait_for()
            your_turn(page)
            play(page, "f1f2", "white")  # wrong
            page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
            page.get_by_test_id("stat-all-time").filter(has_text="1 solved, 1 failed").wait_for()
            shot(page, "failed")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()


def test_two_quick_clicks_on_skip_fail_only_one_puzzle(pw, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_role("button", name="Start").click()
            your_turn(page)
            page.evaluate(
                "() => { const b = document.querySelector('[data-testid=next-button]'); b.click(); b.click(); }"
            )
            page.wait_for_timeout(2000)
            failed = page.get_by_test_id("stat-failed").inner_text()
            header = page.get_by_test_id("puzzle-header").inner_text()
        app.close()
    finally:
        if app.process.poll() is None:
            app.process.kill()
    # One skip is one loss, and you should be looking at puzzle 2.
    assert (failed, header.split(" ·")[0]) == ("1", "Puzzle 2 of 20")


def test_reimport_during_a_session_keeps_the_filters(pw, data_dir: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """User Guide: 'You can keep training while it runs; the new puzzles are switched in when it's
    finished.' Rating 400-600 must still hold for the rest of the running session."""
    subset = tmp_path / "newer_export.csv"
    with FIXTURE_CSV.open(encoding="utf-8", newline="") as src, subset.open("w", encoding="utf-8", newline="") as out:
        reader, writer = csv.reader(src), csv.writer(out)
        writer.writerow(next(reader))
        for i, row in enumerate(reader):
            if i % 3:  # a newer export that dropped every third puzzle
                writer.writerow(row)
    app = launch_app(data_dir, free_port())
    ratings: list[int] = []
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_label("Minimum rating").fill("400")
            page.get_by_label("Minimum rating").press("Enter")
            page.get_by_label("Maximum rating").fill("600")
            page.get_by_label("Maximum rating").press("Enter")
            page.get_by_label("Endless").check()
            page.wait_for_timeout(500)
            page.get_by_role("button", name="Start").click()
            your_turn(page)
            job = page.evaluate("p => window.pywebview.api.start_puzzle_import(p)", str(subset))
            assert job["ok"], job
            page.wait_for_function(
                "id => window.pywebview.api.get_job(id).then(r => r.ok && r.data.state === 'done')",
                arg=job["data"],
                timeout=60_000,
                polling=500,
            )
            for _ in range(8):
                page.get_by_test_id("next-button").click()
                your_turn(page)
                header = page.get_by_test_id("puzzle-header").inner_text()
                ratings.append(int(re.search(r"rated (\d+)", header).group(1)))  # type: ignore[union-attr]
            shot(page, "after-reimport")
        app.close()
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert all(400 <= r <= 600 for r in ratings), ratings
