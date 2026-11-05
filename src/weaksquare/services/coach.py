"""The Coach (v0.10, REQUIREMENTS §10.1–10.7): one background run that syncs, analyzes, tags and makes
puzzles through the shared pipeline, then saves a free report and, for your own games, rebuilds the
Suggested mix.

**A run (one `coach_run` job, cancellable, with progress and an estimate of the time left, FR-10.14):**
1. Games (source Games or Both): your library after a sync of your linked accounts, or another
   player's public games fetched into their own subject (FR-10.3; Adam, v0.10 planning). Send to
   Coach gives the exact games instead.
2. Analysis of the games that aren't current, on the queue and the background engine (FR-10.26), at
   Game Review's think time, so every game opens in Game Review without a re-analysis (FR-10.9).
3. Tags, then puzzles from your mistakes (yours only, §10.9).
4. The puzzle history (source Puzzles or Both): local first tries per theme plus the Lichess dashboard
   when you're signed in (FR-10.15).
5. The report (`core/coach.py`), its preset (FR-10.19), and the trend against your previous report.

**The Suggested mix (FR-10.28–10.31):** rebuilt after each of your runs. It replaces the Mixer's
filters only if they're still the default broad mix or the last suggestion you applied; otherwise it
waits behind the Apply / Compare / Dismiss banner. Another player's run never touches it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.coach import ErrorRow, GameInfo, PuzzleTheme, Report, build_report, trend
from weaksquare.core.coach_diagnosis import MAX_NOTE, Diagnosis, NoteItem, Sent, strip_urls, title_key
from weaksquare.core.coach_diagnosis import SCHEMA as DIAGNOSIS_SCHEMA
from weaksquare.core.coach_diagnosis import SCHEMA_NAME as DIAGNOSIS_SCHEMA_NAME
from weaksquare.core.coach_diagnosis import SYSTEM_PROMPT as DIAGNOSIS_PROMPT
from weaksquare.core.coach_diagnosis import build_prompt as build_diagnosis_prompt
from weaksquare.core.coach_diagnosis import validate as validate_diagnosis
from weaksquare.core.coach_llm import (
    DETAILED_EXAMPLES,
    SCHEMA,
    SCHEMA_NAME,
    SUMMARY_EXAMPLES,
    SYSTEM_PROMPT,
    Coaching,
    ExamplePosition,
    build_prompt,
    fallback_preset,
    validate,
)
from weaksquare.core.digest import DIGEST_VERSION, Digest, build_digest, numbered_san
from weaksquare.core.errors import AppError, NotFoundError, ValidationError
from weaksquare.core.filters import MY_TIME_CLASSES, FilterSpec
from weaksquare.core.game_explain import san_moves
from weaksquare.core.game_measures import build_measures, game_weaknesses
from weaksquare.core.game_review import MoveRow, saved_line
from weaksquare.core.games import (
    GameError,
    GameRecord,
    GameRow,
    LibraryFilter,
    base_seconds,
    detect_color,
    parse_single_pgn,
    username_from,
    valid_username,
)
from weaksquare.core.lessons import (
    DEFAULT_SITES,
    SEARCH_SITES,
    catalog,
    curated,
    drill_preset,
    is_allowed,
    search_url,
    topic,
    validate_custom_template,
)
from weaksquare.core.lichess import Dashboard
from weaksquare.core.llm.defaults import COACH_TIMEOUT_S, TYPICAL_INPUT_TOKENS_PER_S, TYPICAL_OUTPUT_TOKENS_PER_S
from weaksquare.core.stats import AttemptRow
from weaksquare.core.stats import Report as StatsReport
from weaksquare.core.suggested_mix import DEFAULT_RATING, Suggestion, build_suggestion, report_preset
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed, JobRunner, ProgressFn
from weaksquare.services.llm_usage import prompt_chars

log = logging.getLogger(__name__)

JOB_KIND = "coach_run"
ME = "me"
SOURCES = ("puzzles", "games", "both")
COUNTS = (25, 50, 100, 200)
DETAILS = ("summary", "detailed")
COLORS = ("both", "white", "black")
PLATFORMS = ("lichess", "chesscom")
MAX_SENT_GAMES = 200
DASHBOARD_DAYS = 30
LAST_PARAMS_KEY = "coach.last_params"
SUGGESTED_KEY = "mixer.suggested"
APPLIED_KEY = "mixer.suggested_applied"
FILTERS_KEY = "mixer.filters"
MODE_KEY = "trainer.mode"
LESSON_SITES_KEY = "coach.lesson_sites"  # v0.11, written through services/ui_settings.py
LESSON_CUSTOM_URL_KEY = "coach.lesson_custom_url"
POSITIONS_PER_GAME = 80  # for the time estimate
RECENT_ATTEMPTS = 50


@dataclass(frozen=True)
class CoachParams:
    """One run's settings (FR-10.2–10.5). ``player`` None means you; otherwise a username or a profile
    URL, with ``platform`` saying where when the text doesn't."""

    source: str = "games"
    player: str | None = None
    platform: str = "lichess"
    platforms: tuple[str, ...] = ()  # your accounts to include; empty = every game of yours, imports too
    count: int = 50
    rated_only: bool = True
    time_classes: tuple[str, ...] = ("rapid", "classical")
    color: str = "both"
    detail: str = "summary"
    game_ids: tuple[int, ...] = ()  # Send to Coach (FR-11.30): exactly these games

    @classmethod
    def from_json(cls, data: Any) -> CoachParams:
        if not isinstance(data, dict):
            raise ValidationError("Coach settings must be an object.")
        known = {f for f in cls.__dataclass_fields__}
        if set(data) - known:
            raise ValidationError("unknown Coach setting(s): " + ", ".join(sorted(set(data) - known))[:200])
        kw: dict[str, Any] = {}
        for k, v in data.items():
            kw[k] = tuple(v) if isinstance(v, list) else v
        p = cls(**kw)
        p.validate()
        return p

    def validate(self) -> None:
        if self.source not in SOURCES:
            raise ValidationError("The source must be puzzle history, games or both.")
        if self.count not in COUNTS:
            raise ValidationError("The number of games must be 25, 50, 100 or 200.")
        if not isinstance(self.rated_only, bool):
            raise ValidationError("rated_only must be true or false")
        if not set(self.time_classes) <= set(MY_TIME_CLASSES) or not all(isinstance(t, str) for t in self.time_classes):
            raise ValidationError("Unknown time control.")
        if self.color not in COLORS:
            raise ValidationError("The color must be white, black or both.")
        if self.detail not in DETAILS:
            raise ValidationError("The detail level must be summary or detailed.")
        if self.platform not in PLATFORMS or not set(self.platforms) <= set(PLATFORMS):
            raise ValidationError("The platform must be Lichess or chess.com.")
        if self.player is not None and (not isinstance(self.player, str) or not self.player.strip()):
            raise ValidationError("Enter a username or a profile link.")
        if len(self.game_ids) > MAX_SENT_GAMES or not all(
            isinstance(g, int) and not isinstance(g, bool) for g in self.game_ids
        ):
            raise ValidationError(f"Send at most {MAX_SENT_GAMES} games to the Coach.")
        if self.source == "puzzles" and self.player is not None:
            raise ValidationError("The puzzle history is yours only: choose Games for another player.")

    def to_json(self) -> dict[str, Any]:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}


