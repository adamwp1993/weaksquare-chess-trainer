"""Overviews, move explanations and prefetch (v0.13, FR-12.5–12.7, 12.15).

**Ask once** (FR-12.7): a note is stored by position, move, kind, provider, model and prompt version. A saved note from
another model still shows, labelled and free, and counts as stored for prefetch. Regenerate is how you replace one.

**One run, one cap** (FR-12.7b): a prefetch's requests are quoted together, and only as many as fit under the per-run
cap go in one run. The rest show as the next run, with what's stored already skipped. During a run each request also
counts what the run has spent, so it stops at the cap or the budget, and everything finished stays saved.

**Attribution** (FR-12.15): a note records the Wikibooks pages and revisions its prompt drew on.

No move here comes from an answer: `opening_explain` validates text about moves the book, explorer or engine supplied.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import chess

from weaksquare.core.clock import Clock
from weaksquare.core.engine import EngineNotInstalled
from weaksquare.core.errors import AppError, NotFoundError, ValidationError
from weaksquare.core.opening_explain import (
    KIND_LINE,
    KIND_MOVE,
    KIND_OVERVIEW,
    LINE_SCHEMA,
    LINE_SCHEMA_NAME,
    LINE_SYSTEM_PROMPT,
    MOVE,
    OVERVIEW,
    OVERVIEW_SCHEMA,
    OVERVIEW_SCHEMA_NAME,
    OVERVIEW_SYSTEM_PROMPT,
    PER_MOVE_PROMPT_CHARS,
    PROMPT_VERSION,
    Note,
    PositionFacts,
    build_line_prompt,
    build_overview_prompt,
    validate_line_notes,
    validate_overview,
)
from weaksquare.core.opening_sources import (
    LICENCE_NAME,
    LICENCE_URL,
    WikiPage,
    page_title,
    page_url,
    prompt_text,
    short_title,
    unfetched_chars,
)
from weaksquare.core.openings import Line, LineMove, OpeningScope, board_of, position_key, validate_scope
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn
from weaksquare.services.llm_settings import LlmSettingsService
from weaksquare.services.llm_usage import BatchQuote, LlmUsageService, prompt_chars
from weaksquare.services.opening_sources import OpeningSources
from weaksquare.services.openings import OpeningsService

FEATURE = "openings"
NOTE_JOB, PREFETCH_JOB = "opening_note", "opening_prefetch"
DEFAULT_REQUEST_S = 20.0  # FR-12.7b: a conservative figure until there's history for your model
WARN_BUDGET_SHARE = 0.25  # FR-12.7b
WARN_SECONDS = 600
MAX_PAGES_PER_REQUEST = 3
MAX_PAGE_LOOKUPS = 8
RUN_STOPPERS = ("over_cap", "over_budget", "not_configured", "no_model", "no_price", "llm_bad_key", "llm_quota")
ANSWER_FAILURES = ("llm_truncated", "llm_refused", "llm_bad_answer")


class _Billed(AppError):
    """The provider answered and charged for it, but there's nothing to save. A run still counts what it cost."""

    def __init__(self, message: str, cost: float, *, code: str, retryable: bool = False) -> None:
        super().__init__(message, code=code, retryable=retryable)
        self.cost = cost


class Repo(Protocol):
    def get(self, key: str, move: str, kind: str, provider: str, model: str, version: int) -> Any | None: ...

    def latest(self, key: str, move: str, kind: str) -> Any | None: ...

    def replace(self, row: Any) -> None: ...

    def for_positions(self, keys: Sequence[str]) -> list[Any]: ...

    def delete_positions(self, keys: Sequence[str]) -> int: ...


@dataclass(frozen=True)
class NoteRow:
    position_key: str
    move_uci: str
    kind: str
    provider: str
    model: str
    prompt_version: int
    body_json: str
    sources_json: str = "[]"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    created_at: str = ""


@dataclass(frozen=True)
class NoteSource:
    label: str
    url: str
    revision_id: int | None


@dataclass(frozen=True)
class NoteView:
    position_key: str
    move_uci: str
    kind: str
    note: Note
    provider: str
    model: str
    other_model: bool  # saved under a model you've since changed from
    sources: tuple[NoteSource, ...]
    licence: str = LICENCE_NAME
    licence_url: str = LICENCE_URL


