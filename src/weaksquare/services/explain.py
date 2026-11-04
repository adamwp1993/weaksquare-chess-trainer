"""Explain (§9.2, FR-8.1–8.8): step 3 of the stuck ladder, for the puzzle that just ended.

1. **Quote** (FR-8.11): what one Explain would cost, without asking the engine (the prompt's size is
   enough), and whether the guardrails allow it. A cached result is free and always allowed (FR-8.6).
2. **Start:** a job. It gathers the grounded facts with the interactive engine (FR-8.2), sends one request
   through `LlmUsageService.run` (cap, budget, `max_tokens`, usage log), validates the answer against
   the real position (FR-8.4) and caches the validated result by (puzzle, your move path, provider, model).
3. **Result:** the latest explanation for the puzzle on the board.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.chess_rules import start_position
from weaksquare.core.clock import Clock
from weaksquare.core.errors import AppError
from weaksquare.core.explain import (
    SCHEMA,
    SCHEMA_NAME,
    SYSTEM_PROMPT,
    CacheKeyParts,
    ExplainInput,
    Explanation,
    build_prompt,
    validate,
)
from weaksquare.core.llm.cost import Estimate
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn
from weaksquare.services.llm_settings import LlmSettingsService
from weaksquare.services.llm_usage import LlmUsageService, prompt_chars

FEATURE = "explain"
JOB = "explain"
# The quote leaves the engine out; three lines of up to 8 SAN moves and a refutation add about this much.
ENGINE_ALLOWANCE_CHARS = 700


class Sessions(Protocol):
    def explain_facts(self, session_id: int, with_engine: bool = True) -> tuple[ExplainInput, CacheKeyParts]: ...

    def current_puzzle(self, session_id: int) -> str | None: ...


class CacheRepo(Protocol):
    def get(self, key: str) -> Any | None: ...  # CachedResult

    def put(
        self, key: str, provider: str, model: str, response_json: str, input_tokens: int, output_tokens: int,
        created_at: str,
    ) -> None: ...  # fmt: skip


@dataclass(frozen=True)
class ExplainQuote:
    state: str  # 'ok' / 'cached' / a guardrail state ('over_budget', 'over_cap', 'no_model', …)
    message: str | None
    provider: str
    model: str
    estimate: Estimate | None


@dataclass(frozen=True)
class ExplainView:
    puzzle: str
    explanation: Explanation
    provider: str
    model: str
    cost_usd: float  # 0 for a cached result
    cached: bool
    start_fen: str  # where your first move is played: Show me starts here
    solution: tuple[str, ...]  # UCI from start_fen, both sides (puzzle.moves[1:])


def cache_key(parts: CacheKeyParts) -> str:
    return hashlib.sha256(parts.canonical().encode()).hexdigest()


class ExplainService:
    def __init__(
        self,
        sessions: Sessions,
        settings: LlmSettingsService,
        usage: LlmUsageService,
        cache: CacheRepo,
        runner: JobRunner,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._usage = usage
        self._cache = cache
        self._runner = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._results: dict[int, ExplainView] = {}
        self._jobs: dict[int, str] = {}

    def _key(self, parts: CacheKeyParts, provider: str, model: str) -> str:
        return cache_key(CacheKeyParts(parts.puzzle, parts.path, provider, model))

    def quote(self, session_id: int) -> ExplainQuote:
        cfg = self._settings.config()
        inp, parts = self._sessions.explain_facts(session_id, with_engine=False)
        if cfg.configured and cfg.model and self._cache.get(self._key(parts, cfg.provider, cfg.model)) is not None:
            return ExplainQuote("cached", None, cfg.provider, cfg.model, None)
        chars = prompt_chars(SYSTEM_PROMPT, build_prompt(inp), SCHEMA) + ENGINE_ALLOWANCE_CHARS
        q = self._usage.quote(FEATURE, chars, cfg)
        return ExplainQuote(str(q.state), q.message, q.provider, q.model, q.estimate)

    def start(self, session_id: int) -> str:
        """Checks the guardrails now, so a blocked Explain fails at once; then runs as a job."""
        q = self.quote(session_id)
        if q.state not in ("ok", "cached"):
            raise AppError(q.message or "Explain can't run now.", code=q.state)
        with self._lock:
            running = self._jobs.get(session_id)
            status = self._runner.status(running) if running else None
            if status is not None and status.state == "running":
                return running  # type: ignore[return-value]
            job = self._runner.submit(JOB, lambda progress, token: self._run(session_id, progress, token))
            self._jobs[session_id] = job
            return job

    def _run(self, session_id: int, progress: ProgressFn, token: CancelToken) -> str:
        try:
            view = self._explain(session_id, progress)
        except AppError as e:
            raise JobFailed(e.code, e.message, e.retryable) from None
        if self._sessions.current_puzzle(session_id) == view.puzzle:
            with self._lock:
                self._results[session_id] = view
        return "Explained (saved)." if view.cached else f"Explained for ${view.cost_usd:.4f}."

    def _explain(self, session_id: int, progress: ProgressFn) -> ExplainView:
        cfg = self._settings.config()
        progress(None, "Asking Stockfish…")
        inp, parts = self._sessions.explain_facts(session_id)
        key = self._key(parts, cfg.provider, cfg.model)
        start_fen = start_position(inp.fen, inp.moves)[0].fen()
        solution = inp.moves[1:]
        hit = self._cache.get(key)
        if hit is not None:
            x = Explanation.from_json(hit.response_json)
            return ExplainView(parts.puzzle, x, cfg.provider, cfg.model, 0.0, True, start_fen, solution)
        progress(None, "Asking the AI…")
        result = self._usage.run(FEATURE, SYSTEM_PROMPT, build_prompt(inp), SCHEMA_NAME, SCHEMA)
        r = result.response
        if r.status == "truncated":
            raise AppError(
                f"The answer was cut short (it hit the {FEATURE} token limit), so nothing is shown. It was still "
                "billed. Try again, or choose Low reasoning in Settings → AI.",
                code="llm_truncated",
                retryable=True,
            )
        if r.status == "refused":
            raise AppError("The model declined to explain this one. Try another model.", code="llm_refused")
        explanation = validate(inp, r.text)
        if explanation is None:
            raise AppError("The AI's answer wasn't in the expected form, so nothing is shown. Try again.",
                           code="llm_bad_answer", retryable=True)  # fmt: skip
        self._cache.put(key, result.provider, result.model, explanation.to_json(), r.input_tokens, r.output_tokens,
                        self._clock.now().isoformat())  # fmt: skip
        return ExplainView(
            parts.puzzle, explanation, result.provider, result.model, result.cost_usd, False, start_fen, solution
        )

    def result(self, session_id: int) -> ExplainView | None:
        """The explanation of the puzzle on the board, if one finished."""
        with self._lock:
            view = self._results.get(session_id)
        if view is None or view.puzzle != self._sessions.current_puzzle(session_id):
            return None
        return view