def resolve_player(text: str, platform: str) -> tuple[str, str]:
    """(platform, username) from a username or a profile URL (FR-10.3)."""
    t = text.strip()
    low = t.lower()
    if "lichess.org" in low:
        platform = "lichess"
    elif "chess.com" in low:
        platform = "chesscom"
    name = username_from(t)
    if not valid_username(name):
        raise ValidationError("That isn't a valid username or profile link.")
    return platform, name


# ---- what the service needs ----------------------------------------------------------------------


class Library(Protocol):
    def start_sync(self) -> str | None: ...

    def usernames(self) -> list[str]: ...

    def fetch_player_games(
        self, platform: str, username: str, want: Any, count: int, progress: ProgressFn, cancel: CancelToken
    ) -> list[int]: ...

    def list_games(self, f: LibraryFilter) -> tuple[list[GameRow], int]: ...


class GamesRepo(Protocol):
    def get(self, game_id: int) -> GameRow | None: ...

    def subjects(self, game_id: int) -> dict[str, str | None]: ...


class Analysis(Protocol):
    def queue(self, game_ids: Sequence[int], *, force: bool = False) -> str | None: ...

    def is_current(self, game: GameRow) -> bool: ...

    def retag(self, game_ids: Sequence[int] | None = None, cancel: CancelToken | None = None) -> int: ...

    def settings(self) -> Any: ...


class Puzzles(Protocol):
    def pending(self, game_ids: Sequence[int] | None = None) -> list[int]: ...

    def process_game(self, game_id: int, cancel: CancelToken | None = None, *, engine: bool = True) -> int: ...


class Reports(Protocol):
    def set_llm(self, report_id: int, llm: dict[str, Any]) -> None: ...

    def add(
        self, created_at: str, subject: str, label: str, source: str, params: dict[str, Any],
        report: dict[str, Any], game_ids: list[int],
    ) -> int: ...  # fmt: skip

    def get(self, report_id: int) -> Any: ...

    def recent(self, limit: int = 100) -> list[Any]: ...

    def previous(self, subject: str, before_id: int) -> Any: ...

    def count(self, subject: str) -> int: ...

    def errors(self, subject: str, game_ids: list[int]) -> list[ErrorRow]: ...

    def game_reasons(self) -> dict[tuple[int, int], str]: ...


class Stats(Protocol):
    def report(self) -> StatsReport: ...


class Attempts(Protocol):
    def attempt_rows(self) -> list[AttemptRow]: ...


class Account(Protocol):
    def token(self) -> str | None: ...

    def status(self) -> Any: ...


class Dashboards(Protocol):
    def dashboard(self, token: str, days: int) -> Dashboard: ...


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class AnalysisRows(Protocol):
    def rows(self, game_id: int) -> list[MoveRow]: ...


class Digests(Protocol):
    def get(self, game_ids: list[int]) -> dict[tuple[int, str], tuple[str, dict[str, Any]]]: ...

    def put(self, game_id: int, color: str, key: str, digest: dict[str, Any], built_at: str) -> None: ...


class GamePuzzleCount(Protocol):
    def coach_puzzles(self) -> list[tuple[int, int, int, str | None, str]]: ...


GAME_CAP_DEFAULT, GAME_CAP_MIN, GAME_CAP_MAX = 30, 10, 50  # FR-10.56


@dataclass(frozen=True)
class CoachAiOptions:
    """One AI run's options (FR-10.56, 10.60). Chosen for each run, off by default, and never saved
    (v0.11 planning), so nothing automatic can turn them on."""

    advanced: bool = False
    game_cap: int = GAME_CAP_DEFAULT
    include_notes: bool = False

    @classmethod
    def from_json(cls, data: Any) -> CoachAiOptions:
        if data is None:
            return cls()
        if isinstance(data, CoachAiOptions):
            return data
        if not isinstance(data, dict) or set(data) - {"advanced", "game_cap", "include_notes"}:
            raise ValidationError("Unknown AI coaching options.")
        adv, notes = data.get("advanced", False), data.get("include_notes", False)
        cap = data.get("game_cap", GAME_CAP_DEFAULT)
        if not isinstance(adv, bool) or not isinstance(notes, bool):
            raise ValidationError("advanced and include_notes must be true or false")
        if not isinstance(cap, int) or isinstance(cap, bool) or not GAME_CAP_MIN <= cap <= GAME_CAP_MAX:
            raise ValidationError(f"The game cap must be {GAME_CAP_MIN}–{GAME_CAP_MAX}.")
        return cls(adv, cap, notes)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdvancedCompare:
    """FR-10.56: how an Advanced run compares with a standard one, for the Confirm dialog."""

    games_with_moves: int
    token_ratio: float | None  # input tokens, Advanced ÷ standard
    standard_usd: float | None
    budget_share: float | None  # this run's typical cost ÷ the monthly budget
    minutes: int