@dataclass(frozen=True)
class NoteQuote:
    state: str  # 'ok', 'cached' (free), or why not
    message: str | None
    typical_usd: float | None
    worst_usd: float | None
    provider: str
    model: str


@dataclass(frozen=True)
class PrefetchPlan:
    """Everything the dialog shows (FR-12.7b)."""

    lines: int
    positions: int
    requests: int
    stored: int  # notes already saved, and so free
    llm: bool  # false: engine time only
    state: str
    message: str | None
    input_tokens: int
    output_tokens: int
    typical_usd: float
    worst_usd: float
    run_cap_usd: float
    budget_share: float  # of what's left this month, 0..1
    fits_cap: bool
    this_run_requests: int  # how many fit under the cap, when it's split
    runs: int
    llm_seconds: float
    engine_seconds: float
    warn: tuple[str, ...]
    blurb: str
    scope: OpeningScope
    extend: bool


@dataclass
class _Request:
    kind: str
    line: Line | None
    plies: list[int] = field(default_factory=list)  # move plies still missing in this line
    chars: int = 0


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"about {max(1, round(seconds))} seconds"
    return f"about {round(seconds / 60)} minutes"


def _sources(pages: Sequence[WikiPage]) -> str:
    return json.dumps([{"title": p.title, "revision_id": p.revision_id} for p in pages], separators=(",", ":"))


