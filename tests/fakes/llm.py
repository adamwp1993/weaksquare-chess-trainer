"""A scriptable fake `LLMProvider` (v0.7). Tests queue answers, usage and errors; it records every request
so tests can check that `max_tokens` was set and what the prompt contained. Never touches the network."""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from weaksquare.core.llm.provider import LLMError, LLMRequest, LLMResponse

FAKE_ANTHROPIC_KEY = "sk-ant-FAKE" + "key0" * 6
FAKE_OPENAI_KEY = "sk-FAKE" + "key0" * 6


def explain_json(steps: int = 2, **overrides: Any) -> str:
    """A well-formed Explain answer for a puzzle with `steps` player moves."""
    body: dict[str, Any] = {
        "summary": "The knight forks king and queen.",
        "steps": [
            {"ply": i, "text": f"Step {i}.", "annotations": [{"type": "circle", "square": "e4", "color": "green"}]}
            for i in range(steps)
        ],
        "key_ideas": ["fork"],
    }
    body.update(overrides)
    return json.dumps(body)


@dataclass
class FakeLLMProvider:
    name: str = "anthropic"
    input_tokens: int = 1200
    output_tokens: int = 400
    default_text: str = field(default_factory=explain_json)
    answers: deque[LLMResponse | LLMError] = field(default_factory=deque)
    requests: list[LLMRequest] = field(default_factory=list)
    keys_seen: list[str] = field(default_factory=list)
    test_error: LLMError | None = None
    known_models: set[str] | None = None  # None: every model exists
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def queue(self, item: LLMResponse | LLMError | str) -> None:
        if isinstance(item, str):
            item = LLMResponse(item, self.input_tokens, self.output_tokens)
        self.answers.append(item)

    def test_key(self, key: str, model: str | None) -> None:
        self.keys_seen.append(key)
        if self.test_error:
            raise self.test_error
        if model and self.known_models is not None and model not in self.known_models:
            raise LLMError("bad_model", 404)

    def generate(self, key: str, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.keys_seen.append(key)
            self.requests.append(request)
            item = self.answers.popleft() if self.answers else None
        if isinstance(item, LLMError):
            raise item
        if item is None:
            return LLMResponse(self.default_text, self.input_tokens, self.output_tokens)
        return item


def fake_providers() -> dict[str, FakeLLMProvider]:
    return {"anthropic": FakeLLMProvider("anthropic"), "openai": FakeLLMProvider("openai")}
