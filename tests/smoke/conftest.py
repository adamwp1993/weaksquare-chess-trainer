"""Real-app smoke harness (ARCHITECTURE §6, SR-16).

Launches `python -m weaksquare --dev` with a temp data folder and the WebView2 remote-debugging
port on 127.0.0.1 (a random free port), then attaches Playwright with `connect_over_cdp`. Only this
harness ever sets the debugging variable, and the app accepts it only in dev runs.

Run: uv run pytest -m smoke
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.adapters import instance_lock

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def front_end_is_built() -> None:
    """The real app serves web/dist. Testing a build older than web/src tests old code, so stop with
    the command to run instead (v0.2: a stale build hid the new Settings menu)."""
    web = ROOT / "web"
    index = web / "dist" / "index.html"
    newest = max(p.stat().st_mtime for p in (web / "src").rglob("*") if p.is_file())
    if not index.is_file() or index.stat().st_mtime < newest:
        pytest.fail("web/dist is missing or older than web/src. Run: npm.cmd --prefix web run build", pytrace=False)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def windows_of(pid: int) -> list[int]:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd: int, _: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def close_window_of(pid: int) -> None:
    """Ask the app to close like a user would (WM_CLOSE), so shutdown runs (NFR-6)."""
    wm_close = 0x0010
    for hwnd in windows_of(pid):
        ctypes.windll.user32.PostMessageW(hwnd, wm_close, 0, 0)  # type: ignore[attr-defined]


@dataclass
class RunningApp:
    process: subprocess.Popen[bytes]
    data_dir: Path
    port: int

    def app_pid(self) -> int | None:
        """The real app process (the venv's python.exe is a launcher that spawns it)."""
        return instance_lock.read_pid(self.data_dir / "weaksquare.lock")

    def close(self, timeout: float = 20) -> int:
        pid = self.app_pid()
        close_window_of(pid or self.process.pid)
        try:
            return self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            raise


def launch_app(data_dir: Path, port: int, extra_env: dict[str, str] | None = None) -> RunningApp:
    if not (config.WEB_DIST / "index.html").is_file():
        pytest.fail("web/dist is missing: run npm.cmd --prefix web run build first")
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    env[config.DATA_DIR_ENV] = str(data_dir)
    env["WEAKSQUARE_NO_DIALOGS"] = "1"
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
    env.update(extra_env or {})
    no_update_check(data_dir)
    process = subprocess.Popen([sys.executable, "-m", "weaksquare", "--dev"], cwd=ROOT, env=env)
    return RunningApp(process, data_dir, port)


def no_update_check(data_dir: Path) -> None:
    """v0.2-B4: the app's daily update check would call database.lichess.org from every test launch
    (and its banner would appear mid-test). Turn it off in the test data folder's user.db, as the
    Settings switch does; the check itself is tested against recorded responses."""
    import sqlite3

    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.core.clock import FixedClock

    data_dir.mkdir(parents=True, exist_ok=True)
    user_db = data_dir / "user.db"
    migrate(user_db, config.MIGRATIONS_DIR / "user", FixedClock())
    conn = sqlite3.connect(user_db)
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('puzzle_db.auto_check', 'false')"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        conn.commit()
    finally:
        conn.close()


def wait_for(predicate: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {what}")


@pytest.fixture
def prepare_data_dir(tmp_path: Path) -> Path:
    """Tests can put a puzzles.db here before the app starts."""
    d = tmp_path / "app-data"
    d.mkdir()
    return d


@pytest.fixture
def real_app(prepare_data_dir: Path) -> Iterator[RunningApp]:
    if sys.platform != "win32":
        pytest.skip("the real app runs on Windows only")
    app = launch_app(prepare_data_dir, free_port())
    try:
        yield app
    finally:
        if app.process.poll() is None:
            with contextlib.suppress(Exception):
                app.close()
            if app.process.poll() is None:
                app.process.kill()


@pytest.fixture
def app_page(pw, real_app: RunningApp):  # type: ignore[no-untyped-def]
    """A Playwright page attached to the real app's WebView2 over CDP."""
    with attach(pw, real_app) as page:
        yield page


@contextlib.contextmanager
def attach(pw, real_app: RunningApp):  # type: ignore[no-untyped-def]
    endpoint = f"http://127.0.0.1:{real_app.port}"

    def app_page_listed() -> bool:
        """True once the debugging endpoint lists the app's page. Checked over plain HTTP *before*
        connecting: the sync Playwright API only learns about new pages while a call is running."""
        if real_app.process.poll() is not None:
            raise RuntimeError(f"the app exited early with code {real_app.process.returncode}")
        try:
            with urllib.request.urlopen(f"{endpoint}/json/list", timeout=2) as r:
                targets = json.loads(r.read())
        except OSError:
            return False
        return any(t.get("type") == "page" and t.get("url", "").startswith("http") for t in targets)

    wait_for(app_page_listed, 90, "the app page on the debugging port")
    browser = pw.chromium.connect_over_cdp(endpoint)
    page = None

    def page_ready() -> bool:
        """Find the app's page. While waiting, wait_for_event keeps Playwright's event loop running so
        the page's attach event is processed (a plain sleep doesn't; that was v0.1-B4)."""
        nonlocal page
        for ctx in browser.contexts:
            for p in ctx.pages:
                if p.url.startswith("http"):
                    page = p
                    return True
        for ctx in browser.contexts[:1]:
            with contextlib.suppress(Exception):
                ctx.wait_for_event("page", timeout=1000)
        return False

    wait_for(page_ready, 60, "the app page")
    assert page is not None
    page.wait_for_function("() => !!(window.pywebview && window.pywebview.api)", timeout=30_000)
    try:
        yield page
    finally:
        browser.close()