@dataclass(frozen=True)
class CoachQuote:
    quote: Any  # services.game_explain.GameQuote
    compare: AdvancedCompare | None
    cached_run: int | None  # the stored run that would be shown again, when the state is 'cached'


@dataclass
class _AiRequest:
    row: Any
    kind: str
    fmt: str  # keyed (v0.10 prompt) / diagnosis (v0.11)
    system: str
    user: str
    schema_name: str
    schema: dict[str, Any]
    keys: list[str] = field(default_factory=list)
    sent: Sent | None = None
    labels: dict[str, int] = field(default_factory=dict)  # G label → game id (kept by the app only)
    fallback: dict[str, Any] | None = None
    notes: list[NoteItem] = field(default_factory=list)
    moves: int = 0  # games whose move list was sent (Advanced)


@dataclass(frozen=True)
class AiRunView:
    id: int
    created_at: str
    format: str
    advanced: bool
    include_notes: bool
    game_cap: int | None
    provider: str
    model: str
    cost_usd: float
    result: dict[str, Any]
    new: tuple[int, ...]  # indexes of findings no earlier run of this report had


@dataclass(frozen=True)
class LessonView:
    """FR-10.59 for one topic, as the screen gets it: no URLs."""

    topic: str
    label: str
    drill: dict[str, Any] | None  # "Learn X": a preset in the AI preset's shape
    curated: list[str]  # titles; open with target "curated:<index>"
    sites: list[str]  # youtube / chesscom / custom, as chosen in Settings


def finding_id(f: Any) -> str:
    """What makes two findings "the same" across runs: the measured key, else the topic, else the
    category and normalized title."""
    if not isinstance(f, dict):
        return ""
    if f.get("key"):
        return f"key:{f['key']}"
    if f.get("topic"):
        return f"topic:{f['topic']}"
    return f"title:{f.get('category')}:{title_key(str(f.get('title') or ''))}"


@dataclass(frozen=True)
class SuggestionState:
    report_id: int
    number: int  # "Coach run #N" (FR-10.28 note: checkpoints arrive in v1.0)
    created_at: str
    spec: dict[str, Any]
    mode: str
    why: list[str]
    pending: bool  # waiting behind the banner (FR-10.31)
    previous: dict[str, Any] | None = None  # the filters it would replace (Compare)


@dataclass
class _RunState:
    report_id: int | None = None
    notes: list[str] = field(default_factory=list)


