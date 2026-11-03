"""QA v0.4: the engine features in the real app (WebView2 attached over CDP), on the fixture DB and a
temp data folder. Written by the independent QA pass (qa/QA-v0.4.md). Screenshots go to
tests/e2e/artifacts/qa-v04-real/.

- `test_engine_flow_in_the_real_app` needs a Stockfish to copy into the temp folder: the dev folder's
  managed install (or `--engine-path`). It's copied, never modified.
- `test_install_from_the_banner` downloads the pinned Stockfish from github.com (about 80 MB). It runs
  only with `QA_V04_DOWNLOAD=1`.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import chess
import pytest

from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app
from weaksquare import config

pytestmark = pytest.mark.smoke
ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts" / "qa-v04-real"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"))


def managed_install(request: pytest.FixtureRequest) -> Path:
    given = request.config.getoption("--engine-path")
    exe = Path(given) if given else config.default_data_dir(dev=True) / "engines" / "sf_19" / "stockfish.exe"
    if not (exe.is_file() and (exe.parent / "install.json").is_file()):
        pytest.skip(f"no managed Stockfish install at {exe.parent}")
    return exe.parent


def engine_processes_under(folder: Path) -> list[int]:
    out = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='stockfish.exe'\" | ForEach-Object "
            '{ "$($_.ProcessId)|$($_.ExecutablePath)" }',
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    pids = []
    for line in out.splitlines():
        pid, _, path = line.partition("|")
        if path and Path(path).resolve().is_relative_to(folder.resolve()):
            pids.append(int(pid))
    return pids


def solution_for(puzzles_db: Path, board_fen: str) -> tuple[str, list[str]]:
    conn = sqlite3.connect(puzzles_db)
    try:
        rows = conn.execute("SELECT id, fen, moves FROM puzzles").fetchall()
    finally:
        conn.close()
    for pid, fen, moves in rows:
        b = chess.Board(fen)
        b.push_uci(moves.split()[0])
        if b.board_fen() == board_fen.split()[0]:
            return pid, moves.split()
    raise AssertionError("puzzle not found")


def bridge(page, call: str):  # type: ignore[no-untyped-def]
    return page.evaluate(f"async () => await window.pywebview.api.{call}")


def latest_session(user_db: Path) -> int:
    conn = sqlite3.connect(user_db)
    try:
        return int(conn.execute("SELECT max(id) FROM sessions").fetchone()[0])
    finally:
        conn.close()


def test_engine_flow_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path, request) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    (data_dir / "engines").mkdir(parents=True)
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(managed_install(request), data_dir / "engines" / "sf_19")
    app = launch_app(data_dir, free_port())
    exit_s = None
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_label("Puzzles").fill("3")
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=30_000)
            board = page.get_by_test_id("board")
            fen = board.get_attribute("data-fen")
            _pid, moves = solution_for(data_dir / "puzzles.db", fen)
            pos = chess.Board(fen)
            color = "white" if pos.turn == chess.WHITE else "black"
            sid = latest_session(data_dir / "user.db")

            # FR-7.3 during the puzzle: nothing on screen, and the bridge refuses
            assert page.get_by_test_id("engine-panel").count() == 0
            r = bridge(page, f"analyze_position({sid}, {fen!r}, 'panel')")
            assert not r["ok"] and r["error"]["code"] == "conflict", r
            wrong = next(m.uci() for m in pos.legal_moves if m.uci() != moves[1] and not pos.gives_check(m))
            play(page, wrong, color)
            page.get_by_test_id("outcome").filter(has_text="Failed").wait_for(timeout=10_000)
            page.wait_for_timeout(800)
            assert page.get_by_test_id("engine-panel").count() == 0
            assert "for you" not in page.locator("body").inner_text()
            for call in (f"get_refutation({sid})", f"analyze_position({sid}, {fen!r}, 'board')"):
                r = bridge(page, call)
                assert not r["ok"] and r["error"]["code"] == "conflict", (call, r)
            shot(page, "after-wrong-move-no-engine")

            # Show answer: the solution, "why it fails" beside it, then the panel
            page.get_by_test_id("answer-button").click()
            seg = page.get_by_test_id("refutation-label")  # beside the answer since the v0.4 manual test
            seg.filter(has_text="fails").wait_for(timeout=20_000)
            assert re.search(r"for you|mate|level", seg.inner_text()), seg.inner_text()
            page.get_by_test_id("engine-line").first.wait_for(timeout=20_000)
            assert page.get_by_test_id("engine-line").count() >= 1
            page.get_by_test_id("engine-start-eval").filter(has_text=re.compile("for you|mate|level")).wait_for()
            shot(page, "refutation-and-panel")
            forward = page.get_by_role("button", name="Forward")
            for _ in range(3):  # a short answer has fewer steps (the real app serves a random puzzle)
                if forward.is_disabled():
                    break
                forward.click()
            # The last step of a mate puzzle is the mate itself: the panel says so and has no lines (and the
            # analysis board below needs a legal move). Step back off a finished game.
            if chess.Board(board.get_attribute("data-fen")).is_game_over():
                page.get_by_test_id("engine-panel").filter(has_text="Checkmate").wait_for(timeout=20_000)
                page.get_by_role("button", name="Back", exact=True).click()
            page.get_by_test_id("engine-line").first.wait_for(timeout=20_000)

            # analysis board: a move, the eval, a legal arrow
            page.get_by_test_id("analyze-button").click()
            page.get_by_test_id("analysis-controls").wait_for()
            afen = board.get_attribute("data-fen")
            abo = chess.Board(afen)

            # a move that doesn't end the game, so the engine has a line (and an arrow) to show
            def ends(m: chess.Move) -> bool:
                b = abo.copy()
                b.push(m)
                return b.is_game_over()

            play(page, next(m for m in abo.legal_moves if not ends(m)).uci(), color)
            page.wait_for_function(
                "() => document.querySelector('[data-testid=analysis-moves]').innerText !== 'Make a move on the board.'"
                " && !document.querySelector('[data-testid=engine-thinking]')"
                " && document.querySelector('[data-testid=board]').getAttribute('data-arrows') !== ''",
                timeout=20_000,
            )
            arrow = board.get_attribute("data-arrows").split()[0]
            # an arrow is from-to only (a promotion's piece isn't drawn): some legal move must match it
            legal = chess.Board(board.get_attribute("data-fen")).legal_moves
            assert any(m.uci()[:4] == arrow[:4] for m in legal), arrow
            shot(page, "analysis-board")
            page.get_by_test_id("analysis-close").click()

            # Next puzzle: in progress again, nothing shown, the bridge refuses
            page.get_by_test_id("next-button").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=10_000)
            page.wait_for_timeout(500)
            assert page.get_by_test_id("engine-panel").count() == 0
            r = bridge(page, f"analyze_position({sid}, {fen!r}, 'panel')")
            assert not r["ok"] and r["error"]["code"] == "conflict", r

            # About names the engine and its path (NFR-7)
            page.get_by_role("button", name="Menu").click()
            page.get_by_role("menuitem", name="About").click()
            about = page.get_by_test_id("about-engine")
            about.filter(has_text="Stockfish 19").wait_for(timeout=10_000)
            assert "stockfish.exe" in about.inner_text()
            shot(page, "about")
            page.keyboard.press("Escape")

            # close while a long search runs (NFR-6): finish this puzzle, think 5 s, ask, close at once
            page.get_by_test_id("hint-button").click()
            page.get_by_test_id("answer-button").click()
            page.get_by_test_id("answer-player").wait_for()
            page.wait_for_timeout(2500)  # let the panel's own searches finish
            r = bridge(page, "set_engine_settings(5, null, null)")
            assert r["ok"], r
            assert engine_processes_under(data_dir), "the engine should be running"
            page.evaluate(
                f"() => {{ window.pywebview.api.analyze_position({sid}, '4k3/8/8/8/8/8/3P4/4K3 w - - 0 1', 'board'); }}"
            )
            page.wait_for_timeout(500)  # the 5 s search is running
        # nothing more on the page; close the window and time the exit
        started = time.monotonic()
        assert app.close() == 0
        exit_s = time.monotonic() - started
    finally:
        if app.process.poll() is None:
            app.process.kill()
    print(f"\napp exit took {exit_s:.1f} s")
    time.sleep(1)
    assert engine_processes_under(data_dir) == []  # NFR-6
    log = (data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    first = log.splitlines()[0]
    assert "Stockfish: Stockfish 19 (sf_19, managed)" in first, first
    assert "engine started: Stockfish 19" in log
    assert "Engine in use: Stockfish 19 (managed, sf_19) at " in log  # round 2: v0.4-B6
    assert "chess.engine" not in log and "<< " not in log and ">> " not in log  # no UCI DEBUG flood
    lines = log.splitlines()
    context = [lines[max(0, i - 3) : i + 25] for i, x in enumerate(lines) if " ERROR " in x]
    assert " ERROR " not in log, context


@pytest.mark.skipif(os.environ.get("QA_V04_DOWNLOAD") != "1", reason="downloads ~80 MB: set QA_V04_DOWNLOAD=1")
def test_install_from_the_banner(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    """FR-7.5 end to end: no engine -> the banner -> Install -> progress -> the panel, in the real app."""
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("hint-button").click(timeout=30_000)
            page.get_by_test_id("answer-button").click()
            banner = page.get_by_test_id("engine-banner")
            banner.filter(has_text="Stockfish isn't installed").wait_for(timeout=10_000)
            shot(page, "install-banner")
            page.get_by_test_id("engine-install").click()
            page.get_by_test_id("engine-install-progress").wait_for()
            shot(page, "install-progress")
            page.get_by_test_id("engine-panel").wait_for(timeout=180_000)
            page.get_by_test_id("engine-line").first.wait_for(timeout=30_000)
            shot(page, "installed-panel")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert (data_dir / "engines" / "sf_19" / "stockfish.exe").is_file()
    assert list((data_dir / "downloads").glob("*")) == []  # the zip is gone
    assert not [p for p in (data_dir / "engines").iterdir() if p.name != "sf_19"]  # no temp folders
    log = (data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    assert "installed Stockfish 19" in log
