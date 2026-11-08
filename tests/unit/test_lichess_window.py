"""FR-13.3, 13.4 (v0.14 step 0): the Lichess window process, checked without opening a window.

The real window is driven in tests/smoke/test_lichess_window_isolation.py. Here: what the module may import, the
WebView2 settings it must set, the toolbar's rule, the test hook's limits, and the two bugs step 0 found.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from weaksquare import lichess_window as lw

SOURCE = Path(lw.__file__).read_text(encoding="utf-8")


def test_imports_nothing_that_reaches_the_app() -> None:
    """No bridge, services, adapters (database, secret store, HTTP) and no keyring in the window process."""
    code = (
        "import sys, weaksquare.lichess_window as m; "
        "print('\\n'.join(sorted(n for n in sys.modules if n.startswith('weaksquare') or n in ('keyring', 'webview'))))"
    )
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert sorted(loaded) == [
        "weaksquare",
        "weaksquare.core",
        "weaksquare.core.study_links",
        "weaksquare.lichess_window",
    ]


def test_static_isolation_settings() -> None:
    """The settings the smoke test can't observe directly, pinned in the source."""
    for required in (
        "s.IsWebMessageEnabled = False",
        "s.AreHostObjectsAllowed = False",
        "s.IsPasswordAutosaveEnabled = False",
        "s.IsGeneralAutofillEnabled = False",
        "props.UserDataFolder = str(profile)",
        "core.NavigationStarting += on_nav_starting",
        "core.NewWindowRequested += on_new_window",
        "core.PermissionRequested += on_permission",
        "core.DownloadStarting += on_download",
    ):
        assert required in SOURCE, required
    for forbidden in ("WebMessageReceived", "AddHostObjectToScript", "ExecuteScript", "create_window", "js_api"):
        assert forbidden not in SOURCE, forbidden


@pytest.mark.parametrize(
    ("url", "enabled", "study", "chapter"),
    [
        ("https://lichess.org/study/ZCPaIb70", True, "ZCPaIb70", None),
        ("https://lichess.org/study/nq1GGbNO/rWqJitDx", True, "nq1GGbNO", "rWqJitDx"),
        ("https://lichess.org/study", False, None, None),
        ("https://lichess.org/study/search?q=vienna", False, None, None),
        ("https://lichess.org/abcdefgh", False, None, None),
        ("http://127.0.0.1:5000/study/ZCPaIb70", False, None, None),
        ("", False, None, None),
    ],
)
def test_add_this_study_is_enabled_only_on_a_study_page(
    url: str, enabled: bool, study: str | None, chapter: str | None
) -> None:
    assert lw.toolbar_state(url) == (enabled, {"study": study, "chapter": chapter})


@pytest.mark.parametrize("value", ["http://127.0.0.1:5000", "http://127.0.0.1:5000/"])
def test_test_origin_accepts_only_loopback(value: str) -> None:
    assert lw.test_origin_arg(value) == "http://127.0.0.1:5000"


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:5000",
        "http://localhost:5000",
        "http://127.0.0.1",
        "http://example.com:80",
        "http://127.0.0.1:5000/x",
    ],
)
def test_test_origin_refuses_anything_else(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        lw.test_origin_arg(value)


def test_policy() -> None:
    plain = lw.Policy()
    assert plain.allows("https://lichess.org/study")
    assert not plain.allows("http://127.0.0.1:5000/probe.html")
    hooked = lw.Policy("http://127.0.0.1:5000")
    assert hooked.allows("http://127.0.0.1:5000/probe.html")
    assert not hooked.allows("http://127.0.0.1:50001/probe.html")
    assert not hooked.allows("https://example.com/")


def test_refuses_a_start_page_off_lichess() -> None:
    assert lw.main(["--start-url", "https://example.com/"]) == 2


def test_regression_two_links_at_once_both_reach_the_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 0 bug: webbrowser's first-use setup isn't thread-safe, so two links handed over at once lost one. The
    window serializes the calls."""
    active, peak, opened = [0], [0], []
    guard = threading.Lock()

    def slow_open(url: str) -> bool:
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        opened.append(url)
        with guard:
            active[0] -= 1
        return True

    monkeypatch.setattr(lw.webbrowser, "open", slow_open)
    threads = [threading.Thread(target=lw._open_in_browser, args=(f"https://example.com/{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(opened) == [f"https://example.com/{i}" for i in range(4)]
    assert peak[0] == 1


def test_regression_pipes_are_not_inherited() -> None:
    """Step 0 bug: a program the window started inherited its blocking stdin pipe and hung until the window closed."""
    code = (
        "import os, weaksquare.lichess_window as m; m._clean_env(); "
        "print(all(not os.get_inheritable(fd) for fd in (0, 1, 2)))"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, stdin=subprocess.PIPE, check=True)
    assert r.stdout.strip() == "True"


def test_clean_env_drops_webview2_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--remote-debugging-port=9222")
    monkeypatch.setenv("WEBVIEW2_USER_DATA_FOLDER", "C:/elsewhere")
    monkeypatch.setattr(lw.os, "set_inheritable", lambda fd, value: None)
    lw._clean_env()
    assert "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" not in lw.os.environ
    assert "WEBVIEW2_USER_DATA_FOLDER" not in lw.os.environ


def test_remove_profile_retries_until_gone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "weaksquare-lichess-x"
    profile.mkdir()
    calls = [0]
    real = lw.shutil.rmtree

    def flaky(path: Path, ignore_errors: bool = False) -> None:
        calls[0] += 1
        if calls[0] >= 3:
            real(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(lw.shutil, "rmtree", flaky)
    monkeypatch.setattr(lw.time, "sleep", lambda s: None)
    lw._remove_profile(profile)
    assert not profile.exists()
    assert calls[0] == 3