class CoachService:
    def __init__(
        self,
        library: Library,
        games: GamesRepo,
        analysis: Analysis,
        puzzles: Puzzles,
        game_puzzles: GamePuzzleCount,
        reports: Reports,
        stats: Stats,
        attempts: Attempts,
        account: Account,
        lichess: Dashboards,
        settings: Settings,
        clock: Clock,
        runner: JobRunner,
        rows: AnalysisRows | None = None,
        llm_settings: Any = None,
        llm_usage: Any = None,
        digests: Digests | None = None,
        ai_runs: Any = None,
        observations: Any = None,
    ) -> None:
        self._digests = digests
        self._notes_repo: Any = reports if hasattr(reports, "game_notes") else None
        self._ai_jobs: dict[str, dict[str, int | None]] = {}
        self._ai_runs = ai_runs
        self._observations = observations
        self._rows = rows
        self._llm_settings = llm_settings
        self._llm_usage = llm_usage
        self._library = library
        self._games = games
        self._analysis = analysis
        self._puzzles = puzzles
        self._game_puzzles = game_puzzles
        self._reports = reports
        self._stats = stats
        self._attempts = attempts
        self._account = account
        self._lichess = lichess
        self._settings = settings
        self._clock = clock
        self._runner = runner
        self._runs: dict[str, _RunState] = {}

    # ------------------------------------------------------------ settings

    def last_params(self) -> CoachParams:
        raw = self._settings.get(LAST_PARAMS_KEY)
        try:
            return replace(CoachParams.from_json(raw), game_ids=()) if isinstance(raw, dict) else CoachParams()
        except (ValidationError, TypeError):
            return CoachParams()

    # ------------------------------------------------------------ a run

    def start_run(self, data: Any) -> str:
        params = CoachParams.from_json(data)
        if self._runner.active(JOB_KIND):
            raise ValidationError("A Coach run is already going. Wait for it or cancel it.")
        self._settings.set(LAST_PARAMS_KEY, replace(params, game_ids=()).to_json())
        if params.player is not None:
            platform, name = resolve_player(params.player, params.platform)
            if name.lower() in (u.lower() for u in self._library.usernames()):
                params = replace(params, player=None, platforms=(platform,))  # that's you
        state = _RunState()
        job = self._runner.submit(JOB_KIND, lambda p, c: self._run(params, state, p, c))
        self._runs[job] = state
        return job

    def run_result(self, job_id: str) -> int | None:
        st = self._runs.get(job_id)
        return st.report_id if st else None

    def _run(self, params: CoachParams, state: _RunState, progress: ProgressFn, cancel: CancelToken) -> str:
        subject, label = ME, self._my_label(params)
        other: tuple[str, str] | None = None
        if params.player is not None:
            other = resolve_player(params.player, params.platform)
            subject = f"{other[0]}:{other[1].lower()}"
            label = f"{other[1]} ({'Lichess' if other[0] == 'lichess' else 'chess.com'})"
        game_ids: list[int] = []
        if params.source != "puzzles":
            game_ids = self._collect(params, other, state, progress, cancel)
            if not game_ids:
                raise JobFailed(
                    "no_games", "No games match these settings. Try more time controls or include unrated games.",
                    retryable=False,
                )  # fmt: skip
            self._analyze(game_ids, progress, cancel)
            progress(None, "Tagging your mistakes…")
            self._analysis.retag(game_ids, cancel)
            if subject == ME:
                todo = self._puzzles.pending(game_ids)
                for n, gid in enumerate(todo):
                    progress(n / max(1, len(todo)), f"Making puzzles from your games: {n + 1} of {len(todo)}")
                    self._puzzles.process_game(gid, cancel)
        cancel.raise_if_cancelled()
        reasons = self._reports.game_reasons() if subject == ME else {}
        digests = self.digests(game_ids, subject, reasons, progress, cancel) if game_ids else []
        progress(None, "Writing the report…")
        history = self._puzzle_history(state) if params.source != "games" and subject == ME else []
        infos = [self._info(gid, subject) for gid in game_ids]
        errors = self._reports.errors(subject, game_ids)
        report = build_report(params.source, [i for i in infos if i is not None], errors, reasons, history)
        if digests:
            ms = build_measures(digests)
            report = replace(report, whole_game=game_weaknesses(digests, ms), measures=ms.to_json())
        rid = self._save(subject, label, params, report, game_ids, state)
        state.report_id = rid
        if subject == ME and params.source != "puzzles":
            self._suggest(rid, report)
        return f"Report ready: {report.games} game{'s' if report.games != 1 else ''}"

    def _my_label(self, params: CoachParams) -> str:
        names = self._library.usernames()
        return "You" + (f" ({', '.join(names)})" if names else "")

    def _want(self, params: CoachParams, username: str) -> Any:
        def want(rec: GameRecord) -> bool:
            if params.rated_only and rec.rated is not True:
                return False
            if params.time_classes and rec.time_class not in params.time_classes:
                return False
            if params.color != "both":
                return detect_color(rec.white, rec.black, [username]) == params.color
            return True

        return want

    def _collect(
        self, params: CoachParams, other: tuple[str, str] | None, state: _RunState, progress: ProgressFn,
        cancel: CancelToken,
    ) -> list[int]:  # fmt: skip
        if params.game_ids:
            ids = [g for g in params.game_ids if self._games.get(g) is not None]
            return (
                ids
                if other is None
                else [g for g in ids if f"{other[0]}:{other[1].lower()}" in self._games.subjects(g)]
            )
        if other is not None:
            return self._library.fetch_player_games(
                other[0], other[1], self._want(params, other[1]), params.count, progress, cancel
            )
        job = self._library.start_sync()
        if job is not None:
            progress(None, "Syncing your games…")
            done = self._wait(job, cancel)
            if done is not None and done.state == "failed":
                state.notes.append(f"Sync: {done.message}")
        rows, _ = self._library.list_games(
            LibraryFilter(
                player=ME, platforms=tuple(params.platforms), time_classes=tuple(params.time_classes),
                rated=True if params.rated_only else None,
                colors=() if params.color == "both" else (params.color,), limit=params.count,
            )
        )  # fmt: skip
        return [g.id for g in rows if g.user_color in ("white", "black", "both")]

    def _wait(self, job: str, cancel: CancelToken, on_tick: Any = None) -> Any:
        while True:
            if cancel.cancelled:
                self._runner.cancel(job)
                raise JobCancelled()
            st = self._runner.wait(job, 0.5)
            if st is not None and st.state in ("done", "failed", "cancelled"):
                return st
            if on_tick is not None:
                on_tick()

    def _analyze(self, game_ids: list[int], progress: ProgressFn, cancel: CancelToken) -> None:
        todo = [g for g in game_ids if (row := self._games.get(g)) is not None and not self._analysis.is_current(row)]
        if not todo:
            return
        job = self._analysis.queue(todo)
        if job is None:
            return
        think = float(getattr(self._analysis.settings(), "think_s", 0.3))
        started = self._clock.monotonic_ms()

        def tick() -> None:
            st = self._runner.status(job)
            frac = st.progress if st is not None and st.progress is not None else None
            left = len(todo) * POSITIONS_PER_GAME * think * (1 - (frac or 0))
            if frac and frac > 0.05:
                left = (self._clock.monotonic_ms() - started) / 1000 / frac * (1 - frac)
            minutes = max(1, round(left / 60))
            progress(
                frac, f"Analyzing {len(todo)} game{'s' if len(todo) != 1 else ''} on your PC: about {minutes} min left"
            )

        tick()
        done = self._wait(job, cancel, tick)
        if done is not None and done.state == "failed":
            raise JobFailed(done.error_code or "analysis_failed", done.message, retryable=False)
        if done is not None and done.state == "cancelled":
            raise JobCancelled()

    def _digest_key(self, g: GameRow) -> str:
        th = getattr(self._analysis.settings(), "thresholds", None)
        th_key = ",".join(str(v) for v in asdict(th).values()) if th is not None else ""
        return f"d{DIGEST_VERSION}|{g.analysis_engine}|{g.analysis_think_s}|{th_key}"

    def digests(
        self, game_ids: Sequence[int], subject: str, reasons: dict[tuple[int, int], str] | None = None,
        progress: ProgressFn | None = None, cancel: CancelToken | None = None,
    ) -> list[tuple[int, Digest]]:  # fmt: skip
        """FR-10.52: the subject's digest of each analyzed game, built from the stored analysis (no engine)
        and reused while the analysis is the same. Your mistake reasons are added when read, so tagging a
        reason never makes a digest stale."""
        if self._digests is None or self._rows is None:
            return []
        ids = list(dict.fromkeys(game_ids))
        stored = self._digests.get(ids)
        out: list[tuple[int, Digest]] = []
        for n, gid in enumerate(ids):
            if cancel is not None:
                cancel.raise_if_cancelled()
            g = self._games.get(gid)
            color = self._games.subjects(gid).get(subject) if g is not None else None
            if g is None or color not in ("white", "black") or g.analysis_status == "none":
                continue
            key = self._digest_key(g)
            have = stored.get((gid, color))
            d: Digest | None = None
            if have is not None and have[0] == key:
                try:
                    d = Digest.from_json(have[1])
                except (TypeError, ValueError, KeyError):
                    d = None
            if d is None:
                if progress is not None:
                    progress(n / max(1, len(ids)), f"Summarising your games: {n + 1} of {len(ids)}")
                rows = self._rows.rows(gid)
                if not rows:
                    continue
                d = build_digest(
                    rows=rows, color=color, result=g.result, eco=g.eco, opening=g.opening,
                    base_seconds=base_seconds(g.time_control),
                )  # fmt: skip
                self._digests.put(gid, color, key, d.to_json(), self._clock.now().isoformat(timespec="seconds"))
            if reasons:
                d = replace(d, moments=tuple(replace(m, reason=reasons.get((gid, m.ply - 1))) for m in d.moments))
            out.append((gid, d))
        return out

    def _info(self, gid: int, subject: str) -> GameInfo | None:
        g = self._games.get(gid)
        if g is None:
            return None
        color = self._games.subjects(gid).get(subject)
        result = None
        if g.result == "1/2-1/2":
            result = "draw"
        elif g.result in ("1-0", "0-1") and color in ("white", "black"):
            result = "win" if (g.result == "1-0") == (color == "white") else "loss"
        return GameInfo(gid, g.played_at, g.time_class, result)

    def _puzzle_history(self, state: _RunState) -> list[PuzzleTheme]:
        local = {t.key: t for t in self._stats.report().by_theme}
        dash: Dashboard | None = None
        token = self._account.token()
        if token:
            try:
                dash = self._lichess.dashboard(token, DASHBOARD_DAYS)
            except Exception as e:  # the dashboard is extra: the local history still counts
                log.info("puzzle dashboard unavailable: %s", type(e).__name__)
                state.notes.append("The Lichess puzzle dashboard couldn't be fetched; local puzzles only.")
        keys = set(local) | set(dash.themes if dash else {})
        out = []
        for k in sorted(keys):
            t = local.get(k)
            d = dash.themes.get(k) if dash else None
            out.append(
                PuzzleTheme(
                    k, t.attempts if t else 0, t.solved if t else 0, d.nb if d else 0, d.first_wins if d else 0,
                    d.performance if d else None,
                )
            )  # fmt: skip
        return out

    def _rating(self) -> int | None:
        st = self._account.status()
        rating = getattr(st, "rating", None)
        return rating if isinstance(rating, int) and not isinstance(rating, bool) else None

    def _recent_accuracy(self) -> float | None:
        rows = [r for r in self._attempts.attempt_rows() if r.finished_at is not None and not r.misclick]
        rows.sort(key=lambda r: r.finished_at)  # type: ignore[arg-type,return-value]
        recent = rows[-RECENT_ATTEMPTS:]
        return sum(r.win for r in recent) / len(recent) if len(recent) >= 10 else None

    def _save(
        self, subject: str, label: str, params: CoachParams, report: Report, game_ids: list[int], state: _RunState
    ) -> int:
        data = report.to_json()
        preset = report_preset(report, self._rating() if subject == ME else None, None)
        data["preset"] = preset.to_json() if preset else None
        data["notes"] = list(state.notes)
        rid = self._reports.add(
            self._clock.now().isoformat(timespec="seconds"), subject, label, params.source, params.to_json(), data,
            game_ids,
        )  # fmt: skip
        return rid

    # ------------------------------------------------------------ reports

    def reports(self) -> list[Any]:
        return self._reports.recent()

    def report(self, report_id: int) -> tuple[Any, dict[str, float]]:
        """A saved report and its trend against the subject's previous one (FR-10.20)."""
        if not isinstance(report_id, int) or isinstance(report_id, bool):
            raise ValidationError("report_id must be a whole number")
        row = self._reports.get(report_id)
        if row is None:
            raise NotFoundError("That report isn't saved.")
        prev = self._reports.previous(row.subject, row.id) if row.source_kind != "puzzles" else None
        cur = build_report_from_json(row.report)
        return row, (trend(cur, prev.report) if prev is not None and cur is not None else {})

    # ------------------------------------------------------------ AI coaching (FR-10.21–10.25, 10.54–10.60)

    def _example_refs(self, row: Any, detail: str) -> list[tuple[ExamplePosition, int, int]]:
        """The report's example moments as anonymized positions (FR-10.21), with the game and 0-based ply
        they come from, which only the app keeps."""
        if self._rows is None:
            return []
        limit = DETAILED_EXAMPLES if detail == "detailed" else SUMMARY_EXAMPLES
        picked: list[tuple[str, int, int]] = []
        weaknesses = [w for w in row.report.get("weaknesses") or [] if isinstance(w, dict)]
        rounds = max((len(w.get("examples") or []) for w in weaknesses), default=0)
        for i in range(rounds):  # round-robin over the top weaknesses, worst moments first
            for w in weaknesses:
                ex = w.get("examples") or []
                if i < len(ex) and len(picked) < limit:
                    gid, ply = int(ex[i]["game_id"]), int(ex[i]["ply"])
                    if all((g, p) != (gid, ply) for _, g, p in picked):
                        picked.append((str(w.get("key")), gid, ply))
        out: list[tuple[ExamplePosition, int, int]] = []
        cache: dict[int, list[MoveRow]] = {}
        for n, (wkey, gid, ply) in enumerate(picked, start=1):
            rows = cache.setdefault(gid, self._rows.rows(gid))
            if not 0 <= ply < len(rows):
                continue
            r = rows[ply]
            before = tuple(x.move_uci for x in rows[max(0, ply - 2) : ply])
            pos = ExamplePosition(
                f"E{n}", wkey, r.fen_before, r.move_uci,
                saved_line(r.lines[0].pv) if r.lines and r.lines[0].pv else (), r.themes, r.cp_loss,
                before, rows[ply - len(before)].fen_before if before else None,
            )  # fmt: skip
            out.append((pos, gid, ply))
        return out

    def _examples(self, row: Any, detail: str) -> list[ExamplePosition]:
        return [e for e, _, _ in self._example_refs(row, detail)]

    def _notes(self, row: Any, labels: dict[int, str]) -> list[NoteItem]:
        """FR-10.60: your notes for the run's games and puzzles, web addresses removed, as they'll be sent."""
        if self._notes_repo is None or row.subject != ME:
            return []
        out: list[NoteItem] = []
        for n in self._notes_repo.game_notes(list(labels)):
            if n.game_id in labels and n.ply is not None:
                out.append(NoteItem(strip_urls(n.note)[:MAX_NOTE], n.reason, labels[n.game_id], n.ply + 1, n.source))
        since = row.report.get("first_played")
        for n in self._notes_repo.puzzle_notes(since, None):
            out.append(NoteItem(strip_urls(n.note)[:MAX_NOTE], n.reason, None, None, n.source))
        return out

    def _ai_request(self, report_id: Any, options: CoachAiOptions) -> _AiRequest:
        if self._llm_settings is None or self._llm_usage is None:
            raise AppError("AI coaching isn't available.", code="no_llm")
        row, _ = self.report(report_id)
        detail = str(row.params.get("detail") or "summary")
        kind = "coach_detailed" if detail == "detailed" else "coach_summary"
        fallback = fallback_preset(row.report)
        reasons = self._reports.game_reasons() if row.subject == ME else {}
        digests = self.digests(row.game_ids, row.subject, reasons) if row.game_ids else []
        if not digests:  # a puzzle-history report (or no analyzed games): the v0.10 keyed prompt
            if options.advanced or options.include_notes:
                raise ValidationError("Advanced analysis and Include my notes need a report with games.")
            user = build_prompt(row.report, self._examples(row, detail), detail)
            keys = [
                str(w.get("key"))
                for g in ("missed", "allowed", "habits", "puzzles")
                for w in row.report.get(g) or []
                if isinstance(w, dict)
            ]
            return _AiRequest(
                row, kind, "keyed", SYSTEM_PROMPT, user, SCHEMA_NAME, SCHEMA, keys=keys, fallback=fallback
            )
        labels = {gid: f"G{n}" for n, (gid, _) in enumerate(digests, start=1)}
        games = [(labels[gid], d) for gid, d in digests]
        examples = [(e, labels.get(gid), ply + 1) for e, gid, ply in self._example_refs(row, detail) if gid in labels]
        moves: dict[str, str] | None = None
        if options.advanced:
            moves = {}
            for gid, _ in digests[: options.game_cap]:
                g = self._games.get(gid)
                try:
                    parsed = parse_single_pgn(g.pgn) if g is not None else None
                except GameError:
                    parsed = None
                if parsed is not None:
                    moves[labels[gid]] = san_moves(parsed.start_fen, parsed.moves)
        notes = self._notes(row, labels) if options.include_notes else None
        topics = catalog([d.family for _, d in digests])
        user, sent = build_diagnosis_prompt(row.report, games, examples, detail, topics, moves=moves, notes=notes)
        return _AiRequest(
            row, kind, "diagnosis", DIAGNOSIS_PROMPT, user, DIAGNOSIS_SCHEMA_NAME, DIAGNOSIS_SCHEMA,
            sent=sent, labels={v: k for k, v in labels.items()}, fallback=fallback, notes=notes or [],
            moves=len(moves or {}),
        )  # fmt: skip

    def _cached_run(self, report_id: int, options: CoachAiOptions, cfg: Any, fmt: str) -> Any:
        if self._ai_runs is None:
            return None
        for r in reversed(self._ai_runs.for_report(report_id)):
            same = r.advanced == options.advanced and r.include_notes == options.include_notes
            if options.advanced:
                same = same and r.game_cap == options.game_cap
            if same and r.format == fmt and r.provider == cfg.provider and r.model == cfg.model:
                return r
        return None

    def quote_ai(self, report_id: Any, options: Any = None) -> CoachQuote:
        """FR-10.25, 10.56: the estimate for Get AI coaching, checked against the cap and the budget; with
        Advanced, how it compares with a standard run."""
        from weaksquare.services.game_explain import GameQuote  # one quote shape for every AI feature

        opts = CoachAiOptions.from_json(options)
        req = self._ai_request(report_id, opts)
        cfg = self._llm_settings.config("coach")
        spend = self._llm_usage.spend(cfg)
        cached = self._cached_run(req.row.id, opts, cfg, req.fmt)
        if cached is not None:
            q = GameQuote("cached", None, cfg.provider, cfg.model, None, cfg.run_cap_usd, spend)
            return CoachQuote(q, None, cached.id)
        lq = self._llm_usage.quote(req.kind, prompt_chars(req.system, req.user, req.schema), cfg)
        q = GameQuote(str(lq.state), lq.message, lq.provider, lq.model, lq.estimate, lq.run_cap_usd, spend)
        compare = None
        if opts.advanced and lq.estimate is not None:
            std = self._ai_request(report_id, replace(opts, advanced=False))
            std_q = self._llm_usage.quote(req.kind, prompt_chars(std.system, std.user, std.schema), cfg)
            est = lq.estimate
            base = std_q.estimate.input_tokens if std_q.estimate is not None else 0
            seconds = (
                est.input_tokens / TYPICAL_INPUT_TOKENS_PER_S + est.typical_output_tokens / TYPICAL_OUTPUT_TOKENS_PER_S
            )
            compare = AdvancedCompare(
                games_with_moves=req.moves,
                token_ratio=round(est.input_tokens / base, 1) if base else None,
                standard_usd=std_q.estimate.typical_usd if std_q.estimate is not None else None,
                budget_share=round(est.typical_usd / spend.budget_usd, 3) if spend.budget_usd else None,
                minutes=max(1, round(seconds / 60)),
            )
        return CoachQuote(q, compare, None)

    def notes_preview(self, report_id: Any) -> list[NoteItem]:
        """FR-10.60: exactly the notes Include my notes would send."""
        return self._ai_request(report_id, CoachAiOptions(include_notes=True)).notes

    def start_ai(self, report_id: Any, options: Any = None) -> str:
        """Run the AI coaching. The UI calls this only after you Confirm the estimate (FR-8.11)."""
        opts = CoachAiOptions.from_json(options)
        quote = self.quote_ai(report_id, opts.to_json())
        if quote.quote.state not in ("ok", "cached"):
            raise AppError(quote.quote.message or "AI coaching can't run now.", code=quote.quote.state)
        holder: dict[str, int | None] = {"run": quote.cached_run}

        def run(progress: ProgressFn, cancel: CancelToken) -> str:
            try:
                msg, run_id = self._coach_ai(report_id, opts, progress)
            except AppError as e:
                raise JobFailed(e.code, e.message, e.retryable) from None
            holder["run"] = run_id
            return msg

        job = self._runner.submit("coach_ai", run)
        self._ai_jobs[job] = holder
        return job

    def ai_job_run(self, job_id: str) -> int | None:
        """The AI run a finished Get AI coaching job made (or reused)."""
        h = self._ai_jobs.get(job_id)
        return h["run"] if h else None

    def _coach_ai(self, report_id: Any, opts: CoachAiOptions, progress: ProgressFn) -> tuple[str, int | None]:
        req = self._ai_request(report_id, opts)
        cfg = self._llm_settings.config("coach")
        cached = self._cached_run(req.row.id, opts, cfg, req.fmt)
        if cached is not None:
            return "AI coaching (saved).", cached.id
        progress(None, "Asking the AI to coach you…")
        result = self._llm_usage.run(
            req.kind, req.system, req.user, req.schema_name, req.schema, timeout_s=COACH_TIMEOUT_S
        )
        r = result.response
        if r.status == "truncated":
            raise AppError(
                "The answer was cut short (it hit the Coach's token limit), so nothing is shown. It was still "
                "billed. Try again, or choose Low reasoning for the Coach in Settings → AI.",
                code="llm_truncated",
                retryable=True,
            )
        if r.status == "refused":
            raise AppError("The model declined. Try another model.", code="llm_refused")
        data: dict[str, Any] | None = None
        if req.fmt == "keyed":
            coaching = validate(r.text, req.keys, req.fallback)
            data = coaching.to_json() if coaching is not None else None
        else:
            assert req.sent is not None
            diag = validate_diagnosis(r.text, req.sent, req.fallback)
            if diag is not None:
                data = {**diag.to_json(), "labels": req.labels, "seen": self._observe(req.row, diag)}
        if data is None:
            raise AppError(
                "The AI's answer wasn't in the expected form, so nothing is shown. Try again.",
                code="llm_bad_answer",
                retryable=True,
            )
        data.update({"provider": result.provider, "model": result.model, "cost_usd": result.cost_usd})
        run_id = None
        if self._ai_runs is not None:
            run_id = self._ai_runs.add(
                req.row.id, self._clock.now().isoformat(timespec="seconds"), req.fmt, advanced=opts.advanced,
                include_notes=opts.include_notes, game_cap=opts.game_cap if opts.advanced else None,
                provider=result.provider, model=result.model, cost_usd=result.cost_usd, result=data,
            )  # fmt: skip
        return f"AI coaching for ${result.cost_usd:.4f}.", run_id

    def _observe(self, row: Any, diag: Diagnosis) -> list[int]:
        """FR-10.57: observations (findings with no measured key) are noted per subject and report. The
        result is how many reports have seen each finding, in finding order (0 for tracked weaknesses)."""
        out: list[int] = []
        for f in diag.findings:
            if f.key is not None or self._observations is None:
                out.append(0)
            elif f.topic:
                out.append(self._observations.note(row.subject, f.topic, "", "", f.title, row.id))
            else:
                out.append(self._observations.note(row.subject, "", f.category, title_key(f.title), f.title, row.id))
        return out

    def ai_runs(self, report_id: Any) -> list[AiRunView]:
        """Every AI answer for this report, oldest first, each with the findings that no earlier answer had
        (Adam, v0.11 planning)."""
        row, _ = self.report(report_id)
        runs = self._ai_runs.for_report(row.id) if self._ai_runs is not None else []
        if not runs and row.llm:  # a v0.10 answer stored on the report only
            llm = row.llm
            return [
                AiRunView(0, row.created_at, "keyed", False, False, None, str(llm.get("provider") or ""),
                          str(llm.get("model") or ""), float(llm.get("cost_usd") or 0), llm, ())
            ]  # fmt: skip
        out: list[AiRunView] = []
        seen: set[str] = set()
        for r in runs:
            new: list[int] = []
            ids: list[str] = []
            if r.format == "diagnosis":
                for i, f in enumerate(r.result.get("findings") or []):
                    ident = finding_id(f)
                    ids.append(ident)
                    if out and ident not in seen:
                        new.append(i)
            out.append(
                AiRunView(r.id, r.created_at, r.format, r.advanced, r.include_notes, r.game_cap, r.provider, r.model,
                          r.cost_usd, r.result, tuple(new))
            )  # fmt: skip
            seen.update(ids)
        return out

    def move_labels(self, game_id: int) -> list[str]:
        """Every move of an analyzed game as numbered SAN ("23... Nf6"), by 0-based ply: what an
        evidence chip shows, from your own analysis rather than the AI's text (FR-10.55)."""
        if self._rows is None:
            return []
        return [numbered_san(r) for r in self._rows.rows(game_id)]

    # ------------------------------------------------------------ lesson pointers (FR-10.59)

    @staticmethod
    def _families(row: Any) -> list[str]:
        ms = row.report.get("measures") if isinstance(row.report, dict) else None
        return [str(o.get("family")) for o in (ms or {}).get("openings") or [] if isinstance(o, dict)]

    def lesson_sites(self) -> tuple[list[str], str]:
        """(the search sites you chose, your custom template) from Settings → Coach."""
        raw = self._settings.get(LESSON_SITES_KEY)
        sites = [s for s in raw if s in (*SEARCH_SITES, "custom")] if isinstance(raw, list) else list(DEFAULT_SITES)
        custom = self._settings.get(LESSON_CUSTOM_URL_KEY)
        try:
            template = validate_custom_template(custom) if isinstance(custom, str) else ""
        except ValueError:
            template = ""
        if not template and "custom" in sites:
            sites.remove("custom")
        return sites, template

    def lesson(self, report_id: Any, topic_id: str) -> LessonView | None:
        """A topic's pointers: the in-app drill first, then the curated pages, then the search sites. No
        URL leaves the backend: the screen gets titles and site names only."""
        row, _ = self.report(report_id)
        t = topic(topic_id, self._families(row)) if isinstance(topic_id, str) else None
        if t is None:
            return None
        sites, _ = self.lesson_sites()
        return LessonView(
            t.id, t.label, drill_preset(t, self._rating() or DEFAULT_RATING),
            [title for title, _ in curated(t.id)], sites,
        )  # fmt: skip

    def lesson_url(self, report_id: Any, topic_id: Any, target: Any) -> str:
        """The URL behind one pointer, built here only (FR-10.59). Refuses anything off the curated
        allowlist or the search sites you chose."""
        if not isinstance(topic_id, str) or not isinstance(target, str):
            raise ValidationError("Unknown lesson.")
        row, _ = self.report(report_id)
        t = topic(topic_id, self._families(row))
        if t is None:
            raise ValidationError("Unknown lesson topic.")
        if target.startswith("curated:"):
            links = curated(t.id)
            idx = target.split(":", 1)[1]
            if not idx.isdigit() or int(idx) >= len(links) or not is_allowed(links[int(idx)][1]):
                raise ValidationError("Unknown lesson link.")
            return links[int(idx)][1]
        sites, template = self.lesson_sites()
        if target not in sites:
            raise ValidationError("That search site is turned off in Settings → Coach.")
        try:
            return search_url(target, t, template)
        except ValueError as e:
            raise ValidationError(str(e)) from None

    def ai_result(self, report_id: Any) -> tuple[Coaching, dict[str, Any]] | None:
        """The latest keyed (v0.10-format) answer."""
        for r in reversed(self.ai_runs(report_id)):
            if r.format == "keyed":
                return Coaching.from_json(r.result), {"provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}
        return None

    # ------------------------------------------------------------ the Suggested mix (FR-10.28–10.31)

    def _has_game_puzzles(self) -> bool:
        return any(status == "active" for *_, status in self._game_puzzles.coach_puzzles())

    def _current_filters(self) -> dict[str, Any] | None:
        raw = self._settings.get(FILTERS_KEY)
        try:
            return FilterSpec.from_json(raw).to_json() if isinstance(raw, dict) else None
        except ValidationError:
            return None

    def _suggest(self, report_id: int, report: Report) -> None:
        current = self._current_filters()
        base = FilterSpec.from_json(current) if current else None
        s = build_suggestion(
            report, puzzle_rating=self._rating(), recent_accuracy=self._recent_accuracy(),
            has_game_puzzles=self._has_game_puzzles(), base=base,
        )  # fmt: skip
        if s is None:
            return
        applied = self._settings.get(APPLIED_KEY)
        untouched = current is None or current == FilterSpec().to_json() or current == applied
        state = SuggestionState(
            report_id, self._reports.count(ME), self._clock.now().isoformat(timespec="seconds"), s.spec.to_json(),
            s.mode, list(s.why), pending=not untouched, previous=current,
        )  # fmt: skip
        self._settings.set(SUGGESTED_KEY, asdict(state))
        if untouched:
            self._apply(s)

    def _apply(self, s: Suggestion) -> None:
        spec = s.spec.to_json()
        self._settings.set(FILTERS_KEY, spec)
        self._settings.set(APPLIED_KEY, spec)
        self._settings.set(MODE_KEY, s.mode)

    def suggestion(self) -> SuggestionState | None:
        raw = self._settings.get(SUGGESTED_KEY)
        if not isinstance(raw, dict):
            return None
        try:
            return SuggestionState(**raw)
        except TypeError:
            return None

    def apply_suggestion(self) -> SuggestionState:
        """Apply: the suggestion becomes your filters and mode. Never touches a saved preset."""
        st = self.suggestion()
        if st is None:
            raise NotFoundError("There's no suggested mix yet. Run the Coach first.")
        spec = FilterSpec.from_json(st.spec)
        self._apply(Suggestion(spec, st.mode, tuple(st.why), ()))
        new = replace(st, pending=False)
        self._settings.set(SUGGESTED_KEY, asdict(new))
        return new

    def dismiss_suggestion(self) -> SuggestionState | None:
        st = self.suggestion()
        if st is None:
            return None
        new = replace(st, pending=False)
        self._settings.set(SUGGESTED_KEY, asdict(new))
        return new

    def is_suggested(self, filters: Any) -> bool:
        """The current filters are the applied suggestion (the label on the main page)."""
        try:
            spec = FilterSpec.from_json(filters).to_json()
        except ValidationError:
            return False
        return spec == self._settings.get(APPLIED_KEY)


def build_report_from_json(data: dict[str, Any]) -> Report | None:
    """A saved report back as a `Report` for the trend (only the fields the trend reads)."""
    from weaksquare.core.coach import Weakness  # local: keeps the import list short

    def ws(items: Any) -> list[Weakness]:
        out = []
        for w in items or []:
            if isinstance(w, dict) and isinstance(w.get("key"), str):
                out.append(
                    Weakness(
                        w["key"], str(w.get("kind")), str(w.get("name")), str(w.get("label")), int(w.get("count") or 0),
                        float(w.get("per10") or 0), int(w.get("severity") or 0), float(w.get("score") or 0),
                        tuple(w.get("themes") or ()), w.get("mode"), dict(w.get("reasons") or {}),
                    )
                )  # fmt: skip
        return out

    if not isinstance(data, dict):
        return None
    return Report(
        str(data.get("source")), int(data.get("games") or 0), data.get("first_played"), data.get("last_played"),
        dict(data.get("per10") or {}), dict(data.get("results") or {}), ws(data.get("missed")),
        ws(data.get("allowed")), ws(data.get("habits")), ws(data.get("puzzles")), [], {}, 0,
        whole_game=ws(data.get("whole_game")), measures=data.get("measures") if isinstance(data.get("measures"), dict) else None,
    )  # fmt: skip
