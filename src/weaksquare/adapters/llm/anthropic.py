"""Anthropic's Messages API over `adapters/http.py` (v0.7, FR-8.1).

- `generate`: `POST /v1/messages` with `max_tokens` (FR-8.14), `output_config.format` (a JSON schema:
  structured output, FR-8.3) and `output_config.effort` (the reasoning setting, FR-8.15). Never retried.
- `test_key`: `GET /v1/models/{model}` (or `/v1/models`), which is free (FR-1.4).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from weaksquare.adapters.http import HttpClient, HttpError
from weaksquare.adapters.llm import as_int, llm_error
from weaksquare.core.llm.provider import LLMError, LLMRequest, LLMResponse, ResponseStatus

BASE = "https://api.anthropic.com/v1"
API_VERSION = "2026-10-21"  # the newest; the request sends no sampling parameters, documents or citations


def _headers(key: str) -> dict[str, str]:
    return {"x-api-key": key, "anthropic-version": API_VERSION}


def build_body(request: LLMRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": request.system,
        "messages": [{"role": "user", "content": request.user}],
        "output_config": {
            "effort": request.reasoning,
            "format": {"type": "json_schema", "schema": request.schema},
        },
    }


def parse_response(body: Any) -> LLMResponse:
    if not isinstance(body, dict):
        raise LLMError("server")
    raw_usage = body.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    text = "".join(
        b["text"]
        for b in body.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    )
    stop = body.get("stop_reason")
    status: ResponseStatus = "refused" if stop == "refusal" else "truncated" if stop == "max_tokens" else "ok"
    return LLMResponse(text, as_int(usage.get("input_tokens")), as_int(usage.get("output_tokens")), status)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def test_key(self, key: str, model: str | None) -> None:
        url = f"{BASE}/models/{quote(model, safe='')}" if model else f"{BASE}/models"
        try:
            self._http.get_json(url, headers=_headers(key), params=None if model else {"limit": 1}, retry=False)
        except HttpError as e:
            raise llm_error(e) from None

    def generate(self, key: str, request: LLMRequest) -> LLMResponse:
        try:
            body = self._http.post_json(
                f"{BASE}/messages", build_body(request), headers=_headers(key), retry=False, timeout=request.timeout_s
            )
        except HttpError as e:
            raise llm_error(e) from None
        return parse_response(body)
