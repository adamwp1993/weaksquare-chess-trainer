"""Small desktop integrations: open a folder in Explorer, pick a file, read the system theme."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


class Desktop:
    def __init__(self, title: str = "") -> None:
        self._window: Any = None
        self._title = title

    def attach(self, window: Any) -> None:
        self._window = window

    def open_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:  # pragma: no cover
            raise OSError("opening folders is only supported on Windows")

    def open_in_browser(self, url: str) -> None:
        """FR-6.1a: the default system browser, never the app window (password managers and 2FA work)."""
        import webbrowser

        if not url.startswith("https://"):
            raise ValueError("only https URLs are opened in the browser")
        webbrowser.open(url, new=2)

    def bring_to_front(self) -> None:
        """After the sign-in callback, bring the app back in front of the browser (FR-6.1a).
        Windows refuses a plain SetForegroundWindow from a background app, so the window is made
        topmost for a moment as well."""
        import contextlib

        from weaksquare.adapters.instance_lock import bring_existing_to_front

        window = self._window
        if window is not None:
            with contextlib.suppress(Exception):
                window.restore()
                window.on_top = True
                window.on_top = False
        if self._title:
            bring_existing_to_front(self._title)

    def choose_puzzle_file(self) -> str | None:
        """Native Open dialog for a Lichess puzzle export. None if cancelled."""
        if self._window is None:
            return None
        chosen = self._window.create_file_dialog(
            10,  # webview.FileDialog.OPEN
            file_types=("Lichess puzzle export (*.zst;*.csv)", "All files (*.*)"),
        )
        return str(chosen[0]) if chosen else None

    def choose_engine_file(self) -> str | None:
        """Native Open dialog for a UCI engine's .exe (FR-7.5 advanced setting). None if cancelled."""
        if self._window is None:
            return None
        chosen = self._window.create_file_dialog(
            10,  # webview.FileDialog.OPEN
            file_types=("Chess engine (*.exe)", "All files (*.*)"),
        )
        return str(chosen[0]) if chosen else None


def system_prefers_dark() -> bool:
    """The Windows app theme (Settings → Personalization → Colors → app mode). False if unknown."""
    if sys.platform != "win32":  # pragma: no cover - v1.1 adds the macOS and Linux equivalents
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        return False
    return value == 0


APP_USER_MODEL_ID = "WeakSquare.ChessTrainer"


def set_app_user_model_id() -> None:
    """NFR-8a: give the process its own taskbar identity, so the taskbar shows the window's icon
    instead of grouping it under python.exe. Call before the window is created."""
    if sys.platform != "win32":  # pragma: no cover
        return
    import contextlib
    import ctypes

    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)  # type: ignore[attr-defined]


def set_window_icon(title: str, ico: Path) -> bool:
    """NFR-8a: pywebview's `icon` only works on GTK and Qt, so on Windows send WM_SETICON (large and
    small) to the window with this title. Returns False if the window or icon couldn't be found."""
    if sys.platform != "win32" or not ico.is_file():  # pragma: no cover - v1.1 handles other systems
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.FindWindowW.restype = wintypes.HWND
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]  # fmt: skip
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    image_icon, lr_loadfromfile, wm_seticon = 1, 0x10, 0x80
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    sizes = {1: (user32.GetSystemMetrics(11), user32.GetSystemMetrics(12)),  # ICON_BIG: SM_CXICON, SM_CYICON
             0: (user32.GetSystemMetrics(49), user32.GetSystemMetrics(50))}  # ICON_SMALL: SM_CXSMICON…  # fmt: skip
    ok = True
    for which, (cx, cy) in sizes.items():
        hicon = user32.LoadImageW(None, str(ico), image_icon, cx, cy, lr_loadfromfile)
        if not hicon:
            ok = False
            continue
        user32.SendMessageW(hwnd, wm_seticon, which, hicon)
    return ok


def show_fatal(title: str, message: str) -> None:
    """A blocking error box for failures before the window exists, plus stderr for console runs.

    WEAKSQUARE_NO_DIALOGS=1 (set by tests) skips the box.
    """
    print(f"{title}: {message}", file=sys.stderr)
    if sys.platform == "win32" and not os.environ.get("WEAKSQUARE_NO_DIALOGS"):
        import ctypes

        mb_iconerror = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, title, mb_iconerror)  # type: ignore[attr-defined]
