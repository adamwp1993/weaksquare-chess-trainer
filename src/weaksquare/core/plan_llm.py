"""The AI's part of the training plan (v0.12, FR-10.66, 10.71, 10.73). Pure.

**The AI's plan is untrusted.** Every task is checked field by field like a preset (FR-10.23): an unknown task type,
theme, mode, game or lesson topic drops the task. The app writes every title from the validated fields, so the only
AI text kept is a reflection's question, cleaned and shown as plain text. The deterministic plan fills what's left
of each day, so there's always a complete plan of the shape you asked for, and a broken answer falls back to it whole.

**What's added to the prompt** (`prompt_parts`) is aggregates only, plus your journal text when you asked for it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from weaksquare.core import plan as plans
from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.plan import Context, Day, PlanDraft, PlanParams, Task
from weaksquare.core.preset_suggestion import preset_themes
from weaksquare.core.report_compare import TREND_CHANGES
from weaksquare.core.themes import display_name
from weaksquare.core.urls import REPLACEMENT, strip_urls

MAX_PROMPT_TEXT = 200
MIN_TASK_MINUTES = 3
MAX_TASKS_A_DAY = 4
MAX_TASK_THEMES = 3

_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "type", "minutes", "weakness_key", "themes", "mode", "count", "rating_min", "rating_max", "severities",
        "game", "topic", "prompt",
    ],
    "properties": {
        "type": {"type": "string", "enum": list(plans.TASK_TYPES)},
        "minutes": {"type": "integer"},
        "weakness_key": {"type": ["string", "null"]},
        "themes": {"type": "array", "items": {"type": "string"}},
        "mode": {"type": ["string", "null"]},
        "count": {"type": ["integer", "null"]},
        "rating_min": {"type": ["integer", "null"]},
        "rating_max": {"type": ["integer", "null"]},
        "severities": {"type": "array", "items": {"type": "string"}},
        "game": {"type": ["string", "null"]},
        "topic": {"type": ["string", "null"]},
        "prompt": {"type": ["string", "null"]},
    },
}  # fmt: skip

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["weeks"],
    "properties": {
        "weeks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["days"],
                "properties": {
                    "days": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["tasks"],
                            "properties": {"tasks": {"type": "array", "items": _TASK_SCHEMA}},
                        },
                    }
                },
            },
        }
    },
}

TREND_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["key", "change", "comment"],
        "properties": {
            "key": {"type": "string"},
            "change": {"type": "string", "enum": list(TREND_CHANGES)},
            "comment": {"type": "string"},
        },
    },
}

TREND_RULES = """
- "trend": what improved, what got worse and whether earlier advice seems to be working, from the "Since last report"
  numbers only. Each item names a weakness "key" from that section. "change" must agree with its "change" value there
  ("better" is "improved"): give no item for a weakness whose change is "not_enough". Empty when there's no section.
"""

PLAN_RULES = """
- "plan": a training plan in exactly the shape given under "Plan shape": weeks, each with days, each with 2-4 tasks
  whose minutes add up to that day's minutes. The top weaknesses get the most time. Each task is one "type":
  * "puzzles": "themes" from the allowed theme keys (at most 3), "mode" (standard, commit_line, name_idea or
    danger_spotting), "count" as many as fit, and "rating_min"/"rating_max" or null.
  * "game_puzzles": puzzles from the player's own games: "severities" (blunder, mistake, inaccuracy) and "count".
  * "retry": replay their mistakes in one game: "game" is its label (G1, G2, ...).
  * "review": step through one game with best moves hidden: "game" is its label.
  * "lesson": "topic" is one topic id from the list.
  * "reflection": "prompt" is one short question for their journal, plain text.
  Set "weakness_key" to the report's key the task trains, or null. Use null or [] for fields a type doesn't use.
  Use each game for at most one retry and one review. Use the plan progress, if given, to adjust: drop what isn't
  being done, repeat what's working.
"""


def add_to_schema(schema: Mapping[str, Any], *, plan: bool) -> dict[str, Any]:
    """The answer's schema with `trend` and, for your own reports, `plan`."""
    props = dict(schema["properties"])
    required = list(schema["required"])
    props["trend"] = TREND_SCHEMA
    required.append("trend")
    if plan:
        props["plan"] = PLAN_SCHEMA
        required.append("plan")
    return {**schema, "properties": props, "required": required}


@dataclass(frozen=True)
class JournalLine:
    """One Include my journal entry as sent (FR-10.71)."""

    text: str
    kind: str
    game: str | None
    ply: int | None
    weakness: str | None


