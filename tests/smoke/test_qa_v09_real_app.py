"""QA v0.9 in the real app (WebView2 over CDP), temp data folder, no key stored and no request sent:
Game Review AI's bridge methods and gates through the real pywebview bridge, and the AI-reviewed status from
user.db shown in the real My games list (badge and filter). The analysis is planted in user.db by the test,
because the temp folder has no Stockfish."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

import chess
import pytest

from tests.integration.test_review import ANALYSES, MOVES
from tests.smoke.conftest import attach, free_port, launch_app
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.game_review import grade_game

pytestmark = pytest.mark.smoke

SCHOLAR = '[White "opponent_b"]\n[Black "player_x"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'


def test_qa_v09_game_ai_gates_and_ai_reviewed_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)

            def call(method: str, *args: object) -> dict[str, Any]:
                return page.evaluate(f"(a) => window.pywebview.api.{method}(...a)", list(args))  # type: ignore[no-any-return]

            imp = call("import_game_pgn", SCHOLAR)
            assert imp["ok"], imp
            gid = imp["data"]["game_id"]
            assert call("set_game_color", gid, "black")["ok"]
            # Not analyzed yet: a readable refusal, not a crash.
            r = call("get_game_narrative_quote", gid, None)
            assert not r["ok"] and "Analyze this game first" in r["error"]["message"], r

            db = Database(data_dir / "user.db", data_dir / "puzzles.db")
            try:
                rows = grade_game(chess.STARTING_FEN, MOVES, ANALYSES)
                GameAnalysisRepo(db).replace(gid, rows, "analyzed", 0.3, "Stockfish 19")
            finally:
                db.close_all()

            q = call("get_game_narrative_quote", gid, None)
            assert q["ok"] and q["data"]["state"] == "not_configured", q
            got = call("get_game_narrative", gid, None)
            assert got["ok"] and got["data"] is None, got
            s = call("start_game_narrative", gid, None)
            assert not s["ok"] and s["error"]["code"] == "not_configured", s
            mq = call("get_game_move_quote", gid, 5)
            assert mq["ok"] and mq["data"]["state"] == "not_configured", mq
            opp = call("get_game_move_quote", gid, 4)  # White's move: you played Black
            assert not opp["ok"] and "your own moves" in opp["error"]["message"], opp
            for bad in (0, 11, True, "5"):
                b = call("get_game_narrative_quote", gid, bad)
                assert not b["ok"] and b["error"]["code"] == "invalid_argument", (bad, b)
            for args in (("explain", "same", "", "low"), ("game_review", "google", "x", "low"),
                         ("game_review", "same", "", "extreme")):  # fmt: skip
                b = call("set_llm_feature", *args)
                assert not b["ok"] and b["error"]["code"] == "invalid_argument", (args, b)

            with sqlite3.connect(data_dir / "user.db") as conn:
                conn.execute("UPDATE games SET analysis_status = 'ai_reviewed' WHERE id = ?", (gid,))
            page.get_by_test_id("nav-games").click()
            page.get_by_test_id(f"status-{gid}").filter(has_text="AI-reviewed").wait_for(timeout=10_000)
            listed = call("list_games", {"statuses": ["ai_reviewed"]})
            assert listed["ok"] and listed["data"]["total"] == 1, listed
            assert listed["data"]["games"][0]["analysis_status"] == "ai_reviewed"
            assert call("list_games", {"statuses": ["analyzed"]})["data"]["total"] == 0
            # No model set up: no Review + Explain my game button, and no AI panel in Review.
            assert page.get_by_test_id(f"review-explain-{gid}").count() == 0
            page.get_by_test_id(f"review-{gid}").click()
            page.get_by_test_id("review-summary").wait_for(timeout=10_000)
            assert page.get_by_test_id("narrative-panel").count() == 0
            art = Path(__file__).resolve().parents[1] / "e2e" / "artifacts"
            art.mkdir(exist_ok=True)
            page.screenshot(path=str(art / "qa-v09-real-review-no-ai.png"))
    finally:
        app.close()
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone() == (0,)
    finally:
        conn.close()


# v0.9-B1 regression test (fixed: a change made while a save is in flight builds on it).
def test_qa_v09_reasoning_right_after_a_model_pick_keeps_the_model(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("gear").click()
            section = page.get_by_test_id("settings-ai")
            section.scroll_into_view_if_needed()
            section.get_by_test_id("ai-provider").click()
            page.get_by_role("option", name="Anthropic").click()
            picker = section.get_by_test_id("ai-feature-model-game_review")
            picker.wait_for()
            # A slow bridge round trip (a busy PC): every set_llm_feature reply takes 1.5 s.
            page.evaluate(
                """() => { const api = window.pywebview.api; const orig = api.set_llm_feature;
                   api.set_llm_feature = (...a) => new Promise(r => setTimeout(r, 1500)).then(() => orig(...a)); }"""
            )
            picker.click()
            page.get_by_role("option", name="claude-sonnet-5-5  ·  about").click()
            section.get_by_test_id("ai-feature-reasoning-game_review").get_by_text("Medium").click()
            page.wait_for_timeout(4000)
            settings = page.evaluate("window.pywebview.api.get_llm_settings()")
            gr = settings["data"]["features"][1]
            assert (gr["choice"], gr["model"], gr["reasoning"]) == ("anthropic", "claude-sonnet-5-5", "medium"), gr
    finally:
        app.close()
