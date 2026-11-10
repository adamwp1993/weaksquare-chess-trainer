"""Playwright against the web UI built with the mock client (`uv run pytest -m e2e`).

The fixture builds `web/dist-mock` (`npm run build:mock`, found with shutil.which so npm.cmd works on
Windows) when it's missing or older than web/src, serves it on 127.0.0.1, and opens headless Chromium.
"""

from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from weaksquare.app import fix_mime_types

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DIST = WEB / "dist-mock"


def _newest(folder: Path) -> float:
    return max(p.stat().st_mtime for p in folder.rglob("*") if p.is_file())


def ensure_mock_build() -> None:
    index = DIST / "index.html"
    sources = max(_newest(WEB / "src"), (WEB / "index.html").stat().st_mtime, (WEB / "vite.config.ts").stat().st_mtime)
    if index.exists() and index.stat().st_mtime >= sources:
        return
    npm = shutil.which("npm")
    if npm is None:
        pytest.fail("npm not found: install Node.js LTS")
    subprocess.run([npm, "run", "build:mock"], cwd=WEB, check=True, capture_output=True)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="session")
def mock_url() -> Iterator[str]:
    ensure_mock_build()
    fix_mime_types()  # Windows may map .js to text/plain; module scripts then won't run
    handler = functools.partial(_Quiet, directory=str(DIST))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def browser(pw):  # type: ignore[no-untyped-def]
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture
def page(browser, mock_url: str):  # type: ignore[no-untyped-def]
    context = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.base_url = mock_url  # type: ignore[attr-defined]
    # v0.3: the startup page comes first at every launch. Every goto continues past it, unless the
    # URL has `startup=show` (the tests of the startup page itself).
    original_goto = p.goto

    def goto(url: str, **kwargs):  # type: ignore[no-untyped-def]
        response = original_goto(url, **kwargs)
        if "startup=show" not in url and "scenario=fresh" not in url:  # v1.0: a fresh install shows the wizard
            continue_past_startup(p)
        return response

    p.goto = goto  # type: ignore[method-assign]
    yield p
    context.close()
    assert errors == [], f"page errors: {errors}"


def continue_past_startup(page) -> None:  # type: ignore[no-untyped-def]
    """Click the startup page's Continue button (Continue as <name> / without signing in)."""
    page.get_by_test_id("startup-continue").click()
    page.get_by_test_id("startup").wait_for(state="detached")


def click_square(page, square: str, orientation: str) -> None:  # type: ignore[no-untyped-def]
    """Click a square on the chessground board (click-click moves)."""
    board = page.get_by_test_id("board")
    board.scroll_into_view_if_needed()  # the filter panel can push the board below the fold (v0.2)
    box = board.bounding_box()
    size = box["width"] / 8
    file = "abcdefgh".index(square[0])
    rank = int(square[1]) - 1
    col = file if orientation == "white" else 7 - file
    row = 7 - rank if orientation == "white" else rank
    page.mouse.click(box["x"] + (col + 0.5) * size, box["y"] + (row + 0.5) * size)


def play(page, uci: str, orientation: str) -> None:  # type: ignore[no-untyped-def]
    click_square(page, uci[:2], orientation)
    click_square(page, uci[2:4], orientation)