def prompt_parts(
    *, comparison: Mapping[str, Any] | None, progress: Mapping[str, Any] | None, params: PlanParams | None,
    journal: Sequence[JournalLine] | None,
) -> str:  # fmt: skip
    """What v0.12 adds to the user message: the trend, the plan's progress and shape, and (opted in) your journal."""
    lines: list[str] = []
    if comparison is not None:
        lines += ["", "Since last report (aggregates only):", json.dumps(comparison, separators=(",", ":"))]
    if progress is not None:
        lines += ["", "How the current training plan went (aggregates only):", json.dumps(progress, separators=(",", ":"))]  # fmt: skip
    if params is not None:
        lines += [
            "", "Plan shape: "
            f"{params.weeks} week(s), {len(params.weekdays)} training day(s) a week, {params.minutes} minutes a day.",
        ]  # fmt: skip
    if journal:
        lines += ["", "The player's journal (written by the player):"]
        for e in journal:
            item: dict[str, Any] = {"note": e.text, "kind": e.kind}
            if e.game is not None:
                item["game"] = e.game
                if e.ply is not None:
                    item["ply"] = e.ply
            if e.weakness is not None:
                item["weakness"] = e.weakness
            lines.append(json.dumps(item, separators=(",", ":")))
    return "\n".join(lines)


@dataclass(frozen=True)
class PlanCheck:
    """How the AI's plan held up, for the screen."""

    ai_tasks: int  # tasks of the AI's that were kept
    dropped: int  # tasks that failed validation, or didn't fit
    filled: int  # tasks the deterministic plan added
    fallback: bool  # nothing usable came back: this is the deterministic plan

    def to_json(self) -> dict[str, Any]:
        return {"ai_tasks": self.ai_tasks, "dropped": self.dropped, "filled": self.filled, "fallback": self.fallback}


