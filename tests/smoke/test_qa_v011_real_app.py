"""QA v0.11 in the real app (WebView2 over CDP), temp data folder, no account, no AI key, no request sent.

With the dev folder's real Stockfish 19 copied in (read-only source): one imported game goes through Send to
Coach -> Run, and the report shows the whole-game measures with the 5-game guard. In the AI box, Advanced and
Include my notes start off; ticking Include my notes opens the preview with the note's web address removed.
After closing and relaunching, both are off again and nothing about them is in user.db's settings. With no
AI key the estimate is blocked and nothing is logged. Skips when the dev folder has no Stockfish.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v010_real_app import MISSED_MATE, _call, _ok
from weaksquare import config

pytestmark = pytest.mark.smoke
ART = Path("tests/e2e/artifacts")


def _ready(page: Any) -> None:
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)


def test_qa_v011_whole_game_report_and_per_run_options(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    src = config.default_data_dir(dev=True) / "engines" / "sf_19"
    if not (src / "stockfish.exe").is_file() or not (src / "install.json").is_file():
        pytest.skip(f"no managed Stockfish in {src}")
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(src, data_dir / "engines" / "sf_19")
    ART.mkdir(parents=True, exist_ok=True)
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            gid = _ok(_call(page, "import_game_pgn", MISSED_MATE))["game_id"]
            _ok(_call(page, "set_game_color", gid, "white"))
            for _ in range(100):
                if _ok(_call(page, "get_engine_status"))["state"] == "ready":
                    break
                page.wait_for_timeout(200)
            page.get_by_test_id("nav-games").click()
            page.get_by_test_id(f"game-row-{gid}").get_by_role("checkbox").check()
            page.get_by_test_id("send-to-coach").click()
            page.get_by_test_id("coach-sent").filter(has_text="1 game sent").wait_for()
            page.get_by_test_id("coach-run").click()
            page.get_by_test_id("coach-report").wait_for(timeout=180_000)
            rid = _ok(_call(page, "list_coach_reports"))[0]["id"]
            rep = _ok(_call(page, "get_coach_report", rid))
            m = rep["measures"]
            assert m is not None and m["games"] == 1 and m["min_games"] == 5
            assert not m["conversion"]["enough"] and not m["king"]["enough"] and not m["time"]["enough"]
            assert all(not o["enough"] for o in m["openings"])
            assert rep["whole_game"] == []  # one game: nothing passes the guard
            with sqlite3.connect(data_dir / "user.db") as conn:
                assert conn.execute("SELECT COUNT(*) FROM game_digests WHERE game_id = ?", (gid,)).fetchone()[0] == 1
            measures = page.get_by_test_id("coach-measures")
            measures.wait_for()
            assert measures.get_by_test_id("not-enough").count() >= 3

            # A note on the missed mate (ply 14), with a web address in it.
            _ok(_call(page, "set_game_reason", gid, 14, "didntLook", "missed Rd8#, see https://example.org/x"))
            ai = page.get_by_test_id("coach-ai")
            ai.scroll_into_view_if_needed()
            assert not page.get_by_test_id("coach-ai-advanced").is_checked()
            assert not page.get_by_test_id("coach-ai-notes").is_checked()
            page.get_by_test_id("coach-ai-advanced").check()
            page.get_by_test_id("coach-ai-cap").wait_for()
            page.get_by_test_id("coach-ai-notes").check()
            preview = page.get_by_test_id("coach-note")
            preview.first.wait_for(timeout=10_000)
            text = preview.first.inner_text()
            assert "missed Rd8#, see [link removed]" in text and "example.org" not in text
            page.screenshot(path=str(ART / "qa-v011-real-notes-preview.png"))
            page.get_by_test_id("coach-notes-ok").click()
            page.screenshot(path=str(ART / "qa-v011-real-coach-report.png"), full_page=True)
            # No AI key: blocked before anything is sent.
            q = _ok(_call(page, "get_coach_ai_quote", rid, {"advanced": True, "game_cap": 30, "include_notes": True}))
            assert q["quote"]["state"] not in ("ok", "cached")
            assert page.get_by_test_id("coach-ai-start").is_disabled()
    finally:
        assert app.close() == 0
    with sqlite3.connect(data_dir / "user.db") as conn:
        blob = repr(conn.execute("SELECT key, value FROM settings").fetchall())
        assert "advanced" not in blob and "include_notes" not in blob and "game_cap" not in blob
        assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM coach_ai_runs").fetchone()[0] == 0
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-page").wait_for()
            page.get_by_test_id(f"coach-history-{rid}").click()
            page.get_by_test_id("coach-ai").wait_for()
            assert not page.get_by_test_id("coach-ai-advanced").is_checked()  # off every time (FR-10.56)
            assert not page.get_by_test_id("coach-ai-notes").is_checked()
    finally:
        assert app.close() == 0
