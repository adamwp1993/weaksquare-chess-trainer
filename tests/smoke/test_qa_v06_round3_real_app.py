"""QA v0.6 round 3 (qa/QA-v0.6.md): v0.6-B9 in the real app. A puzzles.db with only the fixture's forced
positions (Stockfish answers them in 0.01-0.45 s, and they never have a safe move) plus a few ordinary ones:
every Danger puzzle must still take at least the think time to appear. Then v0.6-B10: raise the think time
mid-session and see whether the forced positions are padded to the new time."""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import chess
import pytest

from tests.smoke.conftest import attach, free_port, launch_app
from weaksquare import config

pytestmark = pytest.mark.smoke
SF = config.default_data_dir(dev=True) / "engines" / "sf_19"
FORCED = ("001KR", "008o6", "00DPQ", "5u38V", "8hajx")  # measured with real Stockfish at 1 s, MultiPV 5
ORDINARY = 5


def _ids_by_board(db: Path) -> dict[str, str]:
    conn = sqlite3.connect(db)
    try:
        return {chess.Board(f).board_fen(): i for i, f in conn.execute("SELECT id, fen FROM puzzles")}
    finally:
        conn.close()


def _loads(page, n: int, think_note: str) -> list[tuple[str, float]]:  # type: ignore[no-untyped-def]
    by_board = _ids_by_board(DB)
    out = []
    t0 = time.monotonic()
    for i in range(n):
        if i:
            t0 = time.monotonic()
            page.get_by_test_id("next-button").click()
        page.get_by_test_id("danger-call").wait_for(timeout=60_000)
        waited = time.monotonic() - t0
        fen = page.get_by_test_id("board").get_attribute("data-fen") or ""
        out.append((by_board.get(fen.split()[0], "?"), round(waited, 2)))
        page.get_by_test_id("danger-safe").click()
        page.get_by_test_id("danger-verdict").wait_for(timeout=10_000)
    print(f"\nQA-OBS {think_note}: {out}")
    return out


DB = Path()


def test_b9_forced_positions_wait_the_think_time_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    global DB
    if not (SF / "stockfish.exe").is_file():
        pytest.skip("no managed Stockfish in the dev data folder")
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    DB = data_dir / "puzzles.db"
    shutil.copyfile(fixture_puzzles_db, DB)
    conn = sqlite3.connect(DB)
    try:
        keep = list(FORCED) + [r[0] for r in conn.execute("SELECT id FROM puzzles WHERE id NOT IN (?,?,?,?,?)"
                                                           " ORDER BY id LIMIT ?", (*FORCED, ORDINARY))]  # fmt: skip
        conn.execute(f"DELETE FROM puzzles WHERE id NOT IN ({','.join('?' * len(keep))})", keep)
        conn.commit()
    finally:
        conn.close()
    shutil.copytree(SF, data_dir / "engines" / "sf_19")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="match").wait_for(timeout=30_000)
            page.get_by_test_id("mode-control").get_by_text("Danger spotting", exact=True).click()
            matched = int(page.get_by_test_id("match-count").inner_text().split()[0])
            print("QA-OBS match:", matched)
            page.get_by_label("Puzzles").fill(str(matched))
            page.get_by_role("button", name="Start").click()
            first = _loads(page, matched, "think 1 s (puzzle id, seconds)")
            forced = [t for pid, t in first[1:] if pid in FORCED]
            print("QA-OBS forced loads at 1 s:", forced)
            assert forced, "no forced position served after the first load"
            assert min(forced) >= 0.95, forced
            # v0.6-B10: a new session at 1 s, then raise the think time to 3 s after its first puzzle
            page.get_by_test_id("next-button").click()
            page.get_by_role("button", name="New session").click()
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("danger-call").wait_for(timeout=60_000)
            page.evaluate("window.pywebview.api.set_engine_settings(3, null, null)")
            page.wait_for_timeout(300)
            page.get_by_test_id("danger-safe").click()
            page.get_by_test_id("danger-verdict").wait_for(timeout=10_000)
            rest = []
            by_board = _ids_by_board(DB)
            for _ in range(matched - 1):
                t0 = time.monotonic()
                page.get_by_test_id("next-button").click()
                page.get_by_test_id("danger-call").wait_for(timeout=60_000)
                fen = page.get_by_test_id("board").get_attribute("data-fen") or ""
                rest.append((by_board.get(fen.split()[0], "?"), round(time.monotonic() - t0, 2)))
                page.get_by_test_id("danger-safe").click()
                page.get_by_test_id("danger-verdict").wait_for(timeout=10_000)
            print("QA-OBS after raising think time to 3 s mid-session:", rest)
            page.evaluate("window.pywebview.api.set_engine_settings(1, null, null)")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
