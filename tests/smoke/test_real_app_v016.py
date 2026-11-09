"""v0.16 in the real app (WebView2 over CDP), on the fixture DB and temp data folders. Native dialogs can't be driven, so
the restore is staged the way the restore job stages it, then:
- the next real start swaps it in before anything opens user.db, keeps a before-restore backup, and shows the notice;
- a copy started with --after-restore waits for the running one to let go of the single-instance lock, then opens."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.smoke.conftest import ROOT, attach, free_port, launch_app, no_update_check, wait_for
from weaksquare import config
from weaksquare.adapters import instance_lock
from weaksquare.adapters.backup_files import BackupFiles, make_backup
from weaksquare.adapters.db.migrate import migrate
from weaksquare.core.clock import FixedClock

pytestmark = pytest.mark.smoke


def _setting(db: Path, key: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _backup_with_marker(tmp_path: Path) -> Path:
    other = tmp_path / "other-pc" / "user.db"
    other.parent.mkdir()
    migrate(other, config.MIGRATIONS_DIR / "user", FixedClock())
    conn = sqlite3.connect(other)
    conn.execute("INSERT INTO settings (key, value) VALUES ('smoke.marker', '\"from the backup\"')")
    conn.commit()
    conn.close()
    zip_path = tmp_path / "weaksquare-backup-2026-11-02.zip"
    make_backup(other, zip_path, tmp_path / "work", config.APP_VERSION, "2026-11-02T18:05:00+00:00")
    return zip_path


def _app_data(tmp_path: Path, fixture_puzzles_db: Path) -> Path:
    d = tmp_path / "app-data"
    d.mkdir()
    shutil.copyfile(fixture_puzzles_db, d / "puzzles.db")
    return d


def test_a_staged_restore_is_swapped_in_at_the_next_real_start(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = _app_data(tmp_path, fixture_puzzles_db)
    zip_path = _backup_with_marker(tmp_path)
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            paths = config.Paths(data_dir)
            files = BackupFiles(paths.user_db, paths.downloads_dir, paths.user_restore_db, paths.user_restore_manifest,
                                config.APP_VERSION)  # fmt: skip
            files.stage_restore(zip_path)  # what the restore job does, while the app runs
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert _setting(data_dir / "user.db", "smoke.marker") is None  # nothing changed until the restart

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            notice = page.get_by_test_id("restore-notice")
            notice.wait_for(timeout=30_000)
            assert "restored from the backup made Nov 2, 2026" in notice.inner_text()
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert _setting(data_dir / "user.db", "smoke.marker") == '"from the backup"'
    assert not (data_dir / "user.restore.db").exists() and not (data_dir / "user.restore.json").exists()
    assert len(list((data_dir / "backups").glob("before-restore-*.zip"))) == 1


def test_after_restore_waits_for_the_old_window_to_let_go(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = _app_data(tmp_path, fixture_puzzles_db)
    first = launch_app(data_dir, free_port())
    second = None
    try:
        with attach(pw, first) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
        first_pid = first.app_pid()
        port = free_port()
        env = dict(os.environ)
        env.pop("PYTEST_CURRENT_TEST", None)
        env[config.DATA_DIR_ENV] = str(data_dir)
        env["WEAKSQUARE_NO_DIALOGS"] = "1"
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
        no_update_check(data_dir)
        second = subprocess.Popen([sys.executable, "-m", "weaksquare", "--dev", "--after-restore"], cwd=ROOT, env=env)
        try:
            second.wait(3)
            pytest.fail("the --after-restore copy gave up instead of waiting for the lock")
        except subprocess.TimeoutExpired:
            pass  # still waiting, as it should
        assert first.close() == 0
        wait_for(lambda: instance_lock.read_pid(data_dir / "weaksquare.lock") not in (None, first_pid), 20,
                 "the --after-restore copy to take the lock")  # fmt: skip
        assert second.poll() is None
    finally:
        for proc in (first.process, second):
            if proc is not None and proc.poll() is None:
                pid = instance_lock.read_pid(data_dir / "weaksquare.lock")
                if pid:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
                proc.kill()
