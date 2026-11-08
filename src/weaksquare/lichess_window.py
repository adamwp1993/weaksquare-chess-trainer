"""The Lichess window (FR-13.3, 13.4): real lichess.org study pages in a separate, isolated process.

Run by `adapters/lichess_window.py` as `python -m weaksquare.lichess_window`. It is deliberately **not** a pywebview
window: pywebview turns on WebView2 web messaging and injects its JS bridge into every window it creates
(ARCHITECTURE §7, v0.14), so a remote page in the app's own process could reach it. Here a WinForms form hosts a bare
WebView2 control through pythonnet, using the WebView2 assemblies pywebview ships:

- its own temporary browser profile, deleted on close (you're signed out of Lichess each time)
- web messaging, host objects, autofill, password saving, downloads and every permission request turned off
- top-level pages limited to https://lichess.org; any other link opens in the system browser (http/https only)
- a **native** toolbar (Back, Forward, Add this study) above the page, never inside it

This module imports only the standard library, pythonnet and `core.study_links` (an import test enforces it): no bridge,
services, database or secret store. It talks to the app through stdout, one JSON object per line:
`{"type": "ready"}`, `{"type": "page", "study": id|null, "chapter": id|null}` (never the address),
`{"type": "add", "study": id, "chapter": id|null}`, `{"type": "blocked", "scheme": …, "host": …, "opened": bool}`
(a page it refused; scheme and host only) and `{"type": "closed"}`. It reads `focus`, `add` (the same as
clicking the button; for tests) and `close` lines on stdin. The app re-checks every ID it receives.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from weaksquare.core.study_links import STUDY_LIST_URL, is_browser_safe, is_lichess_page, parse_study_ref

TITLE = "Lichess studies (WeakSquare)"
_WEBVIEW2_ENV = (
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
    "WEBVIEW2_USER_DATA_FOLDER",
    "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE",
    "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER",
    "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER",
)


@dataclass(frozen=True)
class Policy:
    """What the window may show itself. `test_origin` (tests only) also allows one http://127.0.0.1 origin."""

    test_origin: str | None = None

    def allows(self, url: str) -> bool:
        if is_lichess_page(url):
            return True
        if self.test_origin is None:
            return False
        return url == self.test_origin or url.startswith(self.test_origin + "/")


def toolbar_state(url: str) -> tuple[bool, dict[str, str | None]]:
    """Whether **Add this study** is enabled on this page, and the study it would add (FR-13.4)."""
    ref = parse_study_ref(url) if is_lichess_page(url) else None
    if ref is None:
        return False, {"study": None, "chapter": None}
    return True, {"study": ref.study_id, "chapter": ref.chapter_id}


def test_origin_arg(value: str) -> str:
    """`--test-origin` accepts only http://127.0.0.1:<port>, so a test hook can never widen the window to the web."""
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as e:
        raise argparse.ArgumentTypeError("bad port") from e
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or port is None or parts.path not in ("", "/"):
        raise argparse.ArgumentTypeError("--test-origin must be http://127.0.0.1:<port>")
    return f"http://127.0.0.1:{port}"


