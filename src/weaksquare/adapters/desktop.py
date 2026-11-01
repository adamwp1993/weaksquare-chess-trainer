"""Small desktop integrations: open a folder in Explorer, pick a file."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


class Desktop:
    def __init__(self) -> None:
        self._window: Any = None

    def attach(self, window: Any) -> None:
        self._window = window

    def open_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:  # pragma: no cover
            raise OSError("opening folders is only supported on Windows")


def show_fatal(title: str, message: str) -> None:
    """A blocking error box for failures before the window exists, plus stderr for console runs.

    WEAKSQUARE_NO_DIALOGS=1 (set by tests) skips the box.
    """
    print(f"{title}: {message}", file=sys.stderr)
    if sys.platform == "win32" and not os.environ.get("WEAKSQUARE_NO_DIALOGS"):
        import ctypes

        mb_iconerror = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, title, mb_iconerror)  # type: ignore[attr-defined]
