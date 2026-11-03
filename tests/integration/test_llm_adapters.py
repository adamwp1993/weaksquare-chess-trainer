"""The Anthropic and OpenAI adapters over a mock transport (v0.7): request shapes (max_tokens always set,
structured output, reasoning effort), usage parsing, truncated/refused answers, and each error kind
(FR-8.8). No network; keys are obvious fakes and must never appear in URLs or error messages (SR-7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FAKE_OPENAI_KEY
from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.llm.anthropic import AnthropicProvider
from weaksquare.adapters.llm.openai import OpenAIProvider
from weaksquare.core.llm.provider import LLMError, LLMRequest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "llm"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
          "additionalProperties": False}  # fmt: skip
REQ = LLMRequest("model-x", "system text", "user text", "explain", SCHEMA, 1500, "low", timeout_s=7.0)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Recorder:
    def __init__(self, status: int = 200, body: Any = None, exc: Exception | None = None) -> None:
        self.status, self.body, self.exc = status, body, exc
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, json=self.body)

    @property
    def sent(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


def client(rec: Recorder) -> HttpClient:
    return HttpClient(transport=httpx.MockTransport(rec), sleep=lambda s: None)


# ---- Anthropic -----------------------------------------------------------------------------------------


def test_anthropic_request_shape_and_usage() -> None:
    rec = Recorder(body=fixture("anthropic_messages.json"))
    resp = AnthropicProvider(client(rec)).generate(FAKE_ANTHROPIC_KEY, REQ)
    req = rec.requests[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == FAKE_ANTHROPIC_KEY and req.headers["anthropic-version"] == "2026-10-21"
    assert "authorization" not in req.headers and FAKE_ANTHROPIC_KEY not in str(req.url)
    body = rec.sent
    assert body["max_tokens"] == 1500  # FR-8.14
    assert body["system"] == "system text" and body["messages"] == [{"role": "user", "content": "user text"}]
    assert body["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert "thinking" not in body and "temperature" not in body
    assert (resp.input_tokens, resp.output_tokens, resp.status) == (1834, 412, "ok")
    assert json.loads(resp.text)["key_ideas"] == ["fork"]
    assert len(rec.requests) == 1


@pytest.mark.parametrize(("stop", "status"), [("max_tokens", "truncated"), ("refusal", "refused")])
def test_anthropic_cut_short_and_refused(stop: str, status: str) -> None:
    body = fixture("anthropic_messages.json") | {"stop_reason": stop}
    resp = AnthropicProvider(client(Recorder(body=body))).generate(FAKE_ANTHROPIC_KEY, REQ)
    assert resp.status == status and resp.input_tokens == 1834  # still billed: usage kept


def test_anthropic_test_key_is_the_free_model_lookup() -> None:
    rec = Recorder(body={"id": "player_model"})
    AnthropicProvider(client(rec)).test_key(FAKE_ANTHROPIC_KEY, "claude/odd name")
    assert rec.requests[0].method == "GET"
    assert rec.requests[0].url.raw_path == b"/v1/models/claude%2Fodd%20name"  # quoted: can't escape the path
    AnthropicProvider(client(rec)).test_key(FAKE_ANTHROPIC_KEY, None)
    assert rec.requests[1].url.path == "/v1/models"


# ---- OpenAI --------------------------------------------------------------------------------------------


def test_openai_request_shape_and_usage() -> None:
    rec = Recorder(body=fixture("openai_responses.json"))
    resp = OpenAIProvider(client(rec)).generate(FAKE_OPENAI_KEY, REQ)
    req = rec.requests[0]
    assert str(req.url) == "https://api.openai.com/v1/responses"
    assert req.headers["authorization"] == f"Bearer {FAKE_OPENAI_KEY}"
    body = rec.sent
    assert body["max_output_tokens"] == 1500  # FR-8.14
    assert body["instructions"] == "system text" and body["input"] == "user text"
    assert body["reasoning"] == {"effort": "low"} and body["store"] is False
    assert body["text"]["format"] == {"type": "json_schema", "name": "explain", "schema": SCHEMA, "strict": True}
    assert (resp.input_tokens, resp.output_tokens, resp.status) == (1790, 455, "ok")  # reasoning is in output
    assert json.loads(resp.text)["summary"].startswith("The knight")


def test_openai_incomplete_and_refusal() -> None:
    inc = fixture("openai_responses.json") | {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    assert OpenAIProvider(client(Recorder(body=inc))).generate(FAKE_OPENAI_KEY, REQ).status == "truncated"
    refusal = fixture("openai_responses.json")
    refusal["output"][1]["content"] = [{"type": "refusal", "refusal": "no"}]
    resp = OpenAIProvider(client(Recorder(body=refusal))).generate(FAKE_OPENAI_KEY, REQ)
    assert resp.status == "refused" and resp.text == ""


# ---- errors (both providers) --------------------------------------------------------------------------

ERRORS = [
    (401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}, "bad_key"),
    (403, {"error": {"type": "permission_error"}}, "bad_key"),
    (404, {"error": {"type": "not_found_error"}}, "bad_model"),
    (429, {"error": {"type": "rate_limit_error"}}, "rate_limited"),
    (429, {"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}, "quota"),
    (400, {"error": {"type": "invalid_request_error"}}, "bad_request"),
    (402, {"error": {"type": "billing_error"}}, "quota"),
    (500, {"error": {"type": "api_error"}}, "server"),
    (529, {"error": {"type": "overloaded_error"}}, "rate_limited"),
]


@pytest.mark.parametrize("provider", [AnthropicProvider, OpenAIProvider])
@pytest.mark.parametrize(("status", "body", "kind"), ERRORS)
def test_errors_map_to_readable_kinds_without_retrying(provider: Any, status: int, body: Any, kind: str) -> None:
    rec = Recorder(status, body)
    key = FAKE_ANTHROPIC_KEY if provider is AnthropicProvider else FAKE_OPENAI_KEY
    with pytest.raises(LLMError) as e:
        provider(client(rec)).generate(key, REQ)
    assert e.value.kind == kind
    assert len(rec.requests) == 1  # never retried: a retry could be billed twice
    assert key not in e.value.message and "invalid x-api-key" not in e.value.message  # ours, not theirs


@pytest.mark.parametrize("provider", [AnthropicProvider, OpenAIProvider])
def test_network_and_timeout(provider: Any) -> None:
    for exc, kind in [(httpx.ConnectError("boom"), "network"), (httpx.ReadTimeout("slow"), "timeout")]:
        rec = Recorder(exc=exc)
        with pytest.raises(LLMError) as e:
            provider(client(rec)).generate(FAKE_ANTHROPIC_KEY, REQ)
        assert e.value.kind == kind and e.value.retryable
        assert len(rec.requests) == 1


@pytest.mark.parametrize("provider", [AnthropicProvider, OpenAIProvider])
def test_a_body_that_isnt_an_object_is_a_server_error(provider: Any) -> None:
    with pytest.raises(LLMError) as e:
        provider(client(Recorder(body=[1, 2]))).generate(FAKE_ANTHROPIC_KEY, REQ)
    assert e.value.kind == "server"


@pytest.mark.parametrize("provider", [AnthropicProvider, OpenAIProvider])
def test_odd_usage_values_become_zero(provider: Any) -> None:
    name = "anthropic_messages.json" if provider is AnthropicProvider else "openai_responses.json"
    body = fixture(name) | {"usage": {"input_tokens": "lots", "output_tokens": -3}}
    resp = provider(client(Recorder(body=body))).generate(FAKE_ANTHROPIC_KEY, REQ)
    assert (resp.input_tokens, resp.output_tokens) == (0, 0)
