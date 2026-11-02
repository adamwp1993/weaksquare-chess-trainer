"""Run a function later on a background thread (sync retries and reconnect checks, v0.3).

Services get this injected so they never sleep or read the time themselves (ARCHITECTURE §3
decision 15); tests use a fake that runs the callbacks when told to.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class TimerScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timers: set[threading.Timer] = set()
        self._closed = False

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None:
        def run() -> None:
            with self._lock:
                self._timers.discard(timer)
                if self._closed:
                    return
            try:
                fn()
            except Exception:
                log.exception("scheduled call failed")

        timer = threading.Timer(delay_s, run)
        timer.daemon = True
        with self._lock:
            if self._closed:
                return
            self._timers.add(timer)
        timer.start()

    def close(self) -> None:
        """Cancel everything still waiting (NFR-6)."""
        with self._lock:
            self._closed = True
            timers, self._timers = self._timers, set()
        for t in timers:
            t.cancel()
