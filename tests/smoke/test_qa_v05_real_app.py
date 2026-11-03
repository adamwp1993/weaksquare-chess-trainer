"""QA v0.5: training modes in the real app (WebView2 over CDP), on the fixture DB and a temp data folder.
Written by the independent QA pass (qa/QA-v0.5.md). Screenshots go to tests/e2e/artifacts/qa-v05-real/.

Covers: the Modes control, a Commit-the-line submit (both sides entered on the board), switching mode
mid-session, Hide filters surviving a relaunch through the bridge, and the dev-only fast-forward
bringing a miss back in Spaced repetition."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke
ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts" / "qa-v05-real"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"))


def solution_for(puzzles_db: Path, board_fen: str) -> list[str]:
    conn = sqlite3.connect(puzzles_db)
    try:
        rows = conn.execute("SELECT fen, moves FROM puzzles").fetchall()
    finally:
        conn.close()
    for fen, moves in rows:
        b = chess.Board(fen)
        b.push_uci(moves.split()[0])
        if b.board_fen() == board_fen.split()[0]:
            return moves.split()
    raise AssertionError("puzzle not found")


def q(user_db: Path, sql: str) -> list[tuple]:  # type: ignore[type-arg]
    conn = sqlite3.connect(user_db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def choose_mode(page, label: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("mode-control").get_by_text(label, exact=True).click()


def wait_turn(page) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    page.get_by_test_id("trainer-message").filter(has_text="Enter the whole line").or_(
        page.get_by_test_id("trainer-message").filter(has_text="Your turn")
    ).wait_for(timeout=30_000)
    page.wait_for_timeout(300)
    fen = page.get_by_test_id("board").get_attribute("data-fen")
    color = "white" if chess.Board(fen).turn == chess.WHITE else "black"
    return fen, color


def test_v05_modes_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    user_db = data_dir / "user.db"

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            assert page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value") == "standard"

            # Commit the line: enter the whole solution, both sides, then Submit
            choose_mode(page, "Commit the line")
            page.get_by_test_id("show-length-switch").wait_for()
            page.get_by_label("Puzzles").fill("5")
            page.get_by_role("button", name="Start").click()
            fen, color = wait_turn(page)
            moves = solution_for(data_dir / "puzzles.db", fen)
            assert page.get_by_test_id("engine-panel").count() == 0
            for uci in moves[1:]:
                play(page, uci, color)
                page.wait_for_timeout(150)
            n = len(moves) - 1
            page.get_by_test_id("commit-count").filter(has_text=f"{n} move").wait_for()
            assert page.get_by_test_id("outcome").count() == 0  # nothing graded before Submit
            shot(page, "commit-entry")
            page.get_by_test_id("commit-submit").click()
            page.get_by_test_id("outcome").filter(has_text="Solved").wait_for(timeout=10_000)
            replies = n // 2
            if replies:  # QA v0.6: a one-move puzzle has no replies line (v0.5-B4), so this flaked on those
                assert (
                    page.get_by_test_id("commit-calculation").inner_text()
                    == f"Replies predicted: {replies} of {replies}"
                )
            else:
                assert page.get_by_test_id("commit-calculation").count() == 0
            shot(page, "commit-result")
            assert q(user_db, "SELECT mode, win, replies_correct, replies_total FROM attempts") == [
                ("commit_line", 1, replies, replies)
            ]

            # Switch mode mid-puzzle: a new session, nothing recorded for the puzzle in progress
            page.get_by_test_id("next-button").click()
            wait_turn(page)
            choose_mode(page, "Standard")
            page.get_by_test_id("session-mode").filter(has_text="Standard").wait_for(timeout=10_000)
            assert q(user_db, "SELECT COUNT(*) FROM attempts") == [(1,)]
            assert [r[0] for r in q(user_db, "SELECT mode FROM sessions ORDER BY id")] == ["commit_line", "standard"]

            # Miss one (skip), then fast-forward a day (dev) and review it in Spaced repetition
            wait_turn(page)
            page.get_by_test_id("next-button").click()  # skip = a miss
            wait_turn(page)
            choose_mode(page, "Spaced repetition")
            # Nothing due yet: the switch can't start a session, so Standard carries on (v0.5-B1 fix).
            page.get_by_test_id("start-error").filter(has_text="Nothing is due").wait_for(timeout=10_000)
            assert page.get_by_test_id("session-mode").inner_text() == "Standard"
            page.get_by_test_id("gear").click()
            page.get_by_test_id("time-offset").fill("1")
            page.get_by_test_id("time-offset-apply").click()
            page.keyboard.press("Escape")
            page.get_by_test_id("time-offset-banner").filter(has_text="+1 day").wait_for(timeout=10_000)
            choose_mode(page, "Spaced repetition")  # now due: the switch starts the review session
            page.get_by_test_id("srs-due").filter(has_text="1 puzzle due now").wait_for(timeout=10_000)
            shot(page, "srs-due")
            page.get_by_test_id("session-mode").filter(has_text="Spaced repetition").wait_for(timeout=10_000)
            wait_turn(page)

            # Hide the filters, then relaunch: still hidden
            page.get_by_test_id("hide-filters").click()
            page.get_by_test_id("filters-strip").wait_for()
            shot(page, "collapsed")
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            # Turn fast-forward off again before closing
            page.get_by_test_id("gear").click()
            page.get_by_test_id("time-offset").fill("0")
            page.get_by_test_id("time-offset-apply").click()
            page.keyboard.press("Escape")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()

    settings = dict(q(user_db, "SELECT key, value FROM settings"))
    assert settings.get("ui.filters_collapsed") == "true", settings
    assert settings.get("trainer.mode") == '"spaced_repetition"', settings

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("filters-strip").wait_for(timeout=30_000)  # survived the relaunch
            assert not page.get_by_test_id("mixer-column").is_visible()
            summary = page.get_by_test_id("filters-summary").inner_text()
            assert summary.startswith("Spaced repetition"), summary
            page.get_by_test_id("show-filters").click()
            page.get_by_test_id("mixer-column").wait_for(state="visible")
            checked = page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value")
            assert checked == "spaced_repetition"
            assert page.get_by_test_id("time-offset-banner").count() == 0
            shot(page, "after-relaunch")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()


def test_rapid_mode_switching_ends_on_the_chosen_mode(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    """Several quick clicks on the Modes control while a session runs: the session that ends up on
    screen must be in the mode the control shows."""
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_role("button", name="Start").click()
            wait_turn(page)
            for _ in range(4):
                choose_mode(page, "Commit the line")
                choose_mode(page, "Standard")
            choose_mode(page, "Commit the line")
            page.wait_for_timeout(3000)
            badge = page.get_by_test_id("session-mode").inner_text()
            control = page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value")
            sessions = q(data_dir / "user.db", "SELECT COUNT(*) FROM sessions")[0][0]
            print(f"\nQA-OBS rapid switch: badge={badge!r} control={control!r} sessions={sessions}")
            shot(page, "rapid-switch")
            assert control == "commit_line"
            assert badge == "Commit the line"
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
