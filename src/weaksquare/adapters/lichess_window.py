"""The app's end of the Lichess window (FR-13.3, 13.4): start `python -m weaksquare.lichess_window`, read what it says,
re-check every study ID, and close it with the app.

The window is a separate process with no bridge (see `weaksquare/lichess_window.py`). Everything it sends is treated as
untrusted: each ID in an `add` is checked on its own against the study-ID rule (`core.study_links.ref_from_ids`), and
anything that fails is dropped. It never sends an address, only study and chapter IDs, and the scheme and host of pages it refused.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import IO, Any

from weaksquare.core.study_links import StudyRef, ref_from_ids

log = logging.getLogger(__name__)

_MAX_LINE = 2000
_CREATE_NO_WINDOW = 0x08000000

Popen = Callable[..., Any]


class LichessWindow:
    """At most one Lichess window. `on_add` gets each study the user adds; `on_page` the study on screen (or None);
    `on_closed` runs when the window goes away. Callbacks run on the reader thread."""

    def __init__(
        self,
        on_add: Callable[[StudyRef], None],
        on_page: Callable[[StudyRef | None], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        *,
        python: str = sys.executable,
        popen: Popen = subprocess.Popen,
        extra_args: tuple[str, ...] = (),
    ) -> None:
        self._on_add = on_add
        self._on_page = on_page
        self._on_closed = on_closed
        self._python = python
        self._popen = popen
        self._extra_args = extra_args
        self._lock = threading.Lock()
        self._proc: Any = None

    def is_open(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def open(self) -> bool:
        """Open the window, or bring it forward if it's already open. True if a new window was started."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._send("focus")
                return False
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("WEBVIEW2_")}
            flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._proc = self._popen(
                [self._python, "-m", "weaksquare.lichess_window", *self._extra_args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
                creationflags=flags,
            )
            proc = self._proc
        threading.Thread(target=self._read, args=(proc,), name="lichess-window-reader", daemon=True).start()
        log.info("Lichess window opened")
        return True

    def close(self, timeout: float = 10) -> None:
        """Close the window (on app shutdown, or from the app)."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            self._send("close")
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            log.warning("Lichess window didn't close; ending it")
            with contextlib.suppress(Exception):
                proc.kill()

    def _send(self, cmd: str) -> None:
        stdin: IO[str] | None = getattr(self._proc, "stdin", None)
        if stdin is None:
            return
        with contextlib.suppress(OSError, ValueError):
            stdin.write(cmd + "\n")
            stdin.flush()

    def _read(self, proc: Any) -> None:
        try:
            for line in proc.stdout:
                if len(line) > _MAX_LINE:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self._handle(msg)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
            log.info("Lichess window closed")
            if self._on_closed is not None:
                with contextlib.suppress(Exception):
                    self._on_closed()

    def _handle(self, msg: dict[str, object]) -> None:
        kind = msg.get("type")
        if kind == "add":
            ref = ref_from_ids(msg.get("study"), msg.get("chapter"))
            if ref is None:
                log.warning("Lichess window sent an add that isn't a study ID; ignored")
                return
            self._on_add(ref)
        elif kind == "page" and self._on_page is not None:
            self._on_page(ref_from_ids(msg.get("study"), msg.get("chapter")))
        elif kind == "blocked":
            host = msg.get("host")
            log.info(
                "Lichess window refused a page (%s, %s)%s",
                str(msg.get("scheme"))[:16],
                str(host)[:253] if host else "no host",
                "; opened in the browser" if msg.get("opened") else "",
            )
