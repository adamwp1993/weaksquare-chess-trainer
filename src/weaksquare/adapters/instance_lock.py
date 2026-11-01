"""Single-instance lock (NFR-1): a byte-range lock on a file in the data folder.

The OS drops the lock if the process dies, so a crash never leaves a stale lock behind.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)


class InstanceLock:
    def __init__(self, handle: IO[bytes]) -> None:
        self._handle = handle

    def release(self) -> None:
        if self._handle.closed:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()


def acquire(lock_file: Path) -> InstanceLock | None:
    """Return the lock, or None if another copy of the app holds it."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
    handle = os.fdopen(fd, "r+b")  # held open for the life of the app
    try:
        _lock(handle)
    except OSError:
        handle.close()
        return None
    return InstanceLock(handle)


if sys.platform == "win32":
    import msvcrt

    def _lock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        with contextlib.suppress(OSError):
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover - the app targets Windows only
    import fcntl

    def _lock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


PID_OFFSET = 16  # byte 0 is the locked byte; other processes can read from here


def write_pid(lock: InstanceLock) -> None:
    """Record the app's real PID (the venv launcher spawns a child process, so the launcher's PID
    isn't the app's). The smoke harness reads it to close the right window."""
    with contextlib.suppress(OSError):
        handle = lock._handle
        handle.seek(0)
        handle.truncate(0)
        handle.write(b" " * PID_OFFSET + str(os.getpid()).encode())
        handle.flush()


def read_pid(lock_file: Path) -> int | None:
    try:
        with open(lock_file, "rb") as f:
            f.seek(PID_OFFSET)
            return int(f.read().strip() or b"0") or None
    except (OSError, ValueError):
        return None


def bring_existing_to_front(window_title: str) -> bool:
    """Bring the running copy's window forward. Returns True if a window was found."""
    if sys.platform != "win32":  # pragma: no cover
        return False
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.FindWindowW(None, window_title)
    if not hwnd:
        log.info("Another copy holds the lock, but its window wasn't found")
        return False
    sw_restore = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    user32.SetForegroundWindow(hwnd)
    return True