class OpeningNotesService:
    def __init__(
        self, repo: Repo, openings: OpeningsService, sources: OpeningSources, settings: LlmSettingsService,
        usage: LlmUsageService, runner: JobRunner, clock: Clock, exports: Path,
    ) -> None:  # fmt: skip
        self._repo = repo
        self._openings = openings
        self._sources = sources
        self._settings = settings
        self._usage = usage
        self._runner = runner
        self._clock = clock
        self._exports = exports
        self._lock = threading.Lock()
        self._jobs: dict[str, str] = {}

    # ---- reading ----------------------------------------------------------------------------------------------

    def _view(self, row: Any) -> NoteView:
        cfg = self._settings.config(FEATURE)
        pages = json.loads(row.sources_json or "[]")
        sources = tuple(NoteSource(short_title(p["title"]), page_url(p["title"]), p.get("revision_id")) for p in pages)
        other = (row.provider, row.model) != (cfg.provider, cfg.model) and bool(cfg.model)
        return NoteView(row.position_key, row.move_uci, row.kind, Note.from_json(row.body_json), row.provider, row.model, other, sources)  # fmt: skip

    def _stored(self, key: str, move: str, kind: str) -> Any | None:
        """An exact match first, then whatever's saved (labelled and free, FR-12.7)."""
        cfg = self._settings.config(FEATURE)
        if cfg.model:
            exact = self._repo.get(key, move, kind, cfg.provider, cfg.model, PROMPT_VERSION)
            if exact is not None:
                return exact
        return self._repo.latest(key, move, kind)

    def note(self, key: object, move: object, kind: object) -> NoteView | None:
        if not isinstance(key, str) or not isinstance(move, str) or kind not in (OVERVIEW, MOVE):
            raise ValidationError("That isn't a note.")
        row = self._stored(key, move, str(kind))
        return self._view(row) if row is not None else None

    # ---- what a request holds ---------------------------------------------------------------------------------

    def _engine_or_raise(self) -> None:
        if self._openings.engine_status_state() != "ready":
            raise EngineNotInstalled("Install Stockfish first: the AI explains what Stockfish shows.")

    def _line(
        self, family: object, index: object, scope: OpeningScope | None = None, extend: bool | None = None
    ) -> Line:
        lines = self._openings.lines(family, scope, extend).lines
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(lines):
            raise NotFoundError("That line isn't in this opening.")
        return lines[index]

    def _facts(self, line: Line, plies: Sequence[int], asked: bool) -> list[PositionFacts]:
        """The engine's view of these moves. A note you asked for and are waiting on uses the interactive engine, and a
        prefetch uses the background one (FR-12.3)."""
        out: list[PositionFacts] = []
        for ply in plies:
            move = line.moves[ply]
            found = (
                self._openings.interactive_lines(move.key_before)
                if asked
                else self._openings.engine_lines(move.key_before, True)
            )
            out.append(PositionFacts(ply, move, tuple(found or ())))
        return out

    def _pages(self, line: Line, plies: Sequence[int], refresh: bool) -> tuple[str, tuple[WikiPage, ...]]:
        """Reference text for these plies, nearest the end first: later pages are the specific ones. Network."""
        if not self._sources.use_wikibooks():
            return "", ()
        sans = [m.san for m in line.moves]
        found: list[WikiPage] = []
        for lookups, ply in enumerate(sorted(plies, reverse=True)):
            if lookups >= MAX_PAGE_LOOKUPS or len(found) >= MAX_PAGES_PER_REQUEST:
                break
            page = self._sources.fetch_page(page_title(sans[: ply + 1]), refresh)
            if page is not None and page.status == "ok":
                found.append(page)
        return prompt_text(found)

    def _root_pages(self, line: Line, root_len: int, refresh: bool) -> tuple[str, tuple[WikiPage, ...]]:
        if not self._sources.use_wikibooks():
            return "", ()
        page = self._sources.fetch_page(page_title([m.san for m in line.moves[:root_len]]), refresh)
        return prompt_text([page] if page is not None else [])

    # ---- sending ---------------------------------------------------------------------------------------------

    def _save(self, key: str, move: str, kind: str, note: Note, pages: Sequence[WikiPage], result: Any) -> None:
        self._repo.replace(
            NoteRow(
                key, move, kind, result.provider, result.model, PROMPT_VERSION, note.to_json(), _sources(pages),
                result.response.input_tokens, result.response.output_tokens, result.cost_usd,
                self._clock.now().isoformat(),
            )
        )  # fmt: skip

    def _send(self, kind: str, system: str, user: str, name: str, schema: dict[str, Any], run_spent: float) -> Any:
        result = self._usage.run(kind, system, user, name, schema, run_spent=run_spent)
        status = result.response.status
        cost = float(result.cost_usd)
        if status == "truncated":
            raise _Billed(
                "The answer was cut short (it hit the token limit), so nothing was saved. It was still billed. Try "
                "Low reasoning for Openings in Settings → AI.",
                cost, code="llm_truncated", retryable=True,
            )  # fmt: skip
        if status == "refused":
            raise _Billed("The model declined to explain this one. Try another model.", cost, code="llm_refused")
        return result

    def _overview(self, family: object, run_spent: float = 0.0, asked: bool = False, refresh: bool = False) -> float:
        """Ask for an opening's overview and save it. Returns its cost."""
        root = self._openings.root(family)
        line = self._line(family, 0)
        plies = sorted({max(0, len(root.moves) - 1), max(0, len(line.moves) - 1)})
        reference, pages = self._root_pages(line, len(root.moves), refresh)
        prompt = build_overview_prompt(root.family, root.eco, line.moves, self._facts(line, plies, asked), reference)
        result = self._send(
            KIND_OVERVIEW, OVERVIEW_SYSTEM_PROMPT, prompt, OVERVIEW_SCHEMA_NAME, OVERVIEW_SCHEMA, run_spent
        )
        note = validate_overview(result.response.text)
        if note is None:
            raise _Billed("The AI's answer wasn't in the expected form, so nothing is shown. Try again.",
                          float(result.cost_usd), code="llm_bad_answer", retryable=True)  # fmt: skip
        self._save(root.final_key, "", OVERVIEW, note, pages, result)
        return float(result.cost_usd)

    def _explain_plies(
        self, line: Line, plies: Sequence[int], kind: str, run_spent: float, asked: bool = False, refresh: bool = False
    ) -> tuple[int, float]:
        """Ask about these moves of a line, in one request. Returns how many notes were saved, and the cost."""
        reference, pages = self._pages(line, plies, refresh)
        facts = self._facts(line, plies, asked)
        prompt = build_line_prompt(line.name, line.eco, line.moves, facts, reference)
        result = self._send(kind, LINE_SYSTEM_PROMPT, prompt, LINE_SCHEMA_NAME, LINE_SCHEMA, run_spent)
        notes = validate_line_notes(facts, result.response.text)
        for ply, note in notes.items():
            move = line.moves[ply]
            self._save(move.key_before, move.uci, MOVE, note, pages, result)
        return len(notes), float(result.cost_usd)

    # ---- one note (FR-12.5, 12.6) ----------------------------------------------------------------------------

    def _note_target(self, family: object, index: object, ply: object) -> tuple[str, str, str, int]:
        """(position, move, kind, prompt characters without Wikibooks)."""
        if ply is None:
            root = self._openings.root(family)
            line = self._line(family, 0)
            chars = prompt_chars(
                OVERVIEW_SYSTEM_PROMPT,
                build_overview_prompt(root.family, root.eco, line.moves, [], ""),
                OVERVIEW_SCHEMA,
            )
            return root.final_key, "", OVERVIEW, chars + unfetched_chars(1)  # fmt: skip
        line = self._line(family, index)
        if not isinstance(ply, int) or isinstance(ply, bool) or not 0 <= ply < len(line.moves):
            raise ValidationError("There's no such move in this line.")
        move = line.moves[ply]
        chars = prompt_chars(
            LINE_SYSTEM_PROMPT, build_line_prompt(line.name, line.eco, line.moves, [], ""), LINE_SCHEMA
        )
        return move.key_before, move.uci, MOVE, chars + PER_MOVE_PROMPT_CHARS + unfetched_chars(1)

    def quote_note(self, family: object, index: object, ply: object, regenerate: bool = False) -> NoteQuote:
        key, move, kind, chars = self._note_target(family, index, ply)
        cfg = self._settings.config(FEATURE)
        if not regenerate and self._stored(key, move, kind) is not None:
            return NoteQuote("cached", None, 0.0, 0.0, cfg.provider, cfg.model)
        q = self._usage.quote(KIND_OVERVIEW if kind == OVERVIEW else KIND_MOVE, chars, cfg)
        est = q.estimate
        return NoteQuote(str(q.state), q.message, est.typical_usd if est else None, est.worst_usd if est else None,
                         q.provider, q.model)  # fmt: skip

    def start_note(self, family: object, index: object, ply: object, regenerate: bool = False) -> str | None:
        """Ask for one note. None when it's already saved. Regenerate replaces it, after you've seen the cost."""
        if not isinstance(regenerate, bool):
            raise ValidationError("Regenerate must be true or false.")
        quote = self.quote_note(family, index, ply, regenerate)
        if quote.state == "cached":
            return None
        if quote.state != "ok":
            raise AppError(quote.message or "The AI can't run now.", code=quote.state)
        self._engine_or_raise()

        def job(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, "Asking the AI…")
            try:
                if ply is None:
                    cost = self._overview(family, asked=True, refresh=regenerate)
                else:
                    assert isinstance(ply, int)
                    saved, cost = self._explain_plies(
                        self._line(family, index), [ply], KIND_MOVE, 0.0, asked=True, refresh=regenerate
                    )
                    if not saved:
                        raise AppError("The AI's answer wasn't in the expected form, so nothing is shown. Try again.",
                                       code="llm_bad_answer", retryable=True)  # fmt: skip
            except AppError as e:
                raise JobFailed(e.code, e.message, e.retryable) from None
            return f"Saved for ${cost:.4f}."

        return self._runner.submit(NOTE_JOB, job)

    # ---- a move outside the book (FR-12.8) ------------------------------------------------------------------------

    @staticmethod
    def _moves_line(moves: object) -> Line:
        """A line of legal UCI moves as a line a note can be about. Its moves were checked here, not by the AI."""
        if not isinstance(moves, list) or not moves:
            raise ValidationError("That isn't a line of moves.")
        board = chess.Board()
        out: list[LineMove] = []
        for uci in moves:
            try:
                move = chess.Move.from_uci(uci) if isinstance(uci, str) else None
            except ValueError:
                move = None
            if move is None or move not in board.legal_moves:
                raise ValidationError("That isn't a line of legal moves.")
            out.append(LineMove(move.uci(), board.san(move), "line", position_key(board)))
            board.push(move)
        return Line("Your line", "none", tuple(out))

    def quote_moves_note(self, moves: object, regenerate: bool = False) -> NoteQuote:
        line = self._moves_line(moves)
        last = line.moves[-1]
        cfg = self._settings.config(FEATURE)
        if not regenerate and self._stored(last.key_before, last.uci, MOVE) is not None:
            return NoteQuote("cached", None, 0.0, 0.0, cfg.provider, cfg.model)
        chars = prompt_chars(
            LINE_SYSTEM_PROMPT, build_line_prompt(line.name, line.eco, line.moves, [], ""), LINE_SCHEMA
        )
        q = self._usage.quote(KIND_MOVE, chars + PER_MOVE_PROMPT_CHARS + unfetched_chars(1), cfg)
        est = q.estimate
        return NoteQuote(str(q.state), q.message, est.typical_usd if est else None, est.worst_usd if est else None,
                         q.provider, q.model)  # fmt: skip

    def start_moves_note(self, moves: object, regenerate: bool = False) -> str | None:
        """Explain the last move of a line. None when it's already saved."""
        if not isinstance(regenerate, bool):
            raise ValidationError("Regenerate must be true or false.")
        quote = self.quote_moves_note(moves, regenerate)
        if quote.state == "cached":
            return None
        if quote.state != "ok":
            raise AppError(quote.message or "The AI can't run now.", code=quote.state)
        self._engine_or_raise()
        line = self._moves_line(moves)

        def job(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, "Asking the AI…")
            try:
                saved, cost = self._explain_plies(
                    line, [len(line.moves) - 1], KIND_MOVE, 0.0, asked=True, refresh=regenerate
                )
                if not saved:
                    raise AppError("The AI's answer wasn't in the expected form, so nothing is shown. Try again.",
                                   code="llm_bad_answer", retryable=True)  # fmt: skip
            except AppError as e:
                raise JobFailed(e.code, e.message, e.retryable) from None
            return f"Saved for ${cost:.4f}."

        return self._runner.submit(NOTE_JOB, job)

    # ---- prefetch (FR-12.7a, 12.7b) ------------------------------------------------------------------------------

    def _requests(
        self, family: object, scope: OpeningScope, extend: bool
    ) -> tuple[list[_Request], list[Line], int, int]:
        """What's still missing, one request per line. Returns (requests, lines, positions, already stored)."""
        view = self._openings.lines(family, scope, extend)
        root = self._openings.root(family)
        requests: list[_Request] = []
        stored = 0
        keys: set[tuple[str, str]] = set()
        base = prompt_chars(LINE_SYSTEM_PROMPT, "", LINE_SCHEMA)
        if self._stored(root.final_key, "", OVERVIEW) is not None:
            stored += 1
        else:
            chars = (
                prompt_chars(OVERVIEW_SYSTEM_PROMPT, "", OVERVIEW_SCHEMA)
                + 2 * PER_MOVE_PROMPT_CHARS
                + unfetched_chars(1)
            )
            requests.append(_Request(KIND_OVERVIEW, None, [], chars))
        positions: set[str] = set()
        for line in view.lines:
            missing: list[int] = []
            for ply, m in enumerate(line.moves):
                positions.add(m.key_before)
                if (m.key_before, m.uci) in keys:
                    continue
                keys.add((m.key_before, m.uci))
                if self._stored(m.key_before, m.uci, MOVE) is not None:
                    stored += 1
                else:
                    missing.append(ply)
            target = len(missing)
            if extend and self._openings.can_grow(line, scope.max_moves):  # the job may grow it first, up to the limit
                target += max(0, scope.max_moves * 2 - len(line.moves))
            if missing or (extend and target):
                chars = base + PER_MOVE_PROMPT_CHARS * target + unfetched_chars(MAX_PAGES_PER_REQUEST)
                requests.append(_Request(KIND_LINE, line, missing, chars))
        return requests, list(view.lines), len(positions), stored

    def _scope(self, preset: object, sub_lines: object, max_moves: object) -> OpeningScope:
        return self._openings.scope() if preset is None else validate_scope(preset, sub_lines, max_moves)

    def plan(self, family: object, preset: object = None, sub_lines: object = None, max_moves: object = None,
             extend: object = None) -> PrefetchPlan:  # fmt: skip
        scope = self._scope(preset, sub_lines, max_moves)
        ext = self._openings.extend_setting() if extend is None else extend
        if not isinstance(ext, bool):
            raise ValidationError("Choose whether lines continue past the book.")
        requests, lines, positions, stored = self._requests(family, scope, ext)
        cfg = self._settings.config(FEATURE)
        batch: BatchQuote = self._usage.quote_batch(FEATURE, [(r.kind, r.chars) for r in requests])
        llm = batch.state not in ("not_configured", "no_model")
        cap_bins = _bins(batch.per_request_worst, batch.run_cap_usd)
        recent = self._usage.recent_seconds(cfg.provider, cfg.model) if cfg.model else None
        llm_seconds = (recent or DEFAULT_REQUEST_S) * len(requests) if llm else 0.0
        engine_seconds = self._openings.engine_seconds(lines, scope.max_moves, ext)
        share = (
            batch.typical_usd / batch.budget_left_usd
            if batch.budget_left_usd > 0
            else (1.0 if batch.typical_usd else 0.0)
        )
        warn: list[str] = []
        if llm and share > WARN_BUDGET_SHARE:
            warn.append(f"That's {share:.0%} of what's left of this month's AI budget.")
        if llm_seconds + engine_seconds > WARN_SECONDS:
            warn.append(f"It'll take {_duration(llm_seconds + engine_seconds)}.")
        fits = batch.state != "over_cap"
        # A single request above the cap can't be split: it stays blocked, and the state says why.
        split_works = bool(cap_bins) and all(w <= batch.run_cap_usd + 1e-9 for w in batch.per_request_worst)
        state = "split" if batch.state == "over_cap" and split_works else batch.state
        moves = sum(len(ln.moves) for ln in lines)
        total_s = llm_seconds + engine_seconds
        if llm:
            blurb = (
                f"About {moves} moves across {len(lines)} lines: ~{len(requests)} requests, ~${batch.typical_usd:.2f} "
                f"(≈{share:.0%} of this month's budget), {_duration(total_s)}. Already-saved notes are free. You can keep "
                "using the app while it runs, and cancel at any time; whatever is finished stays saved."
            )
        else:
            blurb = (
                f"About {moves} moves across {len(lines)} lines: {_duration(engine_seconds)} of Stockfish time. With no AI "
                "set up, this saves engine evals only."
            )
        return PrefetchPlan(
            len(lines), positions, len(requests), stored, llm, str(state), batch.message, batch.input_tokens,
            batch.typical_output_tokens, batch.typical_usd, batch.worst_usd, batch.run_cap_usd, share, fits,
            len(cap_bins[0]) if cap_bins else 0, max(1, len(cap_bins)), llm_seconds, engine_seconds, tuple(warn), blurb,
            scope, ext,
        )  # fmt: skip

    def start_prefetch(self, family: object, preset: object = None, sub_lines: object = None, max_moves: object = None,
                       extend: object = None) -> str:  # fmt: skip
        """Run what fits under the cap. The UI calls this only after you Confirm (FR-8.11)."""
        plan = self.plan(family, preset, sub_lines, max_moves, extend)
        if plan.llm and plan.state not in ("ok", "split"):
            raise AppError(plan.message or "The AI can't run now.", code=plan.state)
        self._engine_or_raise()
        job_key = str(family)
        with self._lock:
            running = self._jobs.get(job_key)
            status = self._runner.status(running) if running else None
            if running is not None and status is not None and status.state == "running":
                return running

        def job(progress: ProgressFn, token: CancelToken) -> str:
            return self._prefetch(family, plan, progress, token)

        job_id = self._runner.submit(PREFETCH_JOB, job)
        with self._lock:
            self._jobs[job_key] = job_id
        return job_id

    def _prefetch(self, family: object, plan: PrefetchPlan, progress: ProgressFn, token: CancelToken) -> str:
        scope, ext = plan.scope, plan.extend
        if ext:
            progress(None, "Continuing the lines past the book…")
            book = self._openings.lines(family, scope, False).lines
            self._openings.extend_now(book, scope.max_moves, token, progress)
        requests, lines, _, _ = self._requests(family, scope, ext)
        if not plan.llm:
            for line in lines:
                for m in line.moves:
                    token.raise_if_cancelled()
                    self._openings.engine_lines(m.key_before, True)
            return "Saved Stockfish's evals. There's no AI set up, so no notes were written."
        batch = self._usage.quote_batch(FEATURE, [(r.kind, r.chars) for r in requests])
        bins = _bins(batch.per_request_worst, batch.run_cap_usd)
        take = len(bins[0]) if bins else 0
        spent, saved, failed, errors = 0.0, 0, 0, 0
        stop: str | None = None
        trouble: str | None = None
        for i, req in enumerate(requests[:take]):
            token.raise_if_cancelled()
            progress(i / max(1, take), f"Asking the AI ({i + 1} of {take})…")
            try:
                if req.line is None:
                    spent += self._overview(family, spent)
                    saved += 1
                elif req.plies:
                    count, cost = self._explain_plies(req.line, req.plies, KIND_LINE, spent)
                    spent += cost
                    saved += count
                    failed += len(req.plies) - count
            except AppError as e:
                if isinstance(e, _Billed):
                    spent += e.cost
                if e.code in RUN_STOPPERS:
                    stop = e.message
                    break
                if e.code in ANSWER_FAILURES:
                    failed += 1
                else:
                    errors += 1
                    trouble = e.message
        left = len(requests) - take
        parts = [f"Saved {saved} notes for ${spent:.4f}."]
        if failed:
            parts.append(f"{failed} didn't come back in the expected form; asking again costs only those.")
        if errors:
            noun = "request" if errors == 1 else "requests"
            parts.append(f"{errors} {noun} failed: {trouble} Run it again to ask for those.")
        if stop:
            parts.append(f"Stopped early: {stop}")
        elif left > 0:
            parts.append(f"{left} requests are left for the next run.")
        return " ".join(parts)

    # ---- export and delete (FR-12.7) -------------------------------------------------------------------------------

    def _note_keys(self, family: object) -> list[str]:
        """An opening's positions, including past the book (FR-12.13). A note on a What if? reply is off its lines, and a
        position doesn't say which opening it came from, so it stays."""
        return sorted(self._openings.tail_keys(family).union(self._openings.family_keys(family)))

    def delete(self, family: object) -> int:
        return self._repo.delete_positions(self._note_keys(family))

    def export(self, family: object) -> Path | None:
        """A Markdown file of an opening's notes, with the credit for any page they drew on (FR-12.15)."""
        rows = self._repo.for_positions(self._note_keys(family))
        if not rows:
            return None
        root = self._openings.root(family)
        out = [f"# {root.family} ({root.eco})", ""]
        credits: dict[str, str] = {}
        for row in rows:
            view = self._view(row)
            label = "Overview" if row.kind == OVERVIEW else _move_label(row.position_key, row.move_uci)
            out.extend([f"## {label}", ""])
            for heading, text in view.note.sections:
                out.extend([f"**{heading}:** {text}", ""])
            out.extend([f"*{row.provider} {row.model}*", ""])
            credits.update({s.url: s.label for s in view.sources})
        if credits:
            out.extend(["---", "", f"These notes are based in part on Wikibooks, *Chess Opening Theory*, and may adapt its text. They're shared under {LICENCE_NAME}: {LICENCE_URL}", ""])  # fmt: skip
            out.extend(f"- {label}: {url}" for url, label in sorted(credits.items()))
            out.append("")
        self._exports.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9-]+", "-", root.family).strip("-") or "opening"
        path = self._exports / f"{name}-notes.md"
        path.write_text("\n".join(out), encoding="utf-8")
        return path


def _move_label(key: str, uci: str) -> str:
    board = board_of(key)
    try:
        return board.san(chess.Move.from_uci(uci))
    except ValueError:
        return uci


def _bins(worsts: Sequence[float], cap: float) -> list[list[int]]:
    """FR-12.7b: split a run's requests, in order, into runs each under the cap. A request above the cap alone
    gets its own bin, and stays blocked by the request-level check."""
    bins: list[list[int]] = []
    total = 0.0
    for i, worst in enumerate(worsts):
        if bins and total + worst <= cap + 1e-9:
            bins[-1].append(i)
            total += worst
        else:
            bins.append([i])
            total = worst
    return bins
