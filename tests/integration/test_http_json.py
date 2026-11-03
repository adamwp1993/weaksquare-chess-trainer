"""adapters/http.py JSON and ndjson calls (v0.3): auth header per request, 401/429 handling,
no secrets in errors (SR-7), ndjson streaming."""

from __future__ import annotations

import json

import httpx
import pytest

from weaksquare.adapters.http import HttpClient, HttpError, RateLimited, Unauthorized

FAKE = "lip_" + "FAKE" * 4


def client(handler, **kw) -> HttpClient:  # type: ignore[no-untyped-def]
    return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_token_goes_only_in_the_authorization_header() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    c = client(handler)
    assert c.get_json("https://lichess.org/api/account", token=FAKE) == {"ok": True}
    assert c.get_json("https://lichess.org/api/other") == {"ok": True}
    assert seen[0].headers["authorization"] == f"Bearer {FAKE}"
    assert FAKE not in str(seen[0].url)
    assert "authorization" not in seen[1].headers  # never a client default


def test_401_is_unauthorized_and_not_retried() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "No such token"})

    with pytest.raises(Unauthorized) as e:
        client(handler).get_json("https://lichess.org/api/account", token=FAKE)
    assert calls == 1
    assert FAKE not in str(e.value)


def test_429_is_not_retried_and_carries_retry_after() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "90"})

    with pytest.raises(RateLimited) as e:
        client(handler).post_json("https://lichess.org/api/puzzle/batch/mix", {"solutions": []}, token=FAKE)
    assert calls == 1
    assert e.value.retry_after_s == 90


def test_5xx_is_retried_then_succeeds() -> None:
    answers = iter([httpx.Response(502), httpx.Response(200, json={"rounds": []})])
    assert client(lambda req: next(answers)).post_json("https://x.test/a", {}) == {"rounds": []}


def test_token_exchange_form_is_not_retried() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(HttpError):
        client(handler).post_form("https://lichess.org/api/token", {"grant_type": "authorization_code"})
    assert calls == 1  # an authorization code is single-use


def test_network_error_message_has_no_secrets() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    with pytest.raises(HttpError) as e:
        client(handler, retries=1).get_json("https://lichess.org/api/account", token=FAKE)
    assert FAKE not in str(e.value)
    assert "Bearer" not in str(e.value)


def test_delete_with_empty_body() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        return httpx.Response(204)

    client(handler).delete("https://lichess.org/api/token", token=FAKE)


def test_stream_ndjson_yields_objects_and_skips_junk() -> None:
    lines = [json.dumps({"date": 2, "win": True}), "", "not json", json.dumps({"date": 1, "win": False})]

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["since"] == "5"
        return httpx.Response(200, content="\n".join(lines).encode())

    got = list(
        client(handler).stream_ndjson("https://lichess.org/api/puzzle/activity", token=FAKE, params={"since": 5})
    )
    assert got == [{"date": 2, "win": True}, {"date": 1, "win": False}]


def test_stream_ndjson_401() -> None:
    with pytest.raises(Unauthorized):
        list(client(lambda req: httpx.Response(401)).stream_ndjson("https://lichess.org/api/puzzle/activity"))


def test_per_request_headers_and_error_codes() -> None:
    """v0.7: extra headers (Anthropic's x-api-key) go on that request only, and a JSON error keeps just the
    API's short code, never its message text (SR-7)."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/fail":
            return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "echo sk-ant-x"}})
        return httpx.Response(200, json={})

    c = client(handler)
    c.post_json("https://api.example/ok", {}, headers={"x-api-key": "sk-ant-FAKEkey"}, retry=False)
    c.get_json("https://api.example/ok")
    assert seen[0].headers["x-api-key"] == "sk-ant-FAKEkey" and "x-api-key" not in seen[1].headers
    with pytest.raises(HttpError) as e:
        c.post_json("https://api.example/fail", {}, retry=False)
    assert e.value.error_code == "invalid_request_error" and "echo" not in str(e.value)


def test_error_codes_that_dont_look_like_codes_are_dropped() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "Has Spaces and sk-ant-secret", "type": 5}})

    with pytest.raises(HttpError) as e:
        client(handler).get_json("https://api.example/x", retry=False)
    assert e.value.error_code is None


def test_timeouts_are_flagged() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(HttpError) as e:
        client(handler).post_json("https://api.example/x", {}, retry=False, timeout=1.0)
    assert e.value.timeout and e.value.status is None
