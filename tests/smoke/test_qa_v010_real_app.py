"""QA v0.10 in the real app (WebView2 over CDP), temp data folder, no account, no key, no request sent.

1. Show best moves (FR-11.35): off by default on the Review screen, turned on there, and still on after the app
   is closed and started again (saved in user.db). The analysis is planted, since this folder has no Stockfish.
2. With the dev folder's real Stockfish 19 copied in (read-only source): a Coach run on one imported game goes
   through the real pipeline (analysis at 0.3 s, tags, a puzzle from the missed mate, the report, the Suggested
   mix), a level change runs no engine, and Analyze from here answers on the interactive engine and changes
   nothing. Skips when the dev folder has no Stockfish.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

import chess
import pytest

from tests.integration.test_review import ANALYSES, MOVES
from tests.smoke.conftest import attach, free_port, launch_app
from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.game_review import grade_game

pytestmark = pytest.mark.smoke

SCHOLAR = '[White "opponent_b"]\n[Black "player_x"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
# You (White) miss 8.Rd8# after 7...Qh6?? and play 8.Kg2 instead (ply 14, past the Coach's opening skip).
MISSED_MATE = (
    '[White "player_a"]\n[Black "opponent_b"]\n[Result "*"]\n[SetUp "1"]\n'
    '[FEN "1n4k1/ppp2ppp/5q2/4p3/8/8/PPP2PPP/RN1R2K1 w - - 0 1"]\n\n'
    "1. a3 a6 2. Nd2 b6 3. a4 Nd7 4. Nb1 Nb8 5. h3 c6 6. g3 c5 7. c3 Qh6 8. Kg2 Qf6 *\n"
)
BEFORE_KG2 = "1n4k1/5ppp/pp5q/2p1p3/P7/2P3PP/1P3P2/RN1R2K1 w - - 1 8"
ANY_GAME = {"rated_only": False, "time_classes": []}


def _call(page, method: str, *args: object) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return page.evaluate(f"(a) => window.pywebview.api.{method}(...a)", list(args))  # type: ignore[no-any-return]


def _ok(r: dict[str, Any]) -> Any:
    assert r["ok"], r
    return r["data"]


def _wait_job(page, job: str, timeout: float = 180) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = _ok(_call(page, "get_job", job))
        if st["state"] in ("done", "failed", "cancelled"):
            return st  # type: ignore[no-any-return]
        page.wait_for_timeout(300)
    raise TimeoutError(job)


def _open_review(page, gid: int) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id(f"review-{gid}").click()
    page.get_by_test_id("review-view").wait_for()


def test_qa_v010_show_best_moves_survives_a_relaunch(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            gid = _ok(_call(page, "import_game_pgn", SCHOLAR))["game_id"]
            _ok(_call(page, "set_game_color", gid, "black"))
            db = Database(data_dir / "user.db", data_dir / "puzzles.db")
            try:
                GameAnalysisRepo(db).replace(
                    gid, grade_game(chess.STARTING_FEN, MOVES, ANALYSES), "analyzed", 0.3, "Stockfish 19"
                )
            finally:
                db.close_all()
            assert _ok(_call(page, "get_settings"))["show_best"] is False
            _open_review(page, gid)
            toggle = page.get_by_test_id("review-show-best")
            assert not toggle.is_checked()
            page.get_by_test_id("move-5").click()  # 3...Nf6??
            page.get_by_test_id("review-current").wait_for()
            assert page.get_by_test_id("review-better").count() == 0
            assert page.get_by_test_id("review-lines").count() == 0
            assert "better was" not in page.get_by_test_id("key-moments").inner_text()
            page.get_by_test_id("review-refutation").wait_for()  # why it fails stays
            page.screenshot(path=str(Path("tests/e2e/artifacts/qa-v010-real-review-best-off.png")))
            toggle.click()
            page.get_by_test_id("review-better").wait_for()
            for _ in range(50):
                if _ok(_call(page, "get_settings"))["show_best"]:
                    break
                page.wait_for_timeout(100)
    finally:
        assert app.close() == 0
    with sqlite3.connect(data_dir / "user.db") as conn:
        assert conn.execute("SELECT value FROM settings WHERE key = 'review.show_best'").fetchone() == ("true",)
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            _open_review(page, gid)
            assert page.get_by_test_id("review-show-best").is_checked()
            page.get_by_test_id("key-moments").get_by_text("better was").first.wait_for()
            # Analyze from here without Stockfish: the board opens, the engine panel says what's missing.
            page.get_by_test_id("review-analyze-here").click()
            page.get_by_test_id("review-free").wait_for()
            page.get_by_test_id("analysis-close").click()
            page.get_by_test_id("review-free").wait_for(state="detached")
            # The Coach page opens and a puzzle-history run (local only: no account) saves a report.
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-page").wait_for()
            page.screenshot(path=str(Path("tests/e2e/artifacts/qa-v010-real-coach-empty.png")))
            job = _ok(_call(page, "start_coach_run", {"source": "puzzles"}))
            assert _wait_job(page, job, 30)["state"] == "done"
            rid = _ok(_call(page, "get_coach_run_result", job))
            rep = _ok(_call(page, "get_coach_report", rid))
            assert rep["is_me"] and rep["games"] == 0
            assert _ok(_call(page, "get_suggestion")) is None  # a puzzle-only report leaves the mix alone
    finally:
        assert app.close() == 0


def test_qa_v010_a_coach_run_with_the_real_stockfish(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    src = config.default_data_dir(dev=True) / "engines" / "sf_19"
    if not (src / "stockfish.exe").is_file() or not (src / "install.json").is_file():
        pytest.skip(f"no managed Stockfish in {src}")
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(src, data_dir / "engines" / "sf_19")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            gid = _ok(_call(page, "import_game_pgn", MISSED_MATE))["game_id"]
            _ok(_call(page, "set_game_color", gid, "white"))
            for _ in range(100):  # the engine starts in the background
                if _ok(_call(page, "get_engine_status"))["state"] == "ready":
                    break
                page.wait_for_timeout(200)
            # Send to Coach from My games, then Run on the Coach page (the UI path, so the Mixer reloads).
            page.get_by_test_id("nav-games").click()
            page.get_by_test_id(f"game-row-{gid}").get_by_role("checkbox").check()
            page.get_by_test_id("send-to-coach").click()
            page.get_by_test_id("coach-sent").filter(has_text="1 game sent").wait_for()
            page.get_by_test_id("coach-run").click()
            page.get_by_test_id("coach-report").wait_for(timeout=180_000)
            rid = _ok(_call(page, "list_coach_reports"))[0]["id"]
            rep = _ok(_call(page, "get_coach_report", rid))
            assert rep["is_me"] and rep["games"] == 1
            with sqlite3.connect(data_dir / "user.db") as conn:
                g = conn.execute("SELECT analysis_status, analysis_think_s FROM games WHERE id = ?", (gid,)).fetchone()
                assert g == ("analyzed", 0.3)  # Game Review's think time (FR-10.9)
                pz = conn.execute(
                    "SELECT ply, fen, solution_uci, player_color, solve_as, kind, origin, status, themes"
                    " FROM custom_puzzles WHERE game_id = ? AND ply = 14",
                    (gid,),
                ).fetchone()
                n_candidates = conn.execute("SELECT COUNT(*) FROM coach_candidates").fetchone()[0]
                n_rows = conn.execute("SELECT COUNT(*) FROM game_analysis WHERE game_id = ?", (gid,)).fetchone()[0]
            assert pz is not None, "no puzzle from the missed mate"
            assert pz[:8] == (14, BEFORE_KG2, "d1d8", "white", "you", "missed", "coach", "active"), pz
            assert "mateIn1" in (pz[8] or "").split()
            sug = _ok(_call(page, "get_suggestion"))
            assert sug is not None and sug["active"] and not sug["pending"]

            # A level change: no new analysis, no new checks of stored candidates.
            _ok(_call(page, "set_games_settings", None, None, None, None, None, None, None, "blunders"))
            _ok(_call(page, "set_games_settings", None, None, None, None, None, None, None, "mistakes"))
            page.wait_for_timeout(1000)
            with sqlite3.connect(data_dir / "user.db") as conn:
                assert conn.execute("SELECT COUNT(*) FROM coach_candidates").fetchone()[0] == n_candidates
                assert conn.execute("SELECT analysis_think_s FROM games WHERE id = ?", (gid,)).fetchone() == (0.3,)
                status = conn.execute(
                    "SELECT status FROM custom_puzzles WHERE game_id = ? AND ply = 14", (gid,)
                ).fetchone()
            assert status == ("active",)

            # Analyze from here on the real interactive engine changes nothing.
            a = _ok(_call(page, "analyze_game_position", gid, "4k3/8/8/8/8/8/1n6/R3K3 w - - 0 1", "board"))
            assert a["lines"]
            bad = _call(page, "analyze_game_position", gid, "not a fen", "board")
            assert not bad["ok"]
            with sqlite3.connect(data_dir / "user.db") as conn:
                assert (
                    conn.execute("SELECT COUNT(*) FROM game_analysis WHERE game_id = ?", (gid,)).fetchone()[0] == n_rows
                )

            # The report on the Coach page, and the Suggested label on the main page.
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-report").wait_for(timeout=10_000)
            page.screenshot(path=str(Path("tests/e2e/artifacts/qa-v010-real-coach-report.png")), full_page=True)
            page.get_by_test_id("nav-puzzles").click()
            page.get_by_test_id("suggestion-label").wait_for(timeout=10_000)
            page.screenshot(path=str(Path("tests/e2e/artifacts/qa-v010-real-mixer-suggested.png")))
    finally:
        assert app.close() == 0