def _whole(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _task(
    raw: Any, keys: frozenset[str], topics: frozenset[str], ctx: Context,
    game: Callable[[str, str], tuple[int, str] | None],
) -> Task | None:  # fmt: skip
    """One task, or None when anything that defines it is invalid."""
    if not isinstance(raw, Mapping):
        return None
    kind = raw.get("type")
    minutes = raw.get("minutes")
    if kind not in plans.TASK_TYPES or not isinstance(minutes, int) or isinstance(minutes, bool):
        return None
    if minutes < MIN_TASK_MINUTES:
        return None
    wk = raw.get("weakness_key")
    key = wk if isinstance(wk, str) and wk in keys else None
    if kind == plans.PUZZLES:
        return _puzzle(raw, minutes, key, ctx)
    if kind == plans.GAME_PUZZLES:
        return _game_puzzle(raw, minutes, key, ctx)
    if kind in (plans.RETRY, plans.REVIEW):
        label = raw.get("game")
        found = game(label, str(kind)) if isinstance(label, str) else None
        if found is None:
            return None
        gid, name = found
        at = ctx if name in ctx.games.values() else replace(ctx, games={**ctx.games, gid: name})
        make = plans.retry_task if kind == plans.RETRY else plans.review_task
        return make(at, minutes, key, gid)
    if kind == plans.LESSON:
        topic = raw.get("topic")
        if not isinstance(topic, str) or topic not in topics:
            return None
        return plans.lesson_task(ctx, minutes, key, topic)
    text = raw.get("prompt")
    prompt = " ".join(strip_urls(text).split())[:MAX_PROMPT_TEXT] if isinstance(text, str) else ""
    return plans.reflection_task(minutes, key, prompt) if prompt.replace(REPLACEMENT, "").strip() else None


def _puzzle(raw: Mapping[str, Any], minutes: int, key: str | None, ctx: Context) -> Task | None:
    allowed = set(preset_themes())
    got = raw.get("themes")
    themes = list(dict.fromkeys(t for t in got if isinstance(t, str))) if isinstance(got, list) else []
    if not themes or len(themes) > MAX_TASK_THEMES or not set(themes) <= allowed:
        return None
    mode = raw.get("mode")
    if mode not in plans.MODES or (mode == "danger_spotting" and not ctx.engine_ready):
        return None
    lo, hi = raw.get("rating_min"), raw.get("rating_max")
    lo = lo if _whole(lo) else None
    hi = hi if _whole(hi) else None
    try:
        FilterSpec(themes=tuple(themes), rating_min=lo, rating_max=hi).validate()
    except ValidationError:
        return None
    count = _count(raw.get("count"), minutes, ctx)
    name = ", ".join(display_name(t) for t in themes)
    if lo is None and hi is None:
        return plans.puzzle_task(ctx, minutes, key, name, picked=themes, mode=str(mode), count=count)
    return plans.puzzle_task(ctx, minutes, key, name, picked=themes, mode=str(mode), rating_min=lo, rating_max=hi, count=count)  # fmt: skip


def _game_puzzle(raw: Mapping[str, Any], minutes: int, key: str | None, ctx: Context) -> Task | None:
    got = raw.get("severities")
    sev = list(dict.fromkeys(s for s in got if isinstance(s, str))) if isinstance(got, list) else []
    if not ctx.has_game_puzzles or not sev or not set(sev) <= set(plans.SEVERITIES):
        return None
    return plans.game_puzzle_task(ctx, minutes, key, sev, count=_count(raw.get("count"), minutes, ctx))


def _count(raw: Any, minutes: int, ctx: Context) -> int:
    """The AI's count, but never more than fits the task's minutes."""
    fits = plans.fit_count(minutes, ctx.puzzle_minutes)
    return min(int(raw), fits) if _whole(raw) and raw >= 1 else fits


def validate_plan(
    raw: Any, draft: PlanDraft, ctx: Context, keys: Sequence[str], topics: Sequence[str],
    game: Callable[[str, str], tuple[int, str] | None],
) -> tuple[PlanDraft, PlanCheck]:  # fmt: skip
    """FR-10.66: the plan to offer, always complete, in `draft`'s shape. `game(label, type)` gives a game's id
    and short name when that label can have that task type."""
    weeks = raw.get("weeks") if isinstance(raw, Mapping) else None
    if not isinstance(weeks, list):
        return draft, PlanCheck(0, 0, 0, True)
    per_week = len(draft.params.weekdays)
    ai_days: list[Any] = []
    surplus = 0
    for w in weeks:
        days = w.get("days") if isinstance(w, Mapping) else None
        days = days if isinstance(days, list) else []
        ai_days += days[:per_week]
        surplus += sum(_task_count(d) for d in days[per_week:])
    surplus += sum(_task_count(d) for d in ai_days[len(draft.days) :])
    key_set, topic_set = frozenset(keys), frozenset(topics)
    used: set[tuple[str, Any]] = set()
    out: list[Day] = []
    kept = filled = 0
    dropped = surplus
    budget = draft.params.minutes
    for n, base in enumerate(draft.days):
        tasks: list[Task] = []
        spent = 0
        raw_day = ai_days[n] if n < len(ai_days) else None
        raw_tasks = raw_day.get("tasks") if isinstance(raw_day, Mapping) else None
        for t in raw_tasks if isinstance(raw_tasks, list) else []:
            task = _task(t, key_set, topic_set, ctx, game)
            once = plans._once_key(task) if task is not None else None
            fits = task is not None and spent + task.minutes <= budget and len(tasks) < MAX_TASKS_A_DAY
            if not fits or (once is not None and once in used):
                dropped += 1
                continue
            assert task is not None
            if once is not None:
                used.add(once)
            tasks.append(task)
            spent += task.minutes
        kept += len(tasks)
        filled += _fill(tasks, base, budget - spent, ctx, used)
        out.append(Day(base.week, base.position, tuple(tasks)))
    if kept == 0:  # nothing usable: the deterministic plan, whole
        return draft, PlanCheck(0, dropped, 0, True)
    return PlanDraft(draft.params, tuple(out)), PlanCheck(kept, dropped, filled, False)


def _task_count(day: Any) -> int:
    tasks = day.get("tasks") if isinstance(day, Mapping) else None
    return len(tasks) if isinstance(tasks, list) else 0


def _fill(tasks: list[Task], base: Day, left: int, ctx: Context, used: set[tuple[str, Any]]) -> int:
    """The deterministic day's tasks take up what's left of the day. Returns how many were added."""
    added = 0
    for b in base.tasks:
        if left <= 0 or len(tasks) >= MAX_TASKS_A_DAY:
            break
        once = plans._once_key(b)
        if (once is not None and once in used) or any(plans._same(b, t) for t in tasks):
            continue
        minutes = left if len(tasks) == MAX_TASKS_A_DAY - 1 else min(b.minutes, left)
        if minutes < MIN_TASK_MINUTES and tasks:
            break
        if once is not None:
            used.add(once)
        tasks.append(plans.resize(b, minutes, ctx))
        left -= minutes
        added += 1
    if left > 0:
        if tasks:  # the day's minutes always add up: the last task gets the rest
            tasks[-1] = plans.resize(tasks[-1], tasks[-1].minutes + left, ctx)
        else:
            tasks.append(plans.general_task(ctx, left))
            added += 1
    if len(tasks) == 1 and tasks[0].minutes >= 2 * MIN_TASK_MINUTES:  # FR-10.62: at least 2 tasks
        first = tasks[0]
        half = first.minutes // 2
        tasks[0] = plans.resize(first, first.minutes - half, ctx)
        extra = plans.general_task(ctx, half)
        tasks.append(extra)
        added += 1
    return added
