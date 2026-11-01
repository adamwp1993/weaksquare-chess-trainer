"""Python -> JS push events (job progress). Delivered with `window.evaluate_js`.

The front end registers `window.__ws_events(event)`; until it has, events are dropped, and the UI
can always poll `get_job`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from weaksquare.bridge.dto import Job
from weaksquare.bridge.errors import to_json
from weaksquare.jobs.runner import JobStatus

log = logging.getLogger(__name__)


class JsWindow(Protocol):
    def evaluate_js(self, script: str) -> Any: ...


def job_dto(status: JobStatus) -> Job:
    return Job(status.id, status.kind, status.state, status.progress, status.message, status.error_code)


class EventSink:
    def __init__(self) -> None:
        self._window: JsWindow | None = None

    def attach(self, window: JsWindow) -> None:
        self._window = window

    def detach(self) -> None:
        """Stop delivering events (the window is closing; its WebView2 is being disposed)."""
        self._window = None

    def emit(self, name: str, payload: Any) -> None:
        if self._window is None:
            return
        data = json.dumps({"name": name, "payload": to_json(payload)})
        try:
            self._window.evaluate_js(f"window.__ws_events && window.__ws_events({data})")
        except Exception:
            log.debug("event %s not delivered", name, exc_info=True)

    def job_changed(self, status: JobStatus) -> None:
        self.emit("job", job_dto(status))
