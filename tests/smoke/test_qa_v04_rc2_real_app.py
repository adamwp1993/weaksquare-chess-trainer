"""QA v0.4 rc2: Try again (FR-5.12) in the real app over CDP, with the real Stockfish copied into a temp
data folder. FR-7.3 must hold during the practice run (the bridge refuses), and the practice run must
leave user.db's attempts (which are also the Lichess sync queue) untouched, including after a wrong
move, a hint, Show answer and Next mid-practice. Written by the independent QA pass (qa/QA-v0.4.md).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v04_real_app import bridge, latest_session, managed_install, shot, solution_for

pytestmark = pytest.mark.smoke


def attempts(user_db: Path) -> list[tuple]:
    conn = sqlite3.connect(user_db)
    try:
        return conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    finally:
        conn.close()


def test_try_again_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path, request) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    (data_dir / "engines").mkdir(parents=True)
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(managed_install(request), data_dir / "engines" / "sf_19")
    user_db = data_dir / "user.db"
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_label("Puzzles", exact=True).fill("3")
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=30_000)
            board = page.get_by_test_id("board")
            fen = board.get_attribute("data-fen")
            _pid, moves = solution_for(data_dir / "puzzles.db", fen)
            pos = chess.Board(fen)
            color = "white" if pos.turn == chess.WHITE else "black"
            sid = latest_session(user_db)
            wrong = next(m.uci() for m in pos.legal_moves if m.uci() != moves[1] and not pos.gives_check(m))

            # the real attempt: a wrong move, then Show answer
            play(page, wrong, color)
            page.get_by_test_id("outcome").filter(has_text="Failed").wait_for(timeout=10_000)
            page.get_by_test_id("answer-button").click()
            page.get_by_test_id("refutation-label").filter(has_text="fails").wait_for(timeout=20_000)
            page.get_by_test_id("engine-line").first.wait_for(timeout=20_000)
            before = attempts(user_db)
            assert len(before) == 1 and before[0] is not None
            stats_before = bridge(page, f"get_session_stats({sid})")["data"]
            report_before = bridge(page, "get_stats()")["data"]

            # practice run: the engine is hidden and refused, nothing is recorded
            page.get_by_test_id("try-again").click()
            page.get_by_test_id("practice-badge").wait_for()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn again").wait_for(timeout=10_000)
            assert page.get_by_test_id("engine-panel").count() == 0
            for call in (
                f"analyze_position({sid}, {fen!r}, 'panel')",
                f"analyze_position({sid}, {fen!r}, 'start')",
                f"get_refutation({sid})",
            ):
                r = bridge(page, call)
                assert not r["ok"] and r["error"]["code"] == "conflict", (call, r)
            play(page, wrong, color)
            page.get_by_test_id("trainer-message").filter(has_text="practice, not scored").wait_for(timeout=10_000)
            r = bridge(page, f"analyze_position({sid}, {fen!r}, 'panel')")
            assert not r["ok"] and r["error"]["code"] == "conflict", r  # lost-but-playing: still in progress
            page.get_by_test_id("hint-button").click()
            page.wait_for_timeout(500)
            assert page.get_by_test_id("engine-panel").count() == 0
            assert "for you" not in page.locator("body").inner_text()
            shot(page, "rc2-practice-after-wrong-and-hint")
            page.get_by_test_id("answer-button").click()  # ends the practice run: the engine may show
            page.get_by_test_id("engine-line").first.wait_for(timeout=20_000)
            assert bridge(page, f"analyze_position({sid}, {fen!r}, 'start')")["ok"]
            assert attempts(user_db) == before
            assert bridge(page, f"get_session_stats({sid})")["data"] == stats_before

            # practice run 2, then Next in the middle of it
            page.keyboard.press("r")
            page.get_by_test_id("practice-badge").wait_for()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn again").wait_for(timeout=10_000)
            play(page, moves[1], color)
            page.wait_for_timeout(1200)
            page.get_by_test_id("next-button").click()
            page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 2").wait_for(timeout=10_000)
            page.wait_for_timeout(800)
            assert page.get_by_test_id("practice-badge").count() == 0
            assert attempts(user_db) == before
            assert bridge(page, f"get_session_stats({sid})")["data"] == stats_before
            assert bridge(page, "get_stats()")["data"] == report_before
            assert page.get_by_test_id("sync-chip").filter(has_text="1 solve waiting").count() == 1
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    log = (data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    assert " ERROR " not in log, [x for x in log.splitlines() if " ERROR " in x]
