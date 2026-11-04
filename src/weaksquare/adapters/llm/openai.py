"""OpenAI's Responses API over `adapters/http.py` (v0.7, FR-8.1).

- `generate`: `POST /v1/responses` with `instructions`, `input`, `max_output_tokens` (FR-8.14),
  `reasoning.effort` (FR-8.15) and `text.format` as a strict JSON schema (structured output, FR-8.3).
  `store: false`: the request isn't kept on OpenAI's side for later retrieval. Never retried.
- `test_key`: `GET /v1/models/{model}` (or `/v1/models`), which is free (FR-1.4).

Shapes from the openai-python SDK's types (`responses/response.py`, `response_usage.py`,
`shared_params/reasoning.py`), checked at v0.7. Reasoning tokens are part of `output_tokens`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from weaksquare.adapters.http import HttpClient, HttpError
from weaksquare.adapters.llm import as_int, llm_error
from weaksquare.core.llm.provider import LLMError, LLMRequest, LLMResponse, ResponseStatus

BASE = "https://api.openai.com/v1"


def build_body(request: LLMRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "instructions": request.system,
        "input": request.user,
        "max_output_tokens": request.max_tokens,
        "reasoning": {"effort": request.reasoning},
        "text": {
            "format": {"type": "json_schema", "name": request.schema_name, "schema": request.schema, "strict": True}
        },
        "store": False,
    }


def parse_response(body: Any) -> LLMResponse:
    if not isinstance(body, dict):
        raise LLMError("server")
    raw_usage = body.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    text_parts: list[str] = []
    refused = False
    for item in body.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for c in item.get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "output_text" and isinstance(c.get("text"), str):
                text_parts.append(c["text"])
            elif c.get("type") == "refusal":
                refused = True
    raw_details = body.get("incomplete_details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    status: ResponseStatus
    if refused or details.get("reason") == "content_filter":
        status = "refused"
    elif body.get("status") == "incomplete":
        status = "truncated"
    else:
        status = "ok"
    return LLMResponse("".join(text_parts), as_int(usage.get("input_tokens")), as_int(usage.get("output_tokens")),
                       status)  # fmt: skip


class OpenAIProvider:
    name = "openai"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def test_key(self, key: str, model: str | None) -> None:
        url = f"{BASE}/models/{quote(model, safe='')}" if model else f"{BASE}/models"
        try:
            self._http.get_json(url, token=key, retry=False)
        except HttpError as e:
            raise llm_error(e) from None

    def generate(self, key: str, request: LLMRequest) -> LLMResponse:
        try:
            body = self._http.post_json(
                f"{BASE}/responses", build_body(request), token=key, retry=False, timeout=request.timeout_s
            )
        except HttpError as e:
            raise llm_error(e) from None
        return parse_response(body)
