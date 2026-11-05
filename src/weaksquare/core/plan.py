"""The training plan (v0.12, REQUIREMENTS §10.12, FR-10.61–10.66). Pure: no I/O and no clock.

**Building a plan (FR-10.61, 10.62).** The minutes of the whole plan are shared out by weakness score, so
the top weaknesses get the most time. Each training day has 2–4 equal slots that add up to your minutes, and
each slot goes to the weakness with the most minutes still owed. A weakness turns into tasks through
`_options`; every task is of a closed list of types, so it's always something the app can open. The same
inputs always make the same plan.

**Ticks (FR-10.64).** What the app saw is worked out from stored events when the plan is read (`auto_done`),
and `is_done` applies the rule that a hand choice always wins.

**Carry-over (FR-10.64).** On a training day, the last training day's unfinished tasks are copied in, up to
one day's worth (`to_carry`). It's safe to repeat: a task that already has a copy is never copied again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from weaksquare.core import themes
from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.lessons import topic as lesson_topic

PUZZLES, GAME_PUZZLES, RETRY, REVIEW, LESSON, REFLECTION = (
    "puzzles", "game_puzzles", "retry", "review", "lesson", "reflection",
)  # fmt: skip
TASK_TYPES = (PUZZLES, GAME_PUZZLES, RETRY, REVIEW, LESSON, REFLECTION)
MODES = ("standard", "commit_line", "name_idea", "danger_spotting")
SEVERITIES = ("blunder", "mistake", "inaccuracy")
WEEKS_MIN, WEEKS_MAX = 1, 4
MINUTES_MIN, MINUTES_MAX = 10, 120
DEFAULT_WEEKDAYS = (0, 1, 2, 3, 4)  # Monday to Friday
DEFAULT_PUZZLE_MINUTES = 1.5  # until you have enough attempts of your own
PUZZLE_MINUTES_SAMPLE = 50
MAX_FOCUS = 5
MAX_PUZZLE_COUNT = 100
RATING_BAND = 150
MODE_LABELS = {
    "standard": "",
    "commit_line": "Commit-the-line ",
    "name_idea": "Name-the-idea ",
    "danger_spotting": "Danger-spotting ",
}
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class PlanParams:
    weeks: int = 2
    weekdays: tuple[int, ...] = DEFAULT_WEEKDAYS  # Monday = 0 (Adam, v0.12 planning)
    minutes: int = 20

    @classmethod
    def from_json(cls, data: Any) -> PlanParams:
        if not isinstance(data, Mapping) or set(data) - {"weeks", "weekdays", "minutes"}:
            raise ValidationError("Unknown plan settings.")
        weeks, minutes = data.get("weeks", 2), data.get("minutes", 20)
        days = data.get("weekdays", list(DEFAULT_WEEKDAYS))
        if not _whole(weeks) or not WEEKS_MIN <= weeks <= WEEKS_MAX:
            raise ValidationError(f"A plan lasts {WEEKS_MIN}–{WEEKS_MAX} weeks.")
        if not _whole(minutes) or not MINUTES_MIN <= minutes <= MINUTES_MAX:
            raise ValidationError(f"Minutes per day must be {MINUTES_MIN}–{MINUTES_MAX}.")
        if not isinstance(days, list | tuple) or not days or not all(_whole(d) and 0 <= d <= 6 for d in days):
            raise ValidationError("Pick at least one training day.")
        return cls(weeks, tuple(sorted(set(days))), minutes)

    def to_json(self) -> dict[str, Any]:
        return {"weeks": self.weeks, "weekdays": list(self.weekdays), "minutes": self.minutes}

    @property
    def task_slots(self) -> int:
        """FR-10.62: 2–4 tasks a day, more when you have more time."""
        return 2 if self.minutes < 25 else 3 if self.minutes < 50 else 4


def _whole(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class Task:
    type: str
    minutes: int
    title: str
    params: dict[str, Any]
    weakness_key: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type, "minutes": self.minutes, "title": self.title, "params": self.params,
            "weakness_key": self.weakness_key,
        }  # fmt: skip

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Task:
        return cls(str(d["type"]), int(d["minutes"]), str(d["title"]), dict(d["params"]), d.get("weakness_key"))


@dataclass(frozen=True)
class Day:
    week: int  # 1-based
    position: int  # 1-based within the plan
    tasks: tuple[Task, ...]

    def to_json(self) -> dict[str, Any]:
        return {"week": self.week, "position": self.position, "tasks": [t.to_json() for t in self.tasks]}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Day:
        return cls(int(d["week"]), int(d["position"]), tuple(Task.from_json(t) for t in d["tasks"]))


@dataclass(frozen=True)
class PlanDraft:
    """A plan before it has dates: what a preview shows and what an AI run stores."""

    params: PlanParams
    days: tuple[Day, ...]

    def to_json(self) -> dict[str, Any]:
        return {"params": self.params.to_json(), "days": [d.to_json() for d in self.days]}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> PlanDraft:
        return cls(PlanParams.from_json(d["params"]), tuple(Day.from_json(x) for x in d["days"]))


@dataclass(frozen=True)
class Context:
    """What the plan needs to know besides the report. `games` maps an analyzed game to its short label;
    `retry_games` holds the games that have mistakes to retry."""

    rating: int = 1500
    engine_ready: bool = False
    has_game_puzzles: bool = False
    puzzle_minutes: float = DEFAULT_PUZZLE_MINUTES
    games: Mapping[int, str] = field(default_factory=dict)
    retry_games: frozenset[int] = frozenset()
    families: tuple[str, ...] = ()


# ------------------------------------------------------------ dates


def first_day(today: date, weekdays: Sequence[int]) -> date:
    """The plan starts today if today is a picked day, otherwise on the next one (Adam, v0.12 planning)."""
    for offset in range(7):
        d = today + timedelta(days=offset)
        if d.weekday() in weekdays:
            return d
    raise ValidationError("Pick at least one training day.")


def training_dates(start: date, weekdays: Sequence[int], weeks: int) -> list[tuple[int, date]]:
    """(1-based week, date) of every training day. Each week is the 7 days from the start, so each has
    exactly as many training days as you picked."""
    out: list[tuple[int, date]] = []
    for w in range(weeks):
        window = [start + timedelta(days=7 * w + i) for i in range(7)]
        out += [(w + 1, d) for d in window if d.weekday() in weekdays]
    return out


# ------------------------------------------------------------ what a weakness turns into


def _themes_of(w: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(t for t in w.get("themes") or () if isinstance(t, str) and themes.is_known(t))


def _lesson_id(w: Mapping[str, Any]) -> str | None:
    key = str(w.get("key") or "")
    kind, _, name = key.partition(":")
    if kind in ("missed", "allowed", "puzzle"):
        return f"theme:{name}"
    if kind in ("opening", "endgame"):
        return key
    fixed = {
        "phase:conversion": "concept:conversion",
        "time:low_clock": "concept:timeManagement",
        "habit:castledLate": "concept:kingSafety",
    }
    return fixed.get(key, "concept:blunderCheck" if kind == "habit" else None)


def _example_games(w: Mapping[str, Any]) -> list[int]:
    out: list[int] = []
    for e in w.get("examples") or ():
        gid = e.get("game_id") if isinstance(e, Mapping) else None
        if isinstance(gid, int) and not isinstance(gid, bool) and gid not in out:
            out.append(gid)
    return out


def puzzle_task(
    ctx: Context, minutes: int, key: str | None, name: str, *, picked: Sequence[str] = (), mode: str = "standard",
    rating_min: int | None = None, rating_max: int | None = None, count: int | None = None,
) -> Task:  # fmt: skip
    n = count if count is not None else fit_count(minutes, ctx.puzzle_minutes)
    if rating_min is None and rating_max is None:
        rating_min, rating_max = max(400, ctx.rating - RATING_BAND), ctx.rating + RATING_BAND
    params = {"themes": list(picked), "mode": mode, "count": n, "rating_min": rating_min, "rating_max": rating_max}
    label = f"{n} {MODE_LABELS.get(mode, '')}puzzle{'s' if n != 1 else ''}"
    return Task(PUZZLES, minutes, f"{label}: {name}" if name else label, params, key)


def game_puzzle_task(
    ctx: Context, minutes: int, key: str | None, severities: Sequence[str] = ("blunder", "mistake"),
    kinds: Sequence[str] = (), count: int | None = None,
) -> Task:  # fmt: skip
    n = count if count is not None else fit_count(minutes, ctx.puzzle_minutes)
    what = " and ".join(f"{s}s" for s in severities)
    return Task(
        GAME_PUZZLES, minutes, f"{n} puzzle{'s' if n != 1 else ''} from your games: {what}",
        {"severities": list(severities), "kinds": list(kinds), "count": n}, key,
    )  # fmt: skip


def retry_task(ctx: Context, minutes: int, key: str | None, game_id: int) -> Task:
    return Task(RETRY, minutes, f"Retry your mistakes in {_game(ctx, game_id)}", {"game_id": game_id}, key)


def review_task(ctx: Context, minutes: int, key: str | None, game_id: int) -> Task:
    return Task(REVIEW, minutes, f"Review {_game(ctx, game_id)} with best moves hidden", {"game_id": game_id}, key)


def lesson_task(ctx: Context, minutes: int, key: str | None, topic_id: str) -> Task | None:
    t = lesson_topic(topic_id, ctx.families)
    return None if t is None else Task(LESSON, minutes, f"Lesson: {t.label}", {"topic": t.id}, key)


def reflection_task(minutes: int, key: str | None, prompt: str, game_id: int | None = None) -> Task:
    params: dict[str, Any] = {"prompt": prompt}
    if game_id is not None:
        params["game_id"] = game_id
    return Task(REFLECTION, minutes, f"Reflection: {prompt}", params, key)


def _game(ctx: Context, game_id: int) -> str:
    return ctx.games.get(game_id, "a game of yours")


def fit_count(minutes: int, puzzle_minutes: float) -> int:
    """As many puzzles as fit, at least one."""
    return max(1, min(MAX_PUZZLE_COUNT, int(minutes / max(puzzle_minutes, 0.1))))


def _options(w: Mapping[str, Any], minutes: int, ctx: Context) -> list[Task]:
    """A weakness's tasks, in the order they're offered. FR-10.62's closed list only."""
    key = str(w.get("key"))
    label = str(w.get("label") or key)
    kind = str(w.get("kind") or key.partition(":")[0])
    games = [g for g in _example_games(w) if g in ctx.games]
    retries = [retry_task(ctx, minutes, key, g) for g in games if g in ctx.retry_games]
    reviews = [review_task(ctx, minutes, key, g) for g in games]
    lid = _lesson_id(w)
    lesson = lesson_task(ctx, minutes, key, lid) if lid else None
    lessons = [lesson] if lesson is not None else []
    picked = _themes_of(w)
    names = ", ".join(themes.display_name(t) for t in picked[:3])
    mode = w.get("mode") if w.get("mode") in MODES else "standard"
    if mode == "danger_spotting" and not ctx.engine_ready:  # FR-4.4: it needs Stockfish
        mode = "standard"
    puzzles = [puzzle_task(ctx, minutes, key, names, picked=picked, mode=str(mode))] if picked else []
    if key in ("time:low_clock", "habit:castledLate"):
        prompt = f"What would you do differently about: {label}?"
        return [*reviews[:2], *lessons, reflection_task(minutes, key, prompt), *reviews[2:], *puzzles]
    if kind == "opening":
        prompt = f"What was your plan coming out of the {w.get('name') or 'opening'}?"
        return [*reviews[:2], *lessons, reflection_task(minutes, key, prompt), *reviews[2:]]
    if key == "phase:conversion":
        return [*reviews[:2], *puzzles, *lessons, *reviews[2:]]
    if kind == "endgame":
        return [*puzzles, *lessons, *reviews]
    if kind in ("missed", "allowed", "habit"):
        my = [game_puzzle_task(ctx, minutes, key, kinds=(kind,) if kind != "habit" else ())] if ctx.has_game_puzzles else []  # fmt: skip
        return [*puzzles, *my, *retries[:1], *lessons, *reviews[:1], *retries[1:], *reviews[1:]]
    return [*puzzles, *lessons]  # puzzle weaknesses have no games


