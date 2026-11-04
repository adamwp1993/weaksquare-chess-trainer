"""Game Review AI (v0.9, REQUIREMENTS §11.4): Explain this move and Explain my game.

Built from the **stored analysis** only, so neither needs the engine. Each follows `ExplainService`'s
pattern:

1. **Quote** (FR-8.11): what the request would cost and whether the guardrails allow it, from the prompt
   itself. A cached result is free and always allowed (FR-8.6).
2. **Start:** guardrails are checked at once, then a job sends one request through `LlmUsageService.run`
   (the Game Review feature's provider, model and reasoning, FR-1.15; the shared cap and budget), validates
   the answer against the game, and caches the validated result in `llm_cache`.
3. **Result:** the explanation under today's settings: a fresh one with its cost, or the cached one for free.

**Cache keys** (FR-11.20): (game, ply, provider, model) for a move and (game, N, provider, model) for the
narrative, plus the analysis settings (think time and engine), the grading thresholds (v0.9-B2) and, for
the narrative, the key-moment plies, so re-analysis or new thresholds never bring back an answer grounded on
other evals or grades (v0.9 planning).

Explain this move is for **your** moves (every move when you review both sides). A finished Explain my game
marks the game **AI-reviewed** (FR-11.25); re-analysis sets it back to Analyzed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import AppError, NotFoundError, ValidationError
from weaksquare.core.explain import (
    GAME_MOVE_SYSTEM_PROMPT,
    SCHEMA,
    SCHEMA_NAME,
    CacheKeyParts,
    Explanation,
    build_prompt,
    validate,
)
from weaksquare.core.game_explain import (
    MAX_MOMENTS,
    NARRATIVE_SCHEMA,
    NARRATIVE_SCHEMA_NAME,
    NARRATIVE_SYSTEM_PROMPT,
    GameNarrative,
    NarrativeInput,
    build_narrative_prompt,
    move_input,
    validate_narrative,
)
from weaksquare.core.game_review import ERRORS, MoveRow
from weaksquare.core.games import GameRow, parse_single_pgn
from weaksquare.core.llm.cost import Estimate
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn
from weaksquare.services.explain import ExplainView, cache_key
from weaksquare.services.llm_settings import LlmSettingsService
from weaksquare.services.llm_usage import LlmUsageService, Spend, prompt_chars

FEATURE = "game_review"
MOVE_KIND, NARRATIVE_KIND = "game_move", "game_narrative"
MOVE_JOB, NARRATIVE_JOB = "game_move_explain", "game_narrative"


class Games(Protocol):
    def get(self, game_id: int) -> GameRow | None: ...

    def mark_ai_reviewed(self, game_id: int) -> None: ...


class Analysis(Protocol):
    def rows(self, game_id: int) -> list[MoveRow]: ...


class ReviewPrefs(Protocol):
    def settings(self) -> Any: ...  # ReviewSettings (key_moments)


class CacheRepo(Protocol):
    def get(self, key: str) -> Any | None: ...

    def put(
        self, key: str, provider: str, model: str, response_json: str, input_tokens: int, output_tokens: int,
        created_at: str,
    ) -> None: ...  # fmt: skip


@dataclass(frozen=True)
class GameQuote:
    state: str  # 'ok' / 'cached' / a guardrail state ('over_budget', 'over_cap', 'no_model', …)
    message: str | None
    provider: str
    model: str
    estimate: Estimate | None
    run_cap_usd: float
    spend: Spend  # for the Confirm dialog: the share of the remaining budget (FR-8.11)


@dataclass(frozen=True)
class NarrativeView:
    game_id: int
    n: int
    narrative: GameNarrative
    moments: tuple[int, ...]  # the key moments it covers
    provider: str
    model: str
    cost_usd: float  # 0 for a cached result
    cached: bool


def _check_id(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{name} must be a whole number")
    return value


def _yours(game: GameRow, mover: str) -> bool:
    return game.user_color == "both" or game.user_color == mover


def top_moments(rows: list[MoveRow], color: str, n: int) -> tuple[int, ...]:
    """FR-11.13 for the narrative: your `n` largest errors, in game order (both sides pooled for 'both')."""
    errs = [r for r in rows if r.classification in ERRORS and (color == "both" or r.mover == color)]
    top = sorted(errs, key=lambda r: (-r.cp_loss, r.ply))[: max(0, n)]
    return tuple(sorted(r.ply for r in top))


class GameExplainService:
    def __init__(
        self,
        games: Games,
        analysis: Analysis,
        prefs: ReviewPrefs,
        settings: LlmSettingsService,
        usage: LlmUsageService,
        cache: CacheRepo,
        runner: JobRunner,
        clock: Clock,
    ) -> None:
        self._games = games
        self._analysis = analysis
        self._prefs = prefs
        self._settings = settings
        self._usage = usage
        self._cache = cache
        self._runner = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._fresh: dict[str, Any] = {}  # cache key -> the view of a result made in this run (with its cost)
        self._jobs: dict[str, str] = {}  # cache key -> job id

    # ---- shared -----------------------------------------------------------------------------------------

    def _analyzed(self, game_id: object) -> tuple[GameRow, list[MoveRow]]:
        gid = _check_id(game_id, "game_id")
        game = self._games.get(gid)
        if game is None:
            raise NotFoundError("That game isn't in your library.")
        rows = self._analysis.rows(gid) if game.analysis_status != "none" else []
        if not rows or len(rows) != len(parse_single_pgn(game.pgn).moves):
            raise ValidationError("Analyze this game first: the AI explains Stockfish's analysis.")
        if game.user_color not in ("white", "black", "both"):
            raise ValidationError("Choose which side you played first.")
        return game, rows

    def _key(self, game: GameRow, what: tuple[Any, ...], provider: str, model: str) -> str:
        th = self._prefs.settings().thresholds  # the grades in the prompt depend on them (v0.9-B2)
        analysis = (
            f"{game.analysis_think_s}|{game.analysis_engine}|{th.inaccuracy},{th.mistake},{th.blunder},{th.decided}"
        )
        ref = ":".join(["game", str(game.id), analysis, *(str(w) for w in what)])
        return cache_key(CacheKeyParts(ref, (), provider, model))

    def _quote(self, kind: str, key: str | None, chars: int) -> GameQuote:
        cfg = self._settings.config(FEATURE)
        spend = self._usage.spend(cfg)
        if key is not None and self._cache.get(key) is not None:
            return GameQuote("cached", None, cfg.provider, cfg.model, None, cfg.run_cap_usd, spend)
        q = self._usage.quote(kind, chars, cfg)
        return GameQuote(str(q.state), q.message, q.provider, q.model, q.estimate, q.run_cap_usd, spend)

    def _cfg_key(self, game: GameRow, what: tuple[Any, ...]) -> str | None:
        cfg = self._settings.config(FEATURE)
        if not cfg.configured or not cfg.model:
            return None
        return self._key(game, what, cfg.provider, cfg.model)

    def _start(self, key: str, job_kind: str, quote: GameQuote, fn: Any) -> str:
        if quote.state not in ("ok", "cached"):
            raise AppError(quote.message or "Game Review's AI can't run now.", code=quote.state)
        with self._lock:
            running = self._jobs.get(key)
            status = self._runner.status(running) if running else None
            if running is not None and status is not None and status.state == "running":
                return running
            job = self._runner.submit(job_kind, fn)
            self._jobs[key] = job
            return job

    def _send(self, kind: str, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> Any:
        result = self._usage.run(kind, system, user, schema_name, schema)
        r = result.response
        if r.status == "truncated":
            raise AppError(
                "The answer was cut short (it hit Game Review's token limit), so nothing is shown. It was still "
                "billed. Try again, or choose Low reasoning for Game Review in Settings → AI.",
                code="llm_truncated",
                retryable=True,
            )
        if r.status == "refused":
            raise AppError("The model declined to explain this one. Try another model.", code="llm_refused")
        return result

    def _bad_answer(self) -> AppError:
        return AppError("The AI's answer wasn't in the expected form, so nothing is shown. Try again.",
                        code="llm_bad_answer", retryable=True)  # fmt: skip

    @staticmethod
    def _as_job(fn: Any) -> Any:
        def job(progress: ProgressFn, token: CancelToken) -> str:
            try:
                return str(fn(progress))
            except AppError as e:
                raise JobFailed(e.code, e.message, e.retryable) from None

        return job

    # ---- Explain this move (FR-11.17) ----------------------------------------------------------------

    def _move(self, game_id: object, ply: object) -> tuple[GameRow, MoveRow, Any]:
        game, rows = self._analyzed(game_id)
        p = _check_id(ply, "ply")
        if not 0 <= p < len(rows):
            raise ValidationError("There's no such move in this game.")
        row = rows[p]
        if not _yours(game, row.mover):
            raise ValidationError("Explain this move works on your own moves.")
        inp = move_input(row)
        if inp is None:
            raise ValidationError("The analysis has no best line for this move.")
        return game, row, inp

    def quote_move(self, game_id: object, ply: object) -> GameQuote:
        game, row, inp = self._move(game_id, ply)
        chars = prompt_chars(GAME_MOVE_SYSTEM_PROMPT, build_prompt(inp), SCHEMA)
        return self._quote(MOVE_KIND, self._cfg_key(game, ("move", row.ply)), chars)

    def start_move(self, game_id: object, ply: object) -> str:
        game, row, inp = self._move(game_id, ply)
        key = self._cfg_key(game, ("move", row.ply))
        quote = self.quote_move(game_id, ply)

        def run(progress: ProgressFn) -> str:
            view = self._explain_move(game, row, inp, progress)
            return "Explained (saved)." if view.cached else f"Explained for ${view.cost_usd:.4f}."

        return self._start(key or f"move:{game.id}:{row.ply}", MOVE_JOB, quote, self._as_job(run))

    def _view(self, game: GameRow, row: MoveRow, inp: Any, x: Explanation, provider: str, model: str,
              cost: float, cached: bool) -> ExplainView:  # fmt: skip
        return ExplainView(f"game:{game.id}:{row.ply}", x, provider, model, cost, cached, inp.fen, inp.moves[1:])

    def _explain_move(self, game: GameRow, row: MoveRow, inp: Any, progress: ProgressFn) -> ExplainView:
        cfg = self._settings.config(FEATURE)
        key = self._key(game, ("move", row.ply), cfg.provider, cfg.model)
        hit = self._cache.get(key)
        if hit is not None:
            return self._view(game, row, inp, Explanation.from_json(hit.response_json), cfg.provider, cfg.model,
                              0.0, True)  # fmt: skip
        progress(None, "Asking the AI…")
        result = self._send(MOVE_KIND, GAME_MOVE_SYSTEM_PROMPT, build_prompt(inp), SCHEMA_NAME, SCHEMA)
        x = validate(inp, result.response.text)
        if x is None:
            raise self._bad_answer()
        key = self._key(game, ("move", row.ply), result.provider, result.model)
        self._cache.put(key, result.provider, result.model, x.to_json(), result.response.input_tokens,
                        result.response.output_tokens, self._clock.now().isoformat())  # fmt: skip
        view = self._view(game, row, inp, x, result.provider, result.model, result.cost_usd, False)
        with self._lock:
            self._fresh[key] = view
        return view

    def move_result(self, game_id: object, ply: object) -> ExplainView | None:
        """The explanation of this move under today's Game Review model, if there is one."""
        game, row, inp = self._move(game_id, ply)
        cfg = self._settings.config(FEATURE)
        key = self._cfg_key(game, ("move", row.ply))
        if key is None:
            return None
        with self._lock:
            fresh = self._fresh.get(key)
        if fresh is not None:
            return fresh  # type: ignore[no-any-return]
        hit = self._cache.get(key)
        if hit is None:
            return None
        return self._view(game, row, inp, Explanation.from_json(hit.response_json), cfg.provider, cfg.model, 0.0, True)

    # ---- Explain my game (FR-11.18, 11.19) -------------------------------------------------------------

    def _narrative_input(self, game_id: object, n: object) -> tuple[GameRow, NarrativeInput, int]:
        game, rows = self._analyzed(game_id)
        if n is None:
            n = self._prefs.settings().key_moments
        count = _check_id(n, "n")
        if not 1 <= count <= MAX_MOMENTS:
            raise ValidationError(f"Explain my game covers 1 to {MAX_MOMENTS} key moments.")
        parsed = parse_single_pgn(game.pgn)
        color = str(game.user_color)
        inp = NarrativeInput(parsed.start_fen, parsed.moves, tuple(rows), color, game.user_result,
                             top_moments(rows, color, count))  # fmt: skip
        return game, inp, count

    def _narrative_what(self, inp: NarrativeInput, n: int) -> tuple[Any, ...]:
        return ("narrative", n, ",".join(str(p) for p in inp.moments))

    def quote_narrative(self, game_id: object, n: object = None) -> GameQuote:
        game, inp, count = self._narrative_input(game_id, n)
        chars = prompt_chars(NARRATIVE_SYSTEM_PROMPT, build_narrative_prompt(inp), NARRATIVE_SCHEMA)
        return self._quote(NARRATIVE_KIND, self._cfg_key(game, self._narrative_what(inp, count)), chars)

    def start_narrative(self, game_id: object, n: object = None) -> str:
        """Run Explain my game. The UI calls this only after you Confirm the estimate (FR-8.11)."""
        game, inp, count = self._narrative_input(game_id, n)
        key = self._cfg_key(game, self._narrative_what(inp, count))
        quote = self.quote_narrative(game_id, count)

        def run(progress: ProgressFn) -> str:
            view = self._explain_game(game, inp, count, progress)
            return "Game explained (saved)." if view.cached else f"Game explained for ${view.cost_usd:.4f}."

        return self._start(key or f"narrative:{game.id}:{count}", NARRATIVE_JOB, quote, self._as_job(run))

    def _explain_game(self, game: GameRow, inp: NarrativeInput, n: int, progress: ProgressFn) -> NarrativeView:
        cfg = self._settings.config(FEATURE)
        what = self._narrative_what(inp, n)
        key = self._key(game, what, cfg.provider, cfg.model)
        hit = self._cache.get(key)
        if hit is not None:
            self._games.mark_ai_reviewed(game.id)
            return NarrativeView(game.id, n, GameNarrative.from_json(hit.response_json), inp.moments, cfg.provider,
                                 cfg.model, 0.0, True)  # fmt: skip
        progress(None, "Asking the AI about your game…")
        result = self._send(NARRATIVE_KIND, NARRATIVE_SYSTEM_PROMPT, build_narrative_prompt(inp), NARRATIVE_SCHEMA_NAME,
                            NARRATIVE_SCHEMA)  # fmt: skip
        narrative = validate_narrative(inp, result.response.text)
        if narrative is None:
            raise self._bad_answer()
        key = self._key(game, what, result.provider, result.model)
        self._cache.put(key, result.provider, result.model, narrative.to_json(), result.response.input_tokens,
                        result.response.output_tokens, self._clock.now().isoformat())  # fmt: skip
        self._games.mark_ai_reviewed(game.id)
        view = NarrativeView(game.id, n, narrative, inp.moments, result.provider, result.model, result.cost_usd, False)
        with self._lock:
            self._fresh[key] = view
        return view

    def narrative_result(self, game_id: object, n: object = None) -> NarrativeView | None:
        game, inp, count = self._narrative_input(game_id, n)
        cfg = self._settings.config(FEATURE)
        key = self._cfg_key(game, self._narrative_what(inp, count))
        if key is None:
            return None
        with self._lock:
            fresh = self._fresh.get(key)
        if fresh is not None:
            return fresh  # type: ignore[no-any-return]
        hit = self._cache.get(key)
        if hit is None:
            return None
        return NarrativeView(game.id, count, GameNarrative.from_json(hit.response_json), inp.moments, cfg.provider,
                             cfg.model, 0.0, True)  # fmt: skip
