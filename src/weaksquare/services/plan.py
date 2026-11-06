"""The training plan (v0.12, REQUIREMENTS §10.12, FR-10.61–10.66).

**Ticks come from stored events, worked out when the plan is read** (`_facts`), rather than from hooks in the
session, review and journal services. A puzzle task counts the attempts of the sessions started from it; Retry reads
`retry_attempts`; a review reads `review_passes`; a reflection reads `journal_entries`. The time the app first sees a
task done is stored, so the daily log can count it on that day.

**A puzzle task never touches your Mixer** (FR-10.63): `start_task` builds its filters from the defaults
(`core.plan.task_spec`) and starts the session directly, so `mixer.filters`, `trainer.mode`, the Suggested mix and
your presets are never written.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.lessons import drill_preset, topic
from weaksquare.core.plan import (
    DEFAULT_PUZZLE_MINUTES,
    GAME_PUZZLES,
    LESSON,
    PUZZLE_MINUTES_SAMPLE,
    PUZZLES,
    REFLECTION,
    RETRY,
    REVIEW,
    Context,
    DayRow,
    Facts,
    PlanDraft,
    PlanParams,
    PlanRow,
    Task,
    TaskRow,
    auto_done,
    build_plan,
    first_day,
    focus,
    general_task,
    plan_progress,
    same_task,
    status_of,
    swap_choices,
    task_minutes,
    task_spec,
    to_carry,
    training_dates,
)
from weaksquare.core.suggested_mix import DEFAULT_RATING

PARAMS_KEY = "plan.params"
CARRY_KEY = "plan.carry_over"
ME = "me"
WIDEN = 200


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class TaskView:
    task: TaskRow
    status: str  # left / done / skipped / carried / missed
    auto: bool  # the app saw it done, whatever you ticked
    progress: int | None  # puzzle tasks: decided attempts so far
    minutes_spent: int


@dataclass(frozen=True)
class DayView:
    day: DayRow
    tasks: tuple[TaskView, ...]
    is_today: bool


@dataclass(frozen=True)
class PlanView:
    plan: PlanRow
    days: tuple[DayView, ...]
    done: int
    skipped: int
    left: int
    minutes_spent: int
    today: str


@dataclass(frozen=True)
class TodayView:
    """The Today's plan card (FR-10.65)."""

    plan_id: int
    today: str
    day: DayView | None  # None on a rest day
    next_date: str | None
    finished: bool  # every training day has passed


@dataclass(frozen=True)
class Preview:
    draft: PlanDraft
    report_id: int | None
    start_date: str
    dates: tuple[str, ...]
    replaces: bool  # a current plan would be replaced: confirm first


@dataclass(frozen=True)
class TaskAction:
    """What Start does (FR-10.63)."""

    kind: str  # session / retry / review / lesson / reflection
    task_id: int
    session: Any = None  # SessionInfo
    remaining: int | None = None  # puzzles left in this task
    mode: str | None = None
    game_id: int | None = None
    topic: str | None = None
    report_id: int | None = None
    prompt: str | None = None
    weakness_key: str | None = None
    plan_day_id: int | None = None


