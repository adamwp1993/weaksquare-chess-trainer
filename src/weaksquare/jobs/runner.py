"""Background jobs: IDs, progress events and cancellation (ARCHITECTURE §3 decision 7).

A job is a function `fn(progress, token)`. It reports progress with `progress(fraction, message)`
(fraction in 0..1, or None when unknown) and checks `token.raise_if_cancelled()` at safe points.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

JobState = Literal["running", "done", "failed", "cancelled"]
ProgressFn = Callable[[float | None, str], None]


class JobCancelled(Exception):
    """Raised inside a job when its token is cancelled."""


class JobFailed(Exception):
    """A job failure with a user-facing message and a stable error code."""

    def __init__(self, code: str, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise JobCancelled()


@dataclass(frozen=True)
class JobStatus:
    id: str
    kind: str
    state: JobState
    progress: float | None
    message: str
    error_code: str | None = None


class JobEvents(Protocol):
    def job_changed(self, status: JobStatus) -> None: ...


class JobRunner:
    PROGRESS_INTERVAL_S = 0.1

    def __init__(self, events: JobEvents | None = None) -> None:
        self._events = events
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._jobs: dict[str, JobStatus] = {}
        self._tokens: dict[str, CancelToken] = {}
        self._threads: dict[str, threading.Thread] = {}

    def set_events(self, events: JobEvents) -> None:
        self._events = events

    def _set(self, job_id: str, **changes: Any) -> JobStatus:
        with self._lock:
            status = replace(self._jobs[job_id], **changes)
            self._jobs[job_id] = status
        if self._events is not None:
            try:
                self._events.job_changed(status)
            except Exception:  # an event sink must never break a job
                log.exception("job event delivery failed")
        return status

    def submit(self, kind: str, fn: Callable[[ProgressFn, CancelToken], Any]) -> str:
        job_id = f"job-{next(self._ids)}"
        token = CancelToken()
        with self._lock:
            self._jobs[job_id] = JobStatus(job_id, kind, "running", 0.0, "Starting…")
            self._tokens[job_id] = token
        last = [0.0]

        def progress(fraction: float | None, message: str) -> None:
            now = time.monotonic()
            if now - last[0] >= self.PROGRESS_INTERVAL_S:
                last[0] = now
                self._set(job_id, progress=fraction, message=message)

        def run() -> None:
            try:
                fn(progress, token)
            except JobCancelled:
                self._set(job_id, state="cancelled", message="Cancelled")
                log.info("%s (%s) cancelled", job_id, kind)
            except JobFailed as e:
                self._set(job_id, state="failed", message=e.message, error_code=e.code)
                log.warning("%s (%s) failed: %s", job_id, kind, e.code)
            except Exception:
                log.exception("%s (%s) crashed", job_id, kind)
                self._set(job_id, state="failed", message="Something went wrong. See the log.", error_code="internal")
            else:
                self._set(job_id, state="done", progress=1.0, message="Done")

        thread = threading.Thread(target=run, name=f"{kind}-{job_id}", daemon=True)
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return job_id

    def status(self, job_id: str) -> JobStatus | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self, kind: str | None = None) -> list[JobStatus]:
        with self._lock:
            return [s for s in self._jobs.values() if s.state == "running" and (kind is None or s.kind == kind)]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(job_id)
            running = job_id in self._jobs and self._jobs[job_id].state == "running"
        if token is None or not running:
            return False
        token.cancel()
        return True

    def wait(self, job_id: str, timeout: float | None = None) -> JobStatus | None:
        with self._lock:
            thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)
        return self.status(job_id)

    def cancel_all(self, timeout: float = 10.0) -> None:
        """Cancel every running job and wait for each to stop (NFR-6)."""
        with self._lock:
            tokens = list(self._tokens.values())
            threads = list(self._threads.values())
        for t in tokens:
            t.cancel()
        deadline = time.monotonic() + timeout
        for th in threads:
            th.join(max(0.0, deadline - time.monotonic()))
