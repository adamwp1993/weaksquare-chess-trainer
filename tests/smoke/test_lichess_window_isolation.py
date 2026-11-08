"""FR-13.3 gate (v0.14 step 0): the Lichess window is isolated from the app.

Launches the real `python -m weaksquare.lichess_window` child process against local probe pages (the `--test-origin` hook
accepts only http://127.0.0.1:<port>) and proves:

- the page sees no pywebview bridge; WebView2 host objects are refused; web messaging has no listener
- top-level navigation off the allowed origin is cancelled; http(s) links go to the system browser (a recorder here,
  via the BROWSER variable), and other schemes (file:, ms-settings:) are dropped, never handed to Windows
- popups (target=_blank, window.open) never open a second page in the window
- a WebView2 debugging port inherited from the app's environment is ignored
- the temporary profile is deleted when the window closes, and closing the app's end of the pipe closes the window
- what the window tells the app holds IDs, scheme and host only, never an address

Run: uv run pytest -m smoke tests/smoke/test_lichess_window_isolation.py
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.smoke.conftest import ROOT, free_port, wait_for

pytestmark = [pytest.mark.smoke, pytest.mark.skipif(sys.platform != "win32", reason="WebView2 is Windows-only")]

PAGES = {
    "probe.html": "<!doctype html><title>probe</title><p>probe</p>",
    "away.html": "<!doctype html><script>setTimeout(() => location.href = 'https://example.com/away', 100)</script>",
    "file.html": "<!doctype html><script>setTimeout(() => location.href = 'file:///C:/Windows/win.ini', 100)</script>",
    "proto.html": "<!doctype html><script>setTimeout(() => location.href = 'ms-settings:privacy', 100)</script>",
    "popups.html": (
        "<!doctype html><a id=b href='https://example.com/blank' target=_blank>b</a>"
        "<a id=l href='/probe.html?popup' target=_blank>l</a>"
        "<script>setTimeout(() => { window.open('https://example.org/pop'); document.getElementById('b').click();"
        " document.getElementById('l').click(); }, 100)</script>"
    ),
}

# Python's webbrowser runs BROWSER as one program name with the URL as its only argument (no arguments of its own on
# Windows), so the recorder is a batch file that hands the URL to a Python script. Each call writes its own uniquely
# named file in WS_BROWSER_LOG (a folder): two popups open at once, and cmd's %RANDOM% repeats within the same second.
RECORDER_PY = "import os, sys, uuid\nopen(os.path.join(os.environ['WS_BROWSER_LOG'], uuid.uuid4().hex + '.txt'), 'w').write(sys.argv[1])\n"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


@dataclass
class Window:
    process: subprocess.Popen[str]
    origin: str
    cdp: int | None
    browser_log: Path
    temp: Path
    messages: list[dict[str, object]] = field(default_factory=list)

    def of_type(self, kind: str) -> list[dict[str, object]]:
        return [m for m in list(self.messages) if m.get("type") == kind]

    def opened_in_browser(self) -> list[str]:
        return sorted(line for f in self.browser_log.glob("*.txt") for line in f.read_text().split())

    def page_targets(self) -> list[str]:
        assert self.cdp is not None
        with urllib.request.urlopen(f"http://127.0.0.1:{self.cdp}/json/list", timeout=5) as r:
            return [t["url"] for t in json.loads(r.read()) if t.get("type") == "page"]

    def close(self) -> int:
        if self.process.poll() is None:
            with contextlib.suppress(OSError, ValueError):
                assert self.process.stdin is not None
                self.process.stdin.write("close\n")
                self.process.stdin.flush()
        return self.process.wait(20)


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    root = tmp_path / "site"
    root.mkdir()
    for name, html in PAGES.items():
        (root / name).write_text(html, encoding="utf-8")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture
def open_window(tmp_path: Path, site: str) -> Iterator:  # type: ignore[type-arg]
    windows: list[Window] = []

    def launch(page: str, *, cdp: bool = True, inherited_port: int | None = None) -> Window:
        temp = tmp_path / f"temp{len(windows)}"
        temp.mkdir()
        script = tmp_path / "recorder.py"
        script.write_text(RECORDER_PY, encoding="utf-8")
        recorder = tmp_path / "recorder.bat"
        recorder.write_bytes(f'@"{sys.executable}" "{script}" %1\r\n'.encode("mbcs"))
        log = tmp_path / f"browser{len(windows)}"
        log.mkdir()
        env = dict(os.environ)
        env.update(TEMP=str(temp), TMP=str(temp), WS_BROWSER_LOG=str(log), BROWSER=str(recorder))
        if inherited_port is not None:
            env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={inherited_port}"
        port = free_port() if cdp else None
        args = [
            sys.executable,
            "-m",
            "weaksquare.lichess_window",
            "--start-url",
            f"{site}/{page}",
            "--test-origin",
            site,
        ]
        if port is not None:
            args += ["--test-cdp-port", str(port)]
        proc = subprocess.Popen(
            args, cwd=ROOT, env=env, text=True, encoding="utf-8",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip
        w = Window(proc, site, port, log, temp)

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                with contextlib.suppress(ValueError):
                    w.messages.append(json.loads(line))

        threading.Thread(target=pump, daemon=True).start()
        windows.append(w)

        def ready() -> bool:
            if proc.poll() is not None:
                raise RuntimeError(f"window exited {proc.returncode}: {proc.stderr.read() if proc.stderr else ''}")
            return bool(w.of_type("ready"))

        wait_for(ready, 60, "the Lichess window")
        return w

    yield launch
    for w in windows:
        with contextlib.suppress(Exception):
            w.close()
        if w.process.poll() is None:
            w.process.kill()


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_page_has_no_bridge_no_host_objects_and_no_message_listener(open_window, pw) -> None:  # type: ignore[no-untyped-def]
    w = open_window("probe.html")
    wait_for(lambda: _listening(w.cdp), 30, "the test debugging port")
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{w.cdp}")
    try:
        page = browser.contexts[0].pages[0]
        page.wait_for_load_state()
        seen = page.evaluate(
            """async () => {
                const wv = window.chrome && window.chrome.webview;
                let host = 'none';
                if (wv && wv.hostObjects) {
                    try { await wv.hostObjects.anything; host = 'reachable'; } catch (e) { host = 'denied'; }
                }
                let posted = 'n/a';
                if (wv && wv.postMessage) {
                    try { wv.postMessage(JSON.stringify(['api.get_settings', '[]', '1'])); posted = 'sent'; }
                    catch (e) { posted = 'threw'; }
                }
                return { pywebview: typeof window.pywebview, external: typeof (window.external && window.external.invoke),
                         host, posted, api: typeof (window.pywebview && window.pywebview.api) };
            }"""
        )
    finally:
        browser.close()
    assert seen["pywebview"] == "undefined"
    assert seen["api"] == "undefined"
    assert seen["external"] == "undefined"
    assert seen["host"] in ("none", "denied")
    # Whatever postMessage does, nothing answers: the window never subscribes to WebMessageReceived and turns
    # messaging off (checked statically in tests/unit/test_lichess_window.py). It stays alive and silent.
    time.sleep(1)
    assert w.process.poll() is None
    assert not [m for m in w.messages if m.get("type") not in ("ready", "page")]


@pytest.mark.parametrize(
    ("page", "blocked", "logged"),
    [
        ("away.html", {"scheme": "https", "host": "example.com", "opened": True}, ["https://example.com/away"]),
        # Chromium itself refuses a jump from a web page to file: before WebView2 raises NavigationStarting.
        ("file.html", None, []),
        ("proto.html", {"scheme": "ms-settings", "host": "", "opened": False}, []),
    ],
)
def test_leaving_the_allowed_site_is_refused(open_window, page, blocked, logged) -> None:  # type: ignore[no-untyped-def]
    w = open_window(page)
    if blocked is None:
        time.sleep(3)
        assert w.of_type("blocked") == []
    else:
        wait_for(lambda: bool(w.of_type("blocked")), 20, "the refused navigation")
        assert w.of_type("blocked")[0] == {"type": "blocked", **blocked}
    if logged:
        wait_for(lambda: w.opened_in_browser() == logged, 20, "the system browser recorder")
    time.sleep(1)
    assert w.opened_in_browser() == logged
    assert w.page_targets() == [f"{w.origin}/{page}"]


def test_popups_never_open_a_second_page(open_window) -> None:  # type: ignore[no-untyped-def]
    w = open_window("popups.html")
    wait_for(lambda: len(w.of_type("blocked")) >= 2, 20, "both refused popups")
    hosts = sorted(str(m["host"]) for m in w.of_type("blocked"))
    assert hosts == ["example.com", "example.org"]
    wait_for(lambda: len(w.opened_in_browser()) == 2, 20, "the system browser recorder")
    assert sorted(w.opened_in_browser()) == ["https://example.com/blank", "https://example.org/pop"]
    # The allowed target=_blank link opened in the same window, not a new one.
    wait_for(lambda: w.page_targets() == [f"{w.origin}/probe.html?popup"], 20, "the same-window navigation")


def test_inherited_debugging_port_is_ignored(open_window) -> None:  # type: ignore[no-untyped-def]
    inherited = free_port()
    w = open_window("probe.html", cdp=False, inherited_port=inherited)
    time.sleep(2)
    assert w.process.poll() is None
    assert not _listening(inherited)


def test_profile_is_deleted_and_closing_the_pipe_closes_the_window(open_window) -> None:  # type: ignore[no-untyped-def]
    w = open_window("probe.html", cdp=False)
    wait_for(lambda: any(w.temp.glob("weaksquare-lichess-*")), 20, "the temporary profile")
    assert w.process.stdin is not None
    w.process.stdin.close()  # the app went away
    assert w.process.wait(20) == 0
    wait_for(lambda: bool(w.of_type("closed")), 5, "the closed message")
    assert not list(w.temp.glob("weaksquare-lichess-*"))


def test_messages_never_carry_an_address(open_window) -> None:  # type: ignore[no-untyped-def]
    w = open_window("away.html")
    wait_for(lambda: bool(w.of_type("blocked")) and bool(w.of_type("page")), 20, "page and blocked messages")
    w.close()
    for m in w.messages:
        for value in m.values():
            assert not (isinstance(value, str) and "://" in value), m
