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
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.filters import MY_TIME_CLASSES, FilterSpec
from weaksquare.core.games import GameRecord, GameRow, LibraryFilter, detect_color, username_from, valid_username
from weaksquare.core.lichess import Dashboard
from weaksquare.core.stats import AttemptRow
from weaksquare.core.stats import Report as StatsReport
from weaksquare.core.suggested_mix import Suggestion, build_suggestion, report_preset
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed, JobRunner, ProgressFn

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


class GamePuzzleCount(Protocol):
    def coach_puzzles(self) -> list[tuple[int, int, int, str | None, str]]: ...


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
    ) -> None:
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
        progress(None, "Writing the report…")
        history = self._puzzle_history(state) if params.source != "games" and subject == ME else []
        infos = [self._info(gid, subject) for gid in game_ids]
        errors = self._reports.errors(subject, game_ids)
        reasons = self._reports.game_reasons() if subject == ME else {}
        report = build_report(params.source, [i for i in infos if i is not None], errors, reasons, history)
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
    )  # fmt: skip
