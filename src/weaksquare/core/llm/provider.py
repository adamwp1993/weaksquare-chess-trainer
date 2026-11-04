"""The `LLMProvider` protocol (ARCHITECTURE §4) and the types every provider shares (FR-8.1, 8.8).

Adapters (`adapters/llm/anthropic.py`, `openai.py`) implement it over `adapters/http.py`; tests use
`tests/fakes/llm.py`. A provider never sees settings, the price table or the budget: those are checked
by `services/llm_usage.py` before it is called, and every call goes through there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from weaksquare.core.llm.defaults import Reasoning

ErrorKind = Literal["bad_key", "quota", "rate_limited", "network", "timeout", "bad_model", "bad_request", "server"]
ResponseStatus = Literal["ok", "truncated", "refused"]

# Readable messages (FR-8.8). The provider's own error text is never shown or logged (SR-7: it can echo
# request details); only the kind is.
ERROR_MESSAGES: dict[ErrorKind, str] = {
    "bad_key": "The API key was rejected. Check it in Settings → AI, or create a new one in the provider's console.",
    "quota": "Your provider account is out of credit or over its spending limit. Check its billing page.",
    "rate_limited": "The provider is busy or rate-limiting you. Wait a minute and try again.",
    "network": "Couldn't reach the provider. Check your internet connection and try again.",
    "timeout": "The provider took too long to answer. Try again.",
    "bad_model": "The provider doesn't know that model, or your key can't use it. Pick another in Settings → AI.",
    "bad_request": "The provider refused the request. Try another model; the log has the details.",
    "server": "The provider had a problem on its side. Try again in a moment.",
}
RETRYABLE: frozenset[ErrorKind] = frozenset({"rate_limited", "network", "timeout", "server"})


class LLMError(Exception):
    """A failed provider call. The message is ours (ERROR_MESSAGES), never the provider's text."""

    def __init__(self, kind: ErrorKind, status: int | None = None) -> None:
        super().__init__(ERROR_MESSAGES[kind])
        self.kind = kind
        self.status = status
        self.message = ERROR_MESSAGES[kind]
        self.retryable = kind in RETRYABLE


@dataclass(frozen=True)
class LLMRequest:
    model: str
    system: str
    user: str
    schema_name: str
    schema: dict[str, Any]  # the JSON schema the answer must follow (structured output, FR-8.3)
    max_tokens: int  # always set (FR-8.14)
    reasoning: Reasoning  # FR-8.15
    timeout_s: float = 60.0


@dataclass(frozen=True)
class LLMResponse:
    """What came back. `status` is 'truncated' when max_tokens cut it short and 'refused' when the model
    declined: both are billed, so the usage is recorded either way."""

    text: str
    input_tokens: int
    output_tokens: int
    status: ResponseStatus = "ok"


class LLMProvider(Protocol):
    name: str  # 'anthropic' / 'openai'

    def test_key(self, key: str, model: str | None) -> None:
        """A free check (the provider's model lookup): returns, or raises LLMError."""
        ...

    def generate(self, key: str, request: LLMRequest) -> LLMResponse:
        """One request, never retried (a retry after a timeout could be billed twice). Raises LLMError."""
        ...