class PlanService:
    def __init__(
        self, plans: Any, passes: Any, reports: Any, games: Any, review: Any, sessions: Any, puzzles: Any,
        stats: Any, settings: Settings, engine: Any, game_puzzles: Any, account: Any, clock: Clock,
        puzzle_db: Any = None,
    ) -> None:  # fmt: skip
        self._puzzle_db = puzzle_db
        self._plans = plans
        self._passes = passes
        self._reports = reports
        self._games = games
        self._review = review
        self._sessions = sessions
        self._puzzles = puzzles
        self._stats = stats
        self._settings = settings
        self._engine = engine
        self._game_puzzles = game_puzzles
        self._account = account
        self._clock = clock

    def _now(self) -> str:
        return self._clock.now().astimezone(UTC).isoformat(timespec="seconds")

    def _today(self) -> date:
        return self._clock.local_date(self._clock.now())

    # ------------------------------------------------------------ settings

    def params(self) -> PlanParams:
        raw = self._settings.get(PARAMS_KEY)
        try:
            return PlanParams.from_json(raw) if isinstance(raw, dict) else PlanParams()
        except ValidationError:
            return PlanParams()

    def carry_over(self) -> bool:
        raw = self._settings.get(CARRY_KEY)
        return raw if isinstance(raw, bool) else True

    # ------------------------------------------------------------ building (FR-10.61, 10.62)

    def latest_report(self) -> Any:
        """Your latest Coach report. Another player's report never makes your plan."""
        return next((r for r in self._reports.recent() if r.subject == ME), None)

    def _report(self, report_id: Any) -> Any:
        if report_id is None:
            return self.latest_report()
        row = self._reports.get(report_id)
        return row if row is not None and row.subject == ME else None

    def _puzzle_minutes(self) -> float:
        avg = self._stats.recent_solve_ms(PUZZLE_MINUTES_SAMPLE)
        return round(avg / 60000, 2) if avg else DEFAULT_PUZZLE_MINUTES

    def _rating(self) -> int:
        rating = getattr(self._account.status(), "rating", None)
        return rating if isinstance(rating, int) and not isinstance(rating, bool) else DEFAULT_RATING

    def _label(self, game: Any) -> str:
        names = [n for n, c in ((game.black, "white"), (game.white, "black")) if c == game.user_color and n]
        played = (game.played_at or "")[:10]
        who = f"your game against {names[0]}" if names else "a game of yours"
        return f"{who} ({played})" if played else who

    def context(self, report: Any) -> Context:
        """What the builder needs besides the report, from the example games of the plan's weaknesses."""
        games: dict[int, str] = {}
        retry: set[int] = set()
        families: list[str] = []
        data = report.report if report is not None else {}
        for w in focus(data):
            for e in w.get("examples") or ():
                gid = e.get("game_id") if isinstance(e, dict) else None
                if not isinstance(gid, int) or gid in games:
                    continue
                g = self._games.get(gid)
                if g is None or g.analysis_status == "none":
                    continue
                games[gid] = self._label(g)
                if self._review.retry_plies(gid):
                    retry.add(gid)
        ms = data.get("measures") if isinstance(data, dict) else None
        for o in (ms or {}).get("openings") or ():
            if isinstance(o, dict) and o.get("family"):
                families.append(str(o["family"]))
        return Context(
            self._rating(), self._engine.status().state == "ready",
            any(s == "active" for *_, s in self._game_puzzles.coach_puzzles()), self._puzzle_minutes(), games,
            frozenset(retry), tuple(families),
        )  # fmt: skip

    def _puzzles_ready(self) -> bool:
        """QA v0.12-B13: a games-only Coach run needs no puzzle database, so a plan can be built without one."""
        return self._puzzle_db is None or bool(self._puzzle_db.status().installed)

    def _available(self, t: Task, memo: dict[str, int]) -> int:
        spec, _ = task_spec(t.type, t.params)
        key = repr(replace(spec, queue_size=None))
        if key not in memo:
            memo[key] = int(self._puzzles.count(spec))
        return memo[key]

    def fit_task(self, t: Task, ctx: Context, memo: dict[str, int] | None = None) -> Task:
        """A puzzle task needs enough puzzles. Its rating band widens, then opens up, before it gives way to
        the general session (so Start never meets *no puzzles match*)."""
        if t.type not in (PUZZLES, GAME_PUZZLES) or not self._puzzles_ready():
            return t
        memo = {} if memo is None else memo
        need = int(t.params.get("count") or 1)
        if self._available(t, memo) >= need:
            return t
        if t.type == GAME_PUZZLES:
            wider = replace(t, params={**t.params, "kinds": [], "severities": []})
            if self._available(wider, memo) >= need:
                return wider
        else:
            lo, hi = t.params.get("rating_min"), t.params.get("rating_max")
            if lo is not None and hi is not None:
                wider = replace(t, params={**t.params, "rating_min": max(400, lo - WIDEN), "rating_max": hi + WIDEN})
                if self._available(wider, memo) >= need:
                    return wider
            opened = replace(t, params={**t.params, "rating_min": None, "rating_max": None})
            if self._available(opened, memo) >= need:
                return opened
        general = general_task(ctx, t.minutes)
        open_general = replace(general, params={**general.params, "rating_min": None, "rating_max": None})
        return open_general

    def _fit(self, draft: PlanDraft, ctx: Context) -> PlanDraft:
        memo: dict[str, int] = {}
        days = tuple(replace(d, tasks=tuple(self.fit_task(t, ctx, memo) for t in d.tasks)) for d in draft.days)
        return replace(draft, days=days)

    def fit(self, draft: PlanDraft, ctx: Context) -> PlanDraft:
        """An AI plan's puzzle tasks need enough puzzles too."""
        return self._fit(draft, ctx)

    def game_for_task(self, game_id: int, kind: str) -> tuple[int, str] | None:
        """(id, short name) when this game can have this task type (FR-10.66): analyzed, and for Retry, with
        mistakes of yours."""
        g = self._games.get(game_id)
        if g is None or g.analysis_status == "none" or "me" not in self._games.subjects(game_id):
            return None
        if kind == RETRY and not self._review.retry_plies(game_id):
            return None
        return game_id, self._label(g)

    def build(self, report: Any, params: PlanParams) -> PlanDraft:
        data = report.report if report is not None else {}
        ctx = self.context(report)
        return self._fit(build_plan(data, params, ctx), ctx)

    def preview_replaces(self) -> bool:
        return self._plans.current() is not None

    def has_report(self) -> bool:
        return self.latest_report() is not None

    def preview(self, data: Any = None) -> Preview:
        """The plan these settings would make, not saved. It needs one report of yours."""
        params = PlanParams.from_json(data) if data is not None else self.params()
        report = self.latest_report()
        if report is None:
            raise ValidationError("Run the Coach first: a plan is built from your latest report.")
        return self._preview(self.build(report, params), report.id)

    def _preview(self, draft: PlanDraft, report_id: int | None) -> Preview:
        p = draft.params
        start = first_day(self._today(), p.weekdays)
        dates = training_dates(start, p.weekdays, p.weeks)
        return Preview(
            draft, report_id, start.isoformat(), tuple(d.isoformat() for _, d in dates),
            self._plans.current() is not None,
        )  # fmt: skip

    def create(self, data: Any, *, confirmed: bool = False) -> int:
        """Build and start a plan. It replaces the current one only when you confirm (FR-10.65)."""
        pv = self.preview(data)
        self._check_replace(confirmed)
        self._settings.set(PARAMS_KEY, pv.draft.params.to_json())
        return self._store(pv.draft, pv.report_id, "deterministic", None)

    def use_draft(self, draft: PlanDraft, report_id: int | None, ai_run_id: int | None, *, confirmed: bool) -> int:
        """Use this plan (FR-10.66): a stored AI plan becomes current."""
        self._check_replace(confirmed)
        return self._store(draft, report_id, "ai", ai_run_id)

    def _check_replace(self, confirmed: bool) -> None:
        if self._plans.current() is not None and not confirmed:
            raise ConflictError("Confirm first: this replaces your current plan.", retryable=False)

    def _store(self, draft: PlanDraft, report_id: int | None, source: str, ai_run_id: int | None) -> int:
        p = draft.params
        start = first_day(self._today(), p.weekdays)
        dates = [d for _, d in training_dates(start, p.weekdays, p.weeks)]
        return int(self._plans.add(draft, dates, self._now(), report_id=report_id, source=source, ai_run_id=ai_run_id))

    # ------------------------------------------------------------ what the app saw (FR-10.64)

    def _facts(self, plan: PlanRow) -> Facts:
        tasks = [t for d in plan.days for t in d.tasks]
        until = plan.ended_at  # QA v0.12-B9: an ended plan stays as it was
        raw = self._plans.attempt_facts(until)
        attempts: dict[int, int] = {}
        seconds: dict[int, int] = {}
        by_id = {t.id: t for t in tasks}
        for t in sorted(tasks, key=lambda x: x.id):  # a carried task keeps the progress of the one it copies
            n, ms = raw.get(t.id, (0, 0))
            source = by_id.get(t.carried_from) if t.carried_from is not None else None
            attempts[t.id] = n + (attempts.get(source.id, 0) if source else 0)
            seconds[t.id] = round(ms / 1000)  # QA v0.12-B5: a copy keeps the progress, not the time spent
        swapped = sum(raw.get(i, (0, 0))[1] for i in self._plans.swapped_task_ids(plan.id))
        # QA v0.12-B34: once a task has a copy the copy is the task, so an entry saved from the original counts for it.
        entries = set(self._plans.entry_tasks(until))
        for t in sorted(tasks, key=lambda x: x.id):
            if t.carried_from in entries:
                entries.add(t.id)
        retry_games = {int(t.params["game_id"]) for t in tasks if t.type == RETRY and isinstance(t.params.get("game_id"), int)}  # fmt: skip
        needed = {g: frozenset(self._review.retry_plies(g)) for g in retry_games}
        return Facts(
            attempts=attempts,
            seconds=seconds,
            carried=frozenset(t.carried_from for t in tasks if t.carried_from is not None),
            swapped_seconds=round(swapped / 1000),
            retry_needed=needed,
            retry_tried=self._plans.retries_since(sorted(retry_games), plan.created_at, until),
            reviewed_tasks=self._passes.completed_tasks(until),
            reviewed_games=self._passes.completed_games(plan.created_at, until),
            entry_tasks=frozenset(entries),
        )

    def _sync(self, plan: PlanRow) -> tuple[PlanRow, Facts]:
        """Store what's newly done, then carry over, once per training day and safe to repeat."""
        facts = self._facts(plan)
        fresh = [t.id for d in plan.days for t in d.tasks if t.done_at is None and auto_done(t, facts)]
        if fresh:
            self._plans.set_done(fresh, self._now())
        if plan.status == "current" and self.carry_over():
            found = to_carry(plan, self._today(), facts)
            if found is not None:
                self._plans.carry(found[0].id, found[1])
        if not fresh and (plan.status != "current" or not self.carry_over()):
            return plan, facts
        again = self._plans.get(plan.id)
        return again, self._facts(again)

    def _view(self, plan: PlanRow) -> PlanView:
        plan, facts = self._sync(plan)
        today = self._today()
        carried = frozenset(t.carried_from for d in plan.days for t in d.tasks if t.carried_from is not None)
        days: list[DayView] = []
        counts = {"done": 0, "skipped": 0, "left": 0}
        spent = round(facts.swapped_seconds / 60)
        for d in plan.days:
            views: list[TaskView] = []
            for t in d.tasks:
                st = status_of(t, d.date, today, facts, carried)
                minutes = task_minutes(t, facts)
                spent += minutes
                views.append(
                    TaskView(t, st, auto_done(t, facts),
                             facts.attempts.get(t.id, 0) if t.type in (PUZZLES, GAME_PUZZLES) else None, minutes)
                )  # fmt: skip
                if st == "done":
                    counts["done"] += 1
                elif st == "skipped":
                    counts["skipped"] += 1
                elif st == "left":
                    counts["left"] += 1
            days.append(DayView(d, tuple(views), d.date == today.isoformat()))
        return PlanView(plan, tuple(days), counts["done"], counts["skipped"], counts["left"], spent, today.isoformat())

    def current(self) -> PlanView | None:
        plan = self._plans.current()
        return self._view(plan) if plan is not None else None

    def today(self) -> TodayView | None:
        view = self.current()
        if view is None:
            return None
        iso = view.today
        day = next((d for d in view.days if d.day.date == iso), None)
        later = [d.day.date for d in view.days if d.day.date > iso]
        return TodayView(view.plan.id, iso, day, later[0] if later else None, not later and day is None)

    def history(self) -> list[PlanView]:
        return [self._view(p) for p in self._plans.history()]

    # ------------------------------------------------------------ ticks, skip, swap

    def _place(self, task_id: Any) -> Any:
        if not isinstance(task_id, int) or isinstance(task_id, bool):
            raise ValidationError("task_id must be a whole number")
        place = self._plans.place(task_id)
        if place is None:
            raise NotFoundError("That task isn't in your plan.")
        current = self._plans.current()
        if current is None or current.id != place.plan_id:
            raise ConflictError("That plan has ended: open your current plan.", retryable=False)
        return place

    def set_tick(self, task_id: Any, done: Any) -> None:
        """Your hand tick or untick (FR-10.64). It always wins over what the app saw."""
        if not isinstance(done, bool):
            raise ValidationError("done must be true or false")
        self._place(task_id)
        # QA v0.12-B32: once a task has a copy the copy is the task, so one task can't be settled twice.
        self._plans.set_manual(self._plans.live_copy(task_id), "done" if done else "undone", self._now())

    def skip(self, task_id: Any, skipped: Any = True) -> None:
        if not isinstance(skipped, bool):
            raise ValidationError("skipped must be true or false")
        self._place(task_id)
        self._plans.set_skipped(task_id, self._now() if skipped else None)

    def swap(self, task_id: Any) -> int:
        place = self._place(task_id)
        t = place.task
        report = self._report_for_plan(place.plan_id)
        data = report.report if report is not None else {}
        ctx = self.context(report)
        old = Task(t.type, t.minutes, t.title, t.params, t.weakness_key)
        today = [Task(x.type, x.minutes, x.title, x.params, x.weakness_key) for x in place.day.tasks if x.id != t.id]
        return self._swap_in(t.id, place.plan_id, old, data, ctx, today)

    def _swap_in(self, task_id: int, plan_id: int, old: Task, data: Any, ctx: Context, today: list[Task]) -> int:
        """QA v0.12-B11, B22: what this slot has been counts, so Swap keeps moving on, and when it's been everything it
        starts over. Fitting can turn a task into another one, so the result is checked after that."""
        been = self._plans.swapped_away(task_id)
        spent = self._spent(plan_id, task_id)
        fitted = [f for f in (self.fit_task(t, ctx) for t in swap_choices(old, data, ctx)) if not spent(f)]
        for f in fitted:
            if not any(same_task(f, x) for x in [old, *today, *been]):
                return int(self._plans.swap(task_id, f))
        # Starting over goes on from where this slot is in the list: from the top, it would bounce between two tasks.
        at = max((i for i, f in enumerate(fitted) if same_task(f, old)), default=-1)
        for f in [*fitted[at + 1 :], *fitted[: at + 1]]:
            if not any(same_task(f, x) for x in [old, *today]):
                return int(self._plans.swap(task_id, f))
        return int(self._plans.swap(task_id, old))  # nothing else fits a full day: it stays as it was

    def _spent(self, plan_id: int, task_id: int) -> Callable[[Task], bool]:
        """QA v0.12-B35: a game or lesson is used once per plan, and a game you've finished would tick itself at once."""
        plan = self._plans.get(plan_id)
        facts = self._facts(plan)
        once = (RETRY, REVIEW, LESSON)
        rest = [t for d in plan.days for t in d.tasks if t.id != task_id and t.type in once]
        used = {(t.type, json.dumps(t.params, sort_keys=True)) for t in rest}

        def spent(t: Task) -> bool:
            if t.type not in once:
                return False
            if (t.type, json.dumps(t.params, sort_keys=True)) in used:
                return True
            gid = t.params.get("game_id")
            if t.type == REVIEW:
                return gid in facts.reviewed_games
            if t.type == RETRY and isinstance(gid, int):
                needed = frozenset(self._review.retry_plies(gid))
                tried = self._plans.retries_since([gid], plan.created_at, plan.ended_at).get(gid, frozenset())
                return bool(needed) and needed <= tried
            return False

        return spent

    def _report_for_plan(self, plan_id: int) -> Any:
        plan = self._plans.get(plan_id)
        report = self._reports.get(plan.report_id) if plan is not None and plan.report_id is not None else None
        return report if report is not None else self.latest_report()

    # ------------------------------------------------------------ Start (FR-10.63)

    def start_task(self, task_id: Any, rated: bool = True) -> TaskAction:
        place = self._place(task_id)
        t = place.task
        if t.type in (PUZZLES, GAME_PUZZLES):
            return self._start_session(place, rated)
        gid = t.params.get("game_id")
        if t.type in (RETRY, REVIEW):
            if not isinstance(gid, int) or self._games.get(gid) is None:
                raise NotFoundError("That game is no longer in your library. Swap or skip this task.")
            if t.type == REVIEW:
                self._passes.start(gid, t.id, self._now())
            return TaskAction(t.type, t.id, game_id=gid)
        if t.type == LESSON:
            report = self._report_for_plan(place.plan_id)
            return TaskAction(LESSON, t.id, topic=str(t.params.get("topic")), report_id=report.id if report else None)
        if t.type == REFLECTION:
            return TaskAction(
                REFLECTION, t.id, prompt=str(t.params.get("prompt") or ""), game_id=gid if isinstance(gid, int) else None,
                weakness_key=t.weakness_key, plan_day_id=place.day.id,
            )  # fmt: skip
        raise ValidationError("Unknown task type.")

    def _start_session(self, place: Any, rated: bool) -> TaskAction:
        t = place.task
        if not self._puzzles_ready():
            raise ValidationError("Import the puzzle database first: this task needs its puzzles.")
        plan = self._plans.get(place.plan_id)
        facts = self._facts(plan)
        left = max(1, int(t.params.get("count") or 1) - facts.attempts.get(t.id, 0))
        spec, mode = task_spec(t.type, t.params, left)
        info = self._sessions.start(spec, bool(rated), mode, False)
        self._plans.link_session(info.session_id, t.id)
        return TaskAction("session", t.id, session=info, remaining=left, mode=mode)

    def lesson_ref(self, task_id: Any) -> tuple[int, str]:
        """(report id, topic) of a lesson task: the backend builds the link from these (FR-10.59)."""
        place = self._place(task_id)
        if place.task.type != LESSON:
            raise ValidationError("This task isn't a lesson.")
        report = self._report_for_plan(place.plan_id)
        if report is None:
            raise NotFoundError("The report behind this lesson is gone. Swap or skip this task.")
        return int(report.id), str(place.task.params.get("topic"))

    def lesson_opened(self, task_id: Any) -> None:
        """FR-10.64 (v0.12 planning): a lesson task ticks when you open one of its links or start its drill."""
        self._place(task_id)
        self._plans.set_done([self._plans.live_copy(task_id)], self._now())  # QA v0.12-B34: the copy is the task

    def start_lesson_drill(self, task_id: Any, rated: bool = True) -> TaskAction:
        """Learn X from a task: its puzzles for this session only (FR-10.63), never through your filters."""
        place = self._place(task_id)
        t = place.task
        if not self._puzzles_ready():  # QA v0.12-B29
            raise ValidationError("Import the puzzle database first: this drill needs its puzzles.")
        report = self._report_for_plan(place.plan_id)
        families = _families(report)
        found = topic(str(t.params.get("topic")), families)
        preset = drill_preset(found, self._rating()) if found is not None else None
        if preset is None:
            raise ValidationError("This lesson has no drill.")
        spec = FilterSpec(
            themes=tuple(preset["themes"]), rating_min=preset["rating_min"], rating_max=preset["rating_max"],  # type: ignore[arg-type]
            queue_size=preset["queue_size"],  # type: ignore[arg-type]
        )  # fmt: skip
        if self._puzzles.count(spec) == 0:
            spec = replace(spec, rating_min=None, rating_max=None)
        info = self._sessions.start(spec, bool(rated), "standard", False)
        self._plans.link_session(info.session_id, t.id)
        self.lesson_opened(task_id)
        return TaskAction("session", t.id, session=info, remaining=spec.queue_size, mode="standard")

    # ------------------------------------------------------------ for AI coaching (FR-10.66)

    def progress(self) -> dict[str, Any] | None:
        """How the current plan is going, as aggregates only."""
        plan = self._plans.current()
        if plan is None:
            return None
        plan, facts = self._sync(plan)
        themes: dict[str, tuple[int, int]] = {}
        for row in self._stats.attempt_rows_for_tasks(self._plans.task_ids_with_sessions(plan.id)):
            if row.misclick or not row.themes:
                continue
            for th in dict.fromkeys(row.themes):
                a, w = themes.get(th, (0, 0))
                themes[th] = (a + 1, w + int(row.win))
        return plan_progress(plan, self._today(), facts, themes)


def _families(report: Any) -> list[str]:
    ms = report.report.get("measures") if report is not None and isinstance(report.report, dict) else None
    return [str(o.get("family")) for o in (ms or {}).get("openings") or () if isinstance(o, dict)]
