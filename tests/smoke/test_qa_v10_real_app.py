"""QA v1.0 in the real app (WebView2 over CDP), temp data folders only (NFR-2):

- **Restore from a backup in the first-run wizard (FR-15.4, NFR-8)** with a backup of a v0.16 database (schema 14,
  made by "0.16.0"): Welcome → Restore from a backup… (the native Open dialog, driven over Win32) → Restore and restart
  → the app relaunches itself, swaps the backup in, migrates it to v1.0, shows the restore notice and comes back to the
  wizard past Welcome (the puzzle database is already there, as after setup.py) → skip Stockfish and Lichess → the app.
  The data is the backup's, `setup.finished` is set, and the checkpoint backfill ran on the restored data.
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from tests.smoke.conftest import (
    RunningApp,
    attach,
    close_window_of,
    finish_wizard,
    free_port,
    launch_app,
    wait_for,
    windows_of,
)
from tests.smoke.test_qa_real_app_v016 import _Detached, _setting, answer_open_dialog
from weaksquare import config
from weaksquare.adapters import instance_lock
from weaksquare.adapters.backup_files import make_backup
from weaksquare.adapters.db.migrate import migrate, read_version
from weaksquare.core.clock import FixedClock

pytestmark = pytest.mark.smoke

V016_SCHEMA = 14


def v016_backup(tmp_path: Path) -> Path:
    """A backup as v0.16 made it: its user.db at schema 14 (migrations 0001–0014 only), with 3 puzzle attempts."""
    old_migrations = tmp_path / "v016-migrations"
    old_migrations.mkdir()
    for f in sorted((config.MIGRATIONS_DIR / "user").glob("*.sql")):
        if int(f.name[:4]) <= V016_SCHEMA:
            shutil.copy(f, old_migrations / f.name)
    db = tmp_path / "old-pc" / "user.db"
    db.parent.mkdir()
    migrate(db, old_migrations, FixedClock())
    assert read_version(db) == V016_SCHEMA
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('qa.marker', '\"from v0.16\"')")
    for i in range(3):
        conn.execute(
            "INSERT INTO attempts (puzzle_source, puzzle_id, mode, started_at, finished_at, win, first_move_correct,"
            " line_correct, time_ms) VALUES ('lichess', ?, 'standard', '2026-11-01T10:00:00+00:00',"
            " '2026-11-01T10:01:00+00:00', 1, 1, 1, 60000)",
            (f"qa{i:03d}",),
        )
    conn.commit()
    conn.close()
    zip_path = tmp_path / "backups" / "weaksquare-backup-2026-11-02.zip"
    make_backup(db, zip_path, tmp_path / "work", "0.16.0", "2026-11-02T18:05:00+00:00")
    return zip_path


def test_qa_restore_a_v016_backup_from_the_wizard_then_finish_into_the_app(  # type: ignore[no-untyped-def]
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:
    zip_path = v016_backup(tmp_path)
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")  # setup.py already imported it
    port = free_port()
    app = launch_app(data_dir, port)
    relaunched_pid = None
    try:
        with attach(pw, app, keep_wizard=True) as page:
            assert page.get_by_test_id("wizard").get_attribute("data-step") == "welcome"
            first_pid = app.app_pid()
            assert first_pid
            page.get_by_test_id("wizard-restore").click()
            answer_open_dialog(first_pid, zip_path)
            info = page.get_by_test_id("wizard-restore-info")
            info.wait_for(timeout=20_000)
            assert "WeakSquare 0.16.0" in info.inner_text() and "3 puzzle attempts" in info.inner_text()
            page.get_by_test_id("wizard-restore-go").click()
            app.process.wait(60)  # the window closes by itself to finish the restore
        assert app.process.returncode == 0

        def relaunched() -> bool:
            pid = instance_lock.read_pid(data_dir / "weaksquare.lock")
            return pid not in (None, first_pid) and bool(windows_of(pid))

        wait_for(relaunched, 60, "the app to relaunch itself with --after-restore")
        relaunched_pid = instance_lock.read_pid(data_dir / "weaksquare.lock")
        again = RunningApp(_Detached(data_dir), data_dir, port)  # type: ignore[arg-type]
        with attach(pw, again, keep_wizard=True) as page:
            page.get_by_test_id("restore-notice").wait_for(timeout=30_000)
            assert "restored from the backup made Nov 2, 2026" in page.get_by_test_id("restore-notice").inner_text()
            wizard = page.get_by_test_id("wizard")
            wizard.wait_for(timeout=30_000)
            assert wizard.get_attribute("data-step") in ("engine", "lichess")  # past Welcome and the puzzles
            finish_wizard(page)
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            wait_for(lambda: _setting(data_dir / "user.db", "checkpoints.backfill_version") == "1", 30,
                     "the checkpoint backfill on the restored data")  # fmt: skip
        close_window_of(relaunched_pid)  # type: ignore[arg-type]
        wait_for(lambda: not windows_of(relaunched_pid), 30, "the relaunched app to close")  # type: ignore[arg-type]
        time.sleep(1)
    finally:
        if app.process.poll() is None:
            app.process.kill()
        for pid in {instance_lock.read_pid(data_dir / "weaksquare.lock"), relaunched_pid} - {None}:
            if pid and windows_of(pid):
                with contextlib.suppress(Exception):
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    user_db = data_dir / "user.db"
    assert _setting(user_db, "qa.marker") == '"from v0.16"'  # the backup's data
    assert read_version(user_db) == len(list((config.MIGRATIONS_DIR / "user").glob("*.sql")))  # migrated to v1.0
    assert _setting(user_db, "setup.choice") == '"restore"' and _setting(user_db, "setup.finished") == "true"
    conn = sqlite3.connect(user_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 3
    finally:
        conn.close()
