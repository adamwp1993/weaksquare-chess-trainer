"""QA v0.6: Danger spotting, the reason chips and Name the idea first in the real app (WebView2 over CDP), on the
fixture DB, a temp data folder and a copy of the dev folder's managed Stockfish (read-only source). Written by the
independent QA pass (qa/QA-v0.6.md). Screenshots go to tests/e2e/artifacts/qa-v06-real/.

It also measures v0.6-B1: how long each Danger puzzle takes to appear, and whether that alone tells you the
answer."""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app
from weaksquare import config

pytestmark = pytest.mark.smoke
ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts" / "qa-v06-real"
SF = config.default_data_dir(dev=True) / "engines" / "sf_19"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"))


def q(db: Path, sql: str) -> list[tuple]:  # type: ignore[type-arg]
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def moves_for_raw(puzzles_db: Path, fen: str) -> list[str]:
    for raw, moves in q(puzzles_db, "SELECT fen, moves FROM puzzles"):
        if chess.Board(raw).board_fen() == fen.split()[0]:
            return str(moves).split()
    raise AssertionError("puzzle not found")


def test_v06_danger_reasons_and_name_the_idea_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    if not (SF / "stockfish.exe").is_file():
        pytest.skip("no managed Stockfish in the dev data folder")
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(SF, data_dir / "engines" / "sf_19")
    user_db = data_dir / "user.db"
    pdb = data_dir / "puzzles.db"

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("mode-control").get_by_text("Danger spotting", exact=True).click()
            assert page.get_by_test_id("rated-switch").is_disabled()
            page.get_by_label("Puzzles").fill("40")
            shot(page, "mixer-danger")
            t0 = time.monotonic()
            page.get_by_role("button", name="Start").click()
            preparing = 0
            loads: list[tuple[float, bool, bool]] = []  # (seconds to appear, guessed safe, really safe)
            for i in range(14):
                page.get_by_test_id("danger-call").wait_for(timeout=60_000)
                waited = time.monotonic() - t0
                fen = page.get_by_test_id("board").get_attribute("data-fen") or ""
                if i == 0:
                    shot(page, "danger-call")
                # v0.6-B1: guess from the load time alone (a safe slot waits for a ~1 s engine search)
                guess_safe = waited > 0.6
                page.get_by_test_id("danger-safe" if guess_safe else "danger-unsafe").click()
                refuting = False
                try:
                    page.get_by_test_id("trainer-message").filter(has_text="punish it").wait_for(timeout=1500)
                    refuting = True
                except Exception:
                    pass
                if refuting:
                    moves = moves_for_raw(pdb, fen)
                    board = chess.Board(fen)
                    board.push_uci(moves[0])
                    if i < 4:
                        shot(page, f"danger-refute-{i}")
                    play(page, moves[1], "white" if board.turn == chess.WHITE else "black")
                page.get_by_test_id("danger-verdict").wait_for(timeout=10_000)
                verdict = page.get_by_test_id("danger-verdict").inner_text()
                really_safe = "was safe" in verdict
                loads.append((round(waited, 2), guess_safe, really_safe))
                if i == 1:
                    shot(page, "danger-verdict")
                t0 = time.monotonic()
                page.get_by_test_id("next-button").click()
                msg = page.get_by_test_id("trainer-message")
                preparing += int(msg.count() > 0 and "Preparing the position" in (msg.inner_text() or ""))
            print("\nQA-OBS danger loads (s, guessed safe, really safe):", loads)
            right = sum(g == r for _, g, r in loads)
            print(f"QA-OBS guessing from the load time alone: {right}/{len(loads)} right")
            print(f"QA-OBS 'Preparing the position' seen after {preparing} of {len(loads)} Next clicks")
            # Round 2 (v0.6-B1 fix): the load times of safe and blunder candidates overlap
            safe_t = [t for t, _, r in loads[1:] if r]
            blunder_t = [t for t, _, r in loads[1:] if not r]
            if safe_t and blunder_t:
                assert min(safe_t) <= max(blunder_t) and min(blunder_t) <= max(safe_t), (safe_t, blunder_t)
            rows = q(user_db, "SELECT DISTINCT mode, sync_status FROM attempts")
            assert rows == [("danger_spotting", "local")], rows

            # a deliberate miss: call the next one wrong, then tag it with keys 1-6
            page.get_by_test_id("danger-call").wait_for(timeout=60_000)
            for _ in range(10):  # call Safe until one was the blunder: a miss
                page.get_by_test_id("danger-safe").click()
                page.get_by_test_id("outcome").wait_for(timeout=10_000)
                if "Failed" in page.get_by_test_id("outcome").inner_text():
                    break
                page.get_by_test_id("next-button").click()
                page.get_by_test_id("danger-call").wait_for(timeout=60_000)
            page.get_by_test_id("reason-chips").wait_for(timeout=15_000)
            shot(page, "reason-chips")
            failed_before = page.get_by_test_id("stat-failed").inner_text()
            page.keyboard.press("6")
            page.get_by_test_id("stat-misclicks").wait_for(timeout=10_000)
            shot(page, "misclick-session-bar")
            print(
                "QA-OBS failed before/after misclick:", failed_before, page.get_by_test_id("stat-failed").inner_text()
            )
            got = q(user_db, "SELECT source, reason FROM mistake_reasons")
            assert got == [("danger", "misclick")], got

            # Name the idea first
            page.get_by_test_id("mode-control").get_by_text("Name the idea first", exact=True).click()
            page.get_by_test_id("idea-tags").wait_for(timeout=30_000)
            shot(page, "name-idea-tagging")
            page.get_by_test_id("idea-payoff").click()
            page.get_by_role("option", name="Fork", exact=True).click()
            page.keyboard.press("Escape")
            page.get_by_test_id("idea-start").click()
            page.get_by_test_id("idea-tags").wait_for(state="detached")
            fen = page.get_by_test_id("board").get_attribute("data-fen") or ""
            raw_moves = None
            for raw, moves in q(pdb, "SELECT fen, moves FROM puzzles"):
                b = chess.Board(raw)
                b.push_uci(str(moves).split()[0])
                if b.board_fen() == fen.split()[0]:
                    raw_moves = str(moves).split()
                    break
            assert raw_moves
            print("QA-OBS name idea fen/moves:", fen, raw_moves)
            color = "white" if chess.Board(fen).turn == chess.WHITE else "black"
            for uci in raw_moves[1::2]:
                play(page, uci, color)
                page.wait_for_timeout(900)
            try:
                page.get_by_test_id("outcome").filter(has_text="Solved").wait_for(timeout=10_000)
            finally:
                shot(page, "name-idea-after-solve")
            page.get_by_test_id("idea-result").wait_for()
            shot(page, "name-idea-result")
            print("QA-OBS idea result:", ascii(page.get_by_test_id("idea-result").inner_text()))
            r = q(user_db, "SELECT mode, idea_tags, sync_status FROM attempts WHERE mode = 'name_idea'")
            assert r and '"payoff": ["fork"]' in r[0][1]

            # Stats
            page.get_by_role("button", name="Menu").click()
            page.get_by_role("menuitem", name="Stats").click()
            page.get_by_test_id("stats-mode-tab").click()
            page.get_by_test_id("stats-mode-details").wait_for()
            shot(page, "stats-mode-details")
            print("QA-OBS mode details:", ascii(page.get_by_test_id("stats-mode-details").inner_text()))
            page.get_by_test_id("stats-reasons-tab").click()
            page.get_by_test_id("reasons-misclicks").wait_for()
            shot(page, "stats-reasons")
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