class _Out:
    """One JSON object per stdout line, from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def send(self, **msg: object) -> None:
        line = json.dumps(msg, ensure_ascii=True)
        with self._lock, contextlib.suppress(OSError, ValueError):
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m weaksquare.lichess_window", description=__doc__.splitlines()[0])
    p.add_argument("--start-url", default=STUDY_LIST_URL, help="first page (must be a lichess.org page)")
    p.add_argument("--test-origin", type=test_origin_arg, default=None, help=argparse.SUPPRESS)
    p.add_argument("--test-cdp-port", type=int, default=None, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def _clean_env() -> None:
    """Never inherit WebView2 overrides (a debugging port, another profile) from the app's environment, and never pass
    the pipes to the app on to programs this window starts (the system browser). The stdin reader blocks on a
    synchronous pipe, and a child process that inherited that handle hung at startup until the window closed (found in
    the step 0 smoke test with a BROWSER command)."""
    for name in _WEBVIEW2_ENV:
        os.environ.pop(name, None)
    for fd in (0, 1, 2):
        with contextlib.suppress(OSError):
            os.set_inheritable(fd, False)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives a real window; tests/smoke covers it
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    policy = Policy(args.test_origin)
    if not policy.allows(args.start_url):
        print(f"refusing start page {args.start_url!r}", file=sys.stderr)
        return 2
    _clean_env()
    out = _Out()
    profile = Path(tempfile.mkdtemp(prefix="weaksquare-lichess-"))
    try:
        return _run(args, policy, out, profile)
    finally:
        _remove_profile(profile)
        out.send(type="closed")


_BROWSER_LOCK = threading.Lock()


def _open_in_browser(url: str) -> None:
    """Hand one link to the system browser, one at a time. webbrowser's first-use setup isn't thread-safe: it publishes
    an empty browser list before filling it, so a second call at the same moment finds nothing and silently does
    nothing. A page opening two popups lost one (reproduced outside the window with two threads, v0.14 step 0)."""
    with _BROWSER_LOCK:
        webbrowser.open(url)


def _remove_profile(profile: Path, attempts: int = 20) -> None:
    """Delete the temporary profile. WebView2's helper processes can hold files for a moment after the browser
    process exits, so retry briefly."""
    for _ in range(attempts):
        shutil.rmtree(profile, ignore_errors=True)
        if not profile.exists():
            return
        time.sleep(0.25)


def _run(args: argparse.Namespace, policy: Policy, out: _Out, profile: Path) -> int:  # pragma: no cover
    try:
        import clr  # pythonnet, installed with pywebview on Windows
    except Exception:
        os.environ["PYTHONNET_RUNTIME"] = "coreclr"
        import clr

    import webview  # only for the location of the WebView2 assemblies it ships; no pywebview window is created

    lib = Path(webview.__file__).parent / "lib"
    native = lib / "runtimes" / ("win-arm64" if os.environ.get("PROCESSOR_ARCHITECTURE") == "ARM64" else "win-x64")
    if (native / "native").is_dir():
        os.add_dll_directory(str(native / "native"))
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    clr.AddReference(str(lib / "Microsoft.Web.WebView2.Core.dll"))
    clr.AddReference(str(lib / "Microsoft.Web.WebView2.WinForms.dll"))

    import System.Windows.Forms as WinForms  # type: ignore[import-not-found]
    from Microsoft.Web.WebView2.Core import (  # type: ignore[import-not-found]
        CoreWebView2PermissionState,
    )
    from Microsoft.Web.WebView2.WinForms import (  # type: ignore[import-not-found]
        CoreWebView2CreationProperties,
        WebView2,
    )
    from System import Action  # type: ignore[import-not-found]
    from System.Diagnostics import Process  # type: ignore[import-not-found]
    from System.Drawing import Size  # type: ignore[import-not-found]
    from System.Threading import ApartmentState, Thread, ThreadStart  # type: ignore[import-not-found]

    result = {"code": 0}

    def build_and_run() -> None:
        WinForms.Application.EnableVisualStyles()
        form = WinForms.Form()
        form.Text = TITLE
        form.Size = Size(1200, 860)
        form.MinimumSize = Size(800, 600)

        bar = WinForms.FlowLayoutPanel()
        bar.Dock = WinForms.DockStyle.Top
        bar.AutoSize = True
        bar.WrapContents = False
        back = WinForms.Button()
        back.Text = "◀ Back"
        back.AutoSize = True
        back.Enabled = False
        fwd = WinForms.Button()
        fwd.Text = "Forward ▶"
        fwd.AutoSize = True
        fwd.Enabled = False
        add = WinForms.Button()
        add.Text = "Add this study"
        add.AutoSize = True
        add.Enabled = False
        hint = WinForms.Label()
        hint.AutoSize = True
        hint.Padding = WinForms.Padding(8, 8, 0, 0)
        hint.Text = "Open a study, then click Add this study."
        for c in (back, fwd, add, hint):
            bar.Controls.Add(c)

        view = WebView2()
        view.Dock = WinForms.DockStyle.Fill
        props = CoreWebView2CreationProperties()
        props.UserDataFolder = str(profile)
        if args.test_cdp_port:
            props.AdditionalBrowserArguments = f"--remote-debugging-port={int(args.test_cdp_port)}"
        view.CreationProperties = props
        form.Controls.Add(view)
        form.Controls.Add(bar)  # added last so it docks above the page

        state: dict[str, object] = {"url": "", "ref": {"study": None, "chapter": None}}

        def to_browser(url: str) -> None:
            """A page the window won't show: hand http(s) links to the system browser, drop anything else. The app
            hears only the scheme and host, never the full address (it could hold a search you typed)."""
            safe = is_browser_safe(url)
            parts = urlsplit(url)
            out.send(type="blocked", scheme=parts.scheme[:16], host=(parts.hostname or "")[:253], opened=safe)
            if safe:
                threading.Thread(
                    target=_open_in_browser, args=(url,), name="lichess-window-browser", daemon=True
                ).start()

        def refresh() -> None:
            core = view.CoreWebView2
            url = str(core.Source) if core is not None else ""
            enabled, ref = toolbar_state(url)
            state["url"], state["ref"] = url, ref
            add.Enabled = enabled
            hint.Text = (
                "Click Add this study to keep a copy in WeakSquare."
                if enabled
                else "Open a study, then click Add this study."
            )
            if core is not None:
                back.Enabled = bool(core.CanGoBack)
                fwd.Enabled = bool(core.CanGoForward)
            out.send(type="page", **ref)  # IDs only: a search page's address holds what you typed

        def do_add() -> None:
            ref = state["ref"]
            if isinstance(ref, dict) and ref.get("study"):
                out.send(type="add", study=ref["study"], chapter=ref.get("chapter"))

        def on_nav_starting(_s: object, e: object) -> None:
            url = str(e.Uri)  # type: ignore[attr-defined]
            if not policy.allows(url):
                e.Cancel = True  # type: ignore[attr-defined]
                to_browser(url)

        def on_new_window(_s: object, e: object) -> None:
            e.Handled = True  # type: ignore[attr-defined]
            url = str(e.Uri)  # type: ignore[attr-defined]
            if policy.allows(url):
                view.CoreWebView2.Navigate(url)
            else:
                to_browser(url)

        def on_permission(_s: object, e: object) -> None:
            e.State = CoreWebView2PermissionState.Deny  # type: ignore[attr-defined]

        def on_download(_s: object, e: object) -> None:
            e.Cancel = True  # type: ignore[attr-defined]

        def on_ready(_s: object, e: object) -> None:
            if not e.IsSuccess:  # type: ignore[attr-defined]
                print(f"WebView2 failed to start: {e.InitializationException}", file=sys.stderr)  # type: ignore[attr-defined]
                result["code"] = 3
                form.Close()
                return
            core = view.CoreWebView2
            s = core.Settings
            s.IsWebMessageEnabled = False
            s.AreHostObjectsAllowed = False
            s.AreDevToolsEnabled = bool(args.test_cdp_port)
            s.IsGeneralAutofillEnabled = False
            s.IsPasswordAutosaveEnabled = False
            s.IsStatusBarEnabled = True
            core.NavigationStarting += on_nav_starting
            core.NewWindowRequested += on_new_window
            core.PermissionRequested += on_permission
            core.DownloadStarting += on_download
            core.SourceChanged += lambda _s, _e: refresh()
            core.HistoryChanged += lambda _s, _e: refresh()
            core.NavigationCompleted += lambda _s, _e: refresh()
            core.Navigate(args.start_url)
            out.send(type="ready")

        back.Click += lambda _s, _e: view.CoreWebView2 and view.CoreWebView2.GoBack()
        fwd.Click += lambda _s, _e: view.CoreWebView2 and view.CoreWebView2.GoForward()
        add.Click += lambda _s, _e: do_add()
        view.CoreWebView2InitializationCompleted += on_ready

        def on_command(cmd: str) -> None:
            if cmd == "focus":
                if form.WindowState == WinForms.FormWindowState.Minimized:
                    form.WindowState = WinForms.FormWindowState.Normal
                form.Activate()
            elif cmd == "add":
                do_add()
            elif cmd == "close":
                form.Close()

        def read_stdin() -> None:
            for line in sys.stdin:
                cmd = line.strip()
                if cmd not in ("focus", "add", "close"):
                    continue
                with contextlib.suppress(Exception):
                    form.BeginInvoke(Action(lambda c=cmd: on_command(c)))
                if cmd == "close":
                    return
            # The app went away (stdin closed): close too.
            with contextlib.suppress(Exception):
                form.BeginInvoke(Action(form.Close))

        def on_shown(_s: object, _e: object) -> None:
            threading.Thread(target=read_stdin, name="lichess-window-stdin", daemon=True).start()
            view.EnsureCoreWebView2Async(None)

        def on_closed(_s: object, _e: object) -> None:
            """Dispose the control and wait for its browser process, so the profile folder can be deleted."""
            pid = None
            with contextlib.suppress(Exception):
                pid = int(view.CoreWebView2.BrowserProcessId)
            with contextlib.suppress(Exception):
                view.Dispose()
            if pid:
                with contextlib.suppress(Exception):
                    Process.GetProcessById(pid).WaitForExit(5000)

        form.Shown += on_shown
        form.FormClosed += on_closed
        WinForms.Application.Run(form)

    thread = Thread(ThreadStart(build_and_run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    while thread.IsAlive:
        thread.Join(250)
    return result["code"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
