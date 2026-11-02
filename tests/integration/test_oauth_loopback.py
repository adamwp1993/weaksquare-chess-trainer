"""FR-6.2 / SR-4 / SR-9: the loopback listener."""

from __future__ import annotations

import logging
import threading

import httpx
import pytest

from weaksquare.adapters.oauth_loopback import (
    FAIL_MESSAGE,
    OK_MESSAGE,
    LoopbackCancelled,
    LoopbackListener,
    LoopbackTimeout,
)


def _get(url: str) -> httpx.Response:
    with httpx.Client(trust_env=False, timeout=5) as c:
        return c.get(url)


def _wait_in_thread(listener: LoopbackListener) -> tuple[threading.Thread, dict]:
    out: dict = {}

    def run() -> None:
        try:
            out["query"] = listener.wait()
        except Exception as e:
            out["error"] = e

    t = threading.Thread(target=run)
    t.start()
    return t, out


def test_binds_loopback_only_and_accepts_one_callback(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    listener = LoopbackListener(accept=lambda q: q.get("state") == ["s1"])
    uri = listener.start()
    assert uri.startswith("http://127.0.0.1:") and uri.endswith("/callback")
    t, out = _wait_in_thread(listener)

    assert _get(uri.replace("/callback", "/favicon.ico")).status_code == 404  # doesn't consume it
    r = _get(uri + "?code=secretcode123&state=s1")
    assert r.status_code == 200 and OK_MESSAGE in r.text
    t.join(5)
    assert out["query"] == {"code": ["secretcode123"], "state": ["s1"]}
    # Single use: the listener is gone.
    with pytest.raises(httpx.TransportError):
        _get(uri + "?code=again&state=s1")
    # SR-9: nothing on the app's side logs the code (the test's own httpx client may, so it's excluded).
    ours = [r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    assert not any("secretcode123" in m for m in ours)


def test_a_rejected_callback_shows_the_failure_page() -> None:
    listener = LoopbackListener(accept=lambda q: False)
    uri = listener.start()
    t, out = _wait_in_thread(listener)
    r = _get(uri + "?code=x&state=wrong")
    assert FAIL_MESSAGE in r.text
    t.join(5)
    assert out["query"]["state"] == ["wrong"]  # the service decides; the listener is still consumed


def test_timeout_shuts_down() -> None:
    listener = LoopbackListener(timeout_s=0.2)
    uri = listener.start()
    with pytest.raises(LoopbackTimeout):
        listener.wait()
    with pytest.raises(httpx.TransportError):
        _get(uri)


def test_cancel() -> None:
    listener = LoopbackListener()
    listener.start()
    t, out = _wait_in_thread(listener)
    listener.cancel()
    t.join(5)
    assert isinstance(out["error"], LoopbackCancelled)
