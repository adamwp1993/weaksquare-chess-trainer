"""QA v0.16 in the real app: the whole restore through the UI, with the native Open dialog driven over Win32.

Settings → Your data → Restore from a backup… → (Open dialog: type the path, Open) → Replace my data → the window closes,
the app relaunches itself with --after-restore, swaps the backup in, and shows the notice. Temp data folders only."""

from __future__ import annotations

import contextlib
import ctypes
import shutil
import sqlite3
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.smoke.conftest import RunningApp, attach, free_port, launch_app, wait_for, windows_of
from weaksquare import config
from weaksquare.adapters import instance_lock
from weaksquare.adapters.backup_files import make_backup
from weaksquare.adapters.db.migrate import migrate
from weaksquare.core.clock import FixedClock

pytestmark = pytest.mark.smoke

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetDlgItem.restype = wintypes.HWND
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
WM_SETTEXT, BM_CLICK, IDOK, FILE_NAME_COMBO = 0x000C, 0x00F5, 1, 1148


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def open_dialog_of(pid: int) -> int | None:
    for hwnd in windows_of(pid):
        if _class(hwnd) == "#32770":
            return hwnd
    return None


def answer_open_dialog(pid: int, path: Path) -> None:
    """Type `path` into the native Open dialog's File name box and press Open."""
    found: list[int] = []
    wait_for(lambda: bool(found.append(open_dialog_of(pid) or 0) or found[-1]), 30, "the native Open dialog")  # type: ignore[func-returns-value]
    dlg = found[-1]
    combo = user32.GetDlgItem(dlg, FILE_NAME_COMBO)
    edit = (
        user32.FindWindowExW(user32.FindWindowExW(combo, None, "ComboBox", None), None, "Edit", None) if combo else None
    )
    if not edit:  # older layouts put the Edit straight under the dialog
        edit = user32.FindWindowExW(dlg, None, "Edit", None)
    assert edit, "no File name box in the Open dialog"
    user32.SendMessageW(edit, WM_SETTEXT, 0, str(path))
    time.sleep(0.3)
    user32.PostMessageW(user32.GetDlgItem(dlg, IDOK), BM_CLICK, 0, 0)


@dataclass
class _Detached:
    """The relaunched app isn't our child: poll() via the lock file's PID."""

    data_dir: Path

    def poll(self) -> int | None:
        return None

    @property
    def returncode(self) -> int | None:
        return None


def _setting(db: Path, key: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_qa_restore_through_the_ui_restarts_the_real_app_and_swaps_the_data(pw, tmp_path: Path,
                                                                              fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]  # fmt: skip
    other = tmp_path / "other-pc" / "user.db"
    other.parent.mkdir()
    migrate(other, config.MIGRATIONS_DIR / "user", FixedClock())
    conn = sqlite3.connect(other)
    conn.execute("INSERT INTO settings (key, value) VALUES ('qa.marker', '\"from the backup\"')")
    conn.execute(
        'INSERT INTO settings (key, value) VALUES (\'backup.auto\', \'{"enabled": true, "folder": "Z:\\\\\\\\x"}\')'
    )
    conn.commit()
    conn.close()
    zip_path = tmp_path / "Ünïcødé folder" / "weaksquare-backup-2026-11-02.zip"
    make_backup(other, zip_path, tmp_path / "work", config.APP_VERSION, "2026-11-02T18:05:00+00:00")

    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    port = free_port()
    app = launch_app(data_dir, port)
    relaunched_pid = None
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            first_pid = app.app_pid()
            assert first_pid
            page.get_by_test_id("gear").click()
            page.get_by_test_id("backup-settings").scroll_into_view_if_needed()
            page.get_by_test_id("restore-choose").click()
            answer_open_dialog(first_pid, zip_path)
            info = page.get_by_test_id("restore-info")
            info.wait_for(timeout=20_000)
            assert "WeakSquare " + config.APP_VERSION in info.inner_text()
            assert _setting(data_dir / "user.db", "qa.marker") is None
            page.get_by_test_id("restore-replace").click()
            # the window closes by itself; the first process exits
            app.process.wait(60)
        assert app.process.returncode == 0

        def relaunched() -> bool:
            pid = instance_lock.read_pid(data_dir / "weaksquare.lock")
            return pid not in (None, first_pid) and bool(windows_of(pid))

        wait_for(relaunched, 60, "the app to relaunch itself with --after-restore")
        relaunched_pid = instance_lock.read_pid(data_dir / "weaksquare.lock")
        again = RunningApp(_Detached(data_dir), data_dir, port)  # type: ignore[arg-type]  # same env: same CDP port
        with attach(pw, again) as page:
            notice = page.get_by_test_id("restore-notice")
            notice.wait_for(timeout=30_000)
            assert "restored from the backup made Nov 2, 2026" in notice.inner_text()
            page.get_by_test_id("gear").click()
            page.get_by_test_id("backup-settings").scroll_into_view_if_needed()
            assert "none chosen" in page.get_by_test_id("backup-folder").inner_text()  # PC-only: not the old PC's
        from tests.smoke.conftest import close_window_of

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
    assert _setting(data_dir / "user.db", "qa.marker") == '"from the backup"'
    assert _setting(data_dir / "user.db", "backup.auto") is None
    assert not (data_dir / "user.restore.db").exists() and not (data_dir / "user.restore.json").exists()
    assert len(list((data_dir / "backups").glob("before-restore-*.zip"))) == 1


def test_qa_r2_b7_the_real_app_runs_and_backs_up_in_a_data_folder_with_hash_and_percent(  # type: ignore[no-untyped-def]
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:
    """v0.16-B7: `#` and `%41` in the data folder path. The app opens puzzles.db and shows the match count, and a
    restore staged there is swapped in at the next start (check_db and the before-restore backup both run)."""
    data_dir = tmp_path / "C#dev %41 data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    other = tmp_path / "other" / "user.db"
    other.parent.mkdir()
    migrate(other, config.MIGRATIONS_DIR / "user", FixedClock())
    conn = sqlite3.connect(other)
    conn.execute("INSERT INTO settings (key, value) VALUES ('qa.marker', '\"hash folder\"')")
    conn.commit()
    conn.close()
    zip_path = tmp_path / "b.zip"
    make_backup(other, zip_path, tmp_path / "work", config.APP_VERSION, "2026-11-02T18:05:00+00:00")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            from weaksquare.adapters.backup_files import BackupFiles

            paths = config.Paths(data_dir)
            BackupFiles(paths.user_db, paths.downloads_dir, paths.user_restore_db, paths.user_restore_manifest,
                        config.APP_VERSION).stage_restore(zip_path)  # fmt: skip
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("restore-notice").wait_for(timeout=30_000)
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert _setting(data_dir / "user.db", "qa.marker") == '"hash folder"'
    assert len(list((data_dir / "backups").glob("before-restore-*.zip"))) == 1