def focus(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The weaknesses a plan works on, worst first: the tactical top list plus the whole-game ones."""
    seen: dict[str, Mapping[str, Any]] = {}
    for group in ("weaknesses", "whole_game"):
        for w in report.get(group) or ():
            if isinstance(w, Mapping) and isinstance(w.get("key"), str):
                seen.setdefault(w["key"], w)
    ranked = sorted(seen.values(), key=lambda w: (-float(w.get("score") or 0), str(w["key"])))
    return ranked[:MAX_FOCUS]


def _share(total: int, weights: Sequence[float]) -> list[int]:
    """`total` minutes by weight, largest remainder first, so they add up exactly."""
    whole = sum(weights)
    if whole <= 0:
        weights, whole = [1.0] * len(weights), float(len(weights))
    raw = [total * w / whole for w in weights]
    out = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (out[i] - raw[i], i))
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def slots_for(minutes: int, n: int) -> list[int]:
    return _share(minutes, [1.0] * n)


def _same(a: Task, b: Task) -> bool:
    return a.type == b.type and _core(a) == _core(b)


def _core(t: Task) -> dict[str, Any]:
    """What makes a task "the same" regardless of its size."""
    return {k: v for k, v in t.params.items() if k != "count"}


def _resized(t: Task, minutes: int, ctx: Context) -> Task:
    if t.type == PUZZLES:
        p = t.params
        name = ", ".join(themes.display_name(x) for x in (p.get("themes") or ())[:3])
        return puzzle_task(ctx, minutes, t.weakness_key, name, picked=p.get("themes") or (), mode=p.get("mode", "standard"),
                           rating_min=p.get("rating_min"), rating_max=p.get("rating_max"))  # fmt: skip
    if t.type == GAME_PUZZLES:
        return game_puzzle_task(ctx, minutes, t.weakness_key, t.params.get("severities") or (),
                                t.params.get("kinds") or ())  # fmt: skip
    return Task(t.type, minutes, t.title, t.params, t.weakness_key)


def general_task(ctx: Context, minutes: int) -> Task:
    """The fallback every plan can always use: puzzles around your rating, any theme."""
    return puzzle_task(ctx, minutes, None, "any theme")


def build_plan(report: Mapping[str, Any], params: PlanParams, ctx: Context) -> PlanDraft:
    """FR-10.61, 10.62: the deterministic plan. It's never empty: with no weaknesses it's a general mix."""
    weak = focus(report)
    day_count = params.weeks * len(params.weekdays)
    slots = slots_for(params.minutes, params.task_slots)
    # Smooth weighted round-robin: each slot adds every weakness's share to its credit and goes to the highest
    # credit. Time follows the score exactly, and the weaknesses stay mixed across the days.
    total = sum(max(float(w.get("score") or 0), 0.01) for w in weak)
    weight = {str(w["key"]): max(float(w.get("score") or 0), 0.01) / total for w in weak}
    credit = dict.fromkeys(weight, 0.0)
    cursor: dict[str, int] = {}
    used: set[tuple[str, Any]] = set()
    days: list[Day] = []
    per_week = len(params.weekdays)
    for i in range(day_count):
        week = i // per_week + 1
        last_of_week = (i + 1) % per_week == 0
        tasks: list[Task] = []
        for n, minutes in enumerate(slots):
            if last_of_week and n == len(slots) - 1:  # one reflection a week (FR-10.62)
                tasks.append(_weekly_reflection(weak, minutes, week))
                continue
            for key in credit:
                credit[key] += weight[key]
            task = None
            # The highest credit first; a weakness with nothing left to offer gives way to the next one.
            for key in sorted(credit, key=lambda k: -credit[k]):
                w = next(x for x in weak if x["key"] == key)
                task = _pick(w, minutes, ctx, cursor, used, tasks)
                if task is not None:
                    credit[key] -= 1
                    break
            tasks.append(task if task is not None else general_task(ctx, minutes))
        days.append(Day(week, i + 1, tuple(tasks)))
    return PlanDraft(params, tuple(days))


def _weekly_reflection(weak: Sequence[Mapping[str, Any]], minutes: int, week: int) -> Task:
    if not weak:
        return reflection_task(minutes, None, f"What went well in week {week}, and what will you change?")
    w = weak[(week - 1) % len(weak)]
    return reflection_task(minutes, str(w["key"]), f"How is this going: {w.get('label') or w['key']}?")


def _pick(
    w: Mapping[str, Any], minutes: int, ctx: Context, cursor: dict[str, int], used: set[tuple[str, Any]],
    today: Sequence[Task],
) -> Task | None:  # fmt: skip
    key = str(w["key"])
    opts = _options(w, minutes, ctx)
    if not opts:
        return None
    start = cursor.get(key, 0)
    for step in range(len(opts)):
        at = (start + step) % len(opts)
        t = opts[at]
        once = _once_key(t)
        if once is not None and once in used:
            continue
        if any(_same(t, x) for x in today):
            continue
        cursor[key] = at + 1
        if once is not None:
            used.add(once)
        return t
    return None


def _once_key(t: Task) -> tuple[str, Any] | None:
    """Games and lessons are used once per plan; puzzle sessions can repeat."""
    if t.type in (RETRY, REVIEW):
        return (t.type, t.params.get("game_id"))
    if t.type == LESSON:
        return (LESSON, t.params.get("topic"))
    if t.type == REFLECTION:
        return (REFLECTION, t.params.get("prompt"))
    return None


def swap_for(task: Task, report: Mapping[str, Any], ctx: Context, today: Sequence[Task]) -> Task:
    """FR-10.64 Swap: the next task for the same weakness, otherwise for the next weakness, otherwise general
    puzzles. Deterministic. Never one already on the day, or the task being swapped."""
    weak = focus(report)
    ordered = [w for w in weak if w["key"] == task.weakness_key] + [w for w in weak if w["key"] != task.weakness_key]
    taken = [*today, task]
    for w in ordered:
        for t in _options(w, task.minutes, ctx):
            if not any(_same(t, x) or t.title == x.title for x in taken):
                return t
    general = general_task(ctx, task.minutes)
    return general if not any(_same(general, x) or general.title == x.title for x in taken) else reflection_task(
        task.minutes, task.weakness_key, "What's the one thing to remember from today?"
    )  # fmt: skip


def resize(task: Task, minutes: int, ctx: Context) -> Task:
    return _resized(task, minutes, ctx)


# ------------------------------------------------------------ a puzzle task as filters (FR-10.63)


def task_spec(task_type: str, params: Mapping[str, Any], count: int | None = None) -> tuple[FilterSpec, str]:
    """A puzzle task's filters and mode, built from the defaults: never from your Mixer filters, which it
    must not change. Raises ValidationError on anything FilterSpec refuses."""
    n = count if count is not None else int(params.get("count") or 10)
    if task_type == GAME_PUZZLES:
        spec = FilterSpec(
            source="my", my_severities=tuple(params.get("severities") or ()), my_kinds=tuple(params.get("kinds") or ()),
            queue_size=n,
        )  # fmt: skip
        spec.validate()
        return spec, "standard"
    if task_type != PUZZLES:
        raise ValidationError("This task isn't a puzzle session.")
    mode = str(params.get("mode") or "standard")
    if mode not in MODES:
        raise ValidationError("Unknown training mode.")
    spec = FilterSpec(
        themes=tuple(params.get("themes") or ()), rating_min=params.get("rating_min"),
        rating_max=params.get("rating_max"), queue_size=n,
    )  # fmt: skip
    spec.validate()
    return spec, mode


# ------------------------------------------------------------ the stored plan


@dataclass(frozen=True)
class TaskRow:
    id: int
    day_id: int
    position: int
    type: str
    weakness_key: str | None
    minutes: int
    title: str
    params: dict[str, Any]
    manual_state: str | None  # done / undone: your hand choice
    skipped_at: str | None
    done_at: str | None  # when the app first saw it done
    carried_from: int | None
    swapped_from: int | None


@dataclass(frozen=True)
class DayRow:
    id: int
    plan_id: int
    week: int
    position: int
    date: str  # ISO, local
    tasks: tuple[TaskRow, ...]


@dataclass(frozen=True)
class PlanRow:
    id: int
    created_at: str
    report_id: int | None
    source: str  # deterministic / ai
    ai_run_id: int | None
    params: PlanParams
    start_date: str
    status: str  # current / replaced
    ended_at: str | None
    days: tuple[DayRow, ...]


@dataclass(frozen=True)
class Facts:
    """What the app saw, from stored events (FR-10.64)."""

    attempts: Mapping[int, int] = field(default_factory=dict)  # task id → decided attempts in its sessions
    retry_tried: Mapping[int, frozenset[int]] = field(
        default_factory=dict
    )  # game id → plies tried since the plan began
    retry_needed: Mapping[int, frozenset[int]] = field(default_factory=dict)  # game id → your mistakes' plies
    reviewed_tasks: frozenset[int] = frozenset()  # tasks whose game was stepped through
    reviewed_games: frozenset[int] = frozenset()  # games stepped through since the plan began
    entry_tasks: frozenset[int] = frozenset()  # tasks a journal entry was saved from
    seconds: Mapping[int, int] = field(default_factory=dict)  # task id → solving time in its sessions


def auto_done(t: TaskRow, f: Facts) -> bool:
    """Did the app see this task done? (FR-10.64.) A lesson's `done_at` is set when you open it."""
    if t.done_at is not None:
        return True
    if t.type in (PUZZLES, GAME_PUZZLES):
        return f.attempts.get(t.id, 0) >= int(t.params.get("count") or 1)
    gid = t.params.get("game_id")
    if t.type == RETRY:
        needed = f.retry_needed.get(gid, frozenset()) if isinstance(gid, int) else frozenset()
        return bool(needed) and needed <= f.retry_tried.get(gid, frozenset())  # type: ignore[arg-type]
    if t.type == REVIEW:
        return t.id in f.reviewed_tasks or gid in f.reviewed_games
    if t.type == REFLECTION:
        return t.id in f.entry_tasks
    return False


def is_done(t: TaskRow, f: Facts) -> bool:
    """A hand tick counts whatever the app saw; a box you unticked stays unticked (FR-10.64)."""
    if t.manual_state == "done":
        return True
    if t.manual_state == "undone":
        return False
    return auto_done(t, f)


LEFT, DONE, SKIPPED, CARRIED, MISSED = "left", "done", "skipped", "carried", "missed"


def status_of(t: TaskRow, day_date: str, today: date, f: Facts, carried: frozenset[int]) -> str:
    if is_done(t, f):
        return DONE
    if t.skipped_at is not None:
        return SKIPPED
    if t.id in carried:
        return CARRIED
    return MISSED if date.fromisoformat(day_date) < today else LEFT


def to_carry(plan: PlanRow, today: date, f: Facts) -> tuple[DayRow, list[TaskRow]] | None:
    """FR-10.64: (today's day, the unfinished tasks of the last training day to copy to it), at most one
    day's worth. None on a rest day, or when there's nothing to carry."""
    iso = today.isoformat()
    current = next((d for d in plan.days if d.date == iso), None)
    earlier = [d for d in plan.days if d.date < iso]
    if current is None or not earlier:
        return None
    last = max(earlier, key=lambda d: d.date)
    copied = {t.carried_from for d in plan.days for t in d.tasks if t.carried_from is not None}
    out: list[TaskRow] = []
    # QA v0.12-B1: what's already on today counts, so reading the plan again never carries more.
    room = plan.params.minutes - sum(t.minutes for t in current.tasks if t.carried_from is not None)
    for t in last.tasks:
        if is_done(t, f) or t.skipped_at is not None or t.id in copied:
            continue
        if t.minutes <= room:
            out.append(t)
            room -= t.minutes
    return (current, out) if out else None


def task_minutes(t: TaskRow, f: Facts) -> int:
    """Minutes spent: real solving time for a puzzle task, the budget for another finished one."""
    if t.type in (PUZZLES, GAME_PUZZLES):
        return round(f.seconds.get(t.id, 0) / 60)
    return t.minutes if is_done(t, f) else 0


def plan_progress(plan: PlanRow, today: date, f: Facts, theme_stats: Mapping[str, tuple[int, int]]) -> dict[str, Any]:
    """FR-10.66: how the plan went, as **aggregates only**: no game ids, titles, prompts or journal text.
    `theme_stats` is theme → (attempts, first-try wins) in the plan's sessions."""
    carried = frozenset(t.carried_from for d in plan.days for t in d.tasks if t.carried_from is not None)
    by_type: dict[str, dict[str, int]] = {}
    by_weakness: dict[str, dict[str, int]] = {}
    minutes = 0
    for d in plan.days:
        for t in d.tasks:
            st = status_of(t, d.date, today, f, carried)
            minutes += task_minutes(t, f)
            by_type.setdefault(t.type, {}).setdefault(st, 0)
            by_type[t.type][st] += 1
            if t.weakness_key:
                by_weakness.setdefault(t.weakness_key, {}).setdefault(st, 0)
                by_weakness[t.weakness_key][st] += 1
    return {
        "weeks": plan.params.weeks,
        "days_per_week": len(plan.params.weekdays),
        "minutes_per_day": plan.params.minutes,
        "training_days_so_far": sum(1 for d in plan.days if d.date <= today.isoformat()),
        "training_days_total": len(plan.days),
        "tasks_by_type": by_type,
        "tasks_by_weakness": by_weakness,
        "minutes_spent": minutes,
        "puzzle_first_try_by_theme": {
            k: {"attempts": a, "first_try": w} for k, (a, w) in sorted(theme_stats.items())
        },
    }  # fmt: skip
