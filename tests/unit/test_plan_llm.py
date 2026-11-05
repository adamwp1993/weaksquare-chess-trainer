"""The AI's plan is untrusted (v0.12, FR-10.66)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from weaksquare.core.plan import (
    GAME_PUZZLES,
    LESSON,
    PUZZLES,
    REFLECTION,
    RETRY,
    REVIEW,
    Context,
    PlanParams,
    build_plan,
)
from weaksquare.core.plan_llm import JournalLine, add_to_schema, prompt_parts, validate_plan

CTX = Context(
    engine_ready=True, has_game_puzzles=True, games={1: "game one", 2: "game two"}, retry_games=frozenset({1})
)
REPORT = {"weaknesses": [{"key": "missed:fork", "label": "Forks", "score": 3.0, "themes": ["fork"], "examples": []}], "whole_game": []}  # fmt: skip
PARAMS = PlanParams(1, (0, 1), 20)
DRAFT = build_plan(REPORT, PARAMS, CTX)
KEYS = ["missed:fork"]
TOPICS = ["theme:fork"]


def game(label: str, kind: str) -> tuple[int, str] | None:
    if label == "G1":
        return 1, "game one"
    if label == "G2" and kind == REVIEW:  # G2 has no mistakes to retry
        return 2, "game two"
    return None


def t(type_: str = PUZZLES, minutes: int = 10, **kw: Any) -> dict[str, Any]:
    base = {
        "type": type_, "minutes": minutes, "weakness_key": "missed:fork", "themes": [], "mode": None, "count": None,
        "rating_min": None, "rating_max": None, "severities": [], "game": None, "topic": None, "prompt": None,
    }  # fmt: skip
    return {**base, **kw}


GOOD = t(themes=["fork"], mode="standard", count=5)


def plan(*days: list[dict[str, Any]]) -> dict[str, Any]:
    return {"weeks": [{"days": [{"tasks": d} for d in days]}]}


def check(raw: Any) -> Any:
    return validate_plan(raw, DRAFT, CTX, KEYS, TOPICS, game)


def titles(out: Any, day: int = 0) -> list[str]:
    return [x.title for x in out.days[day].tasks]


def test_a_good_plan_is_kept_and_titled_by_the_app() -> None:
    out, c = check(plan([GOOD, t(REFLECTION, prompt="What stood out?")], [t(RETRY, game="G1"), t(REVIEW, game="G2")]))
    assert c.fallback is False and c.ai_tasks == 4 and c.dropped == 0
    assert titles(out)[0] == "5 puzzles: Fork"
    assert out.days[1].tasks[0].params == {"game_id": 1}
    assert "game one" in out.days[1].tasks[0].title


@pytest.mark.parametrize(
    "bad",
    [
        t("chess_on_the_moon"),
        t(themes=["notATheme"], mode="standard"),
        t(themes=[], mode="standard"),
        t(themes=["fork", "pin", "skewer", "mateIn1"], mode="standard"),
        t(themes=["fork"], mode="blindfold"),
        t(themes=["fork"], mode=None),
        t(themes=["fork"], mode="standard", rating_min=3000, rating_max=1000),
        t(GAME_PUZZLES, severities=["awful"]),
        t(GAME_PUZZLES, severities=[]),
        t(RETRY, game="G99"),
        t(RETRY, game="G2"),  # that game has no mistakes to retry
        t(RETRY, game=12345),
        t(REVIEW, game=None),
        t(LESSON, topic="https://evil.example"),
        t(LESSON, topic=None),
        t(REFLECTION, prompt=""),
        t(REFLECTION, prompt="https://only.example/a-link"),
        t(minutes=0),
        t(minutes="ten"),
        "nonsense",
    ],
)
def test_an_invalid_task_is_dropped_and_the_day_still_fits(bad: Any) -> None:
    out, c = check(plan([bad, GOOD]))
    assert c.dropped == 1
    assert sum(x.minutes for x in out.days[0].tasks) == PARAMS.minutes
    assert 2 <= len(out.days[0].tasks) <= 4


def test_danger_spotting_without_stockfish_is_dropped() -> None:
    no_engine = Context(engine_ready=False, games=CTX.games)
    draft = build_plan(REPORT, PARAMS, no_engine)
    _, c = validate_plan(plan([t(themes=["fork"], mode="danger_spotting"), GOOD]), draft, no_engine, KEYS, TOPICS, game)
    assert c.dropped == 1


def test_game_puzzles_without_any_are_dropped() -> None:
    none = Context(has_game_puzzles=False)
    draft = build_plan(REPORT, PARAMS, none)
    _, c = validate_plan(plan([t(GAME_PUZZLES, severities=["blunder"]), GOOD]), draft, none, KEYS, TOPICS, game)
    assert c.dropped == 1


def test_an_unknown_weakness_key_is_cleared_but_the_task_stays() -> None:
    out, _ = check(plan([{**GOOD, "weakness_key": "missed:invented"}]))
    assert out.days[0].tasks[0].weakness_key is None


@pytest.mark.parametrize("broken", [None, "text", [], {}, {"weeks": "x"}, {"weeks": []}, {"weeks": [{"days": []}]}, plan([]), plan([t("x")])])  # fmt: skip
def test_an_empty_or_broken_plan_falls_back_to_the_deterministic_one(broken: Any) -> None:
    out, c = check(broken)
    assert out == DRAFT and c.fallback is True and c.ai_tasks == 0


def test_gaps_are_filled_so_every_day_is_complete() -> None:
    out, c = check(plan([GOOD]))  # the second day is missing and the first is short
    assert len(out.days) == len(DRAFT.days)
    assert c.filled > 0 and not c.fallback
    for d in out.days:
        assert sum(x.minutes for x in d.tasks) == PARAMS.minutes
        assert 2 <= len(d.tasks) <= 4


def test_days_and_weeks_beyond_the_shape_are_dropped() -> None:
    days = [[GOOD] for _ in range(5)]
    out, c = check({"weeks": [{"days": [{"tasks": d} for d in days]}, {"days": [{"tasks": [GOOD]}]}]})
    assert len(out.days) == 2
    assert c.dropped == 4


def test_a_day_that_runs_over_keeps_what_fits() -> None:
    out, c = check(
        plan([t(themes=["fork"], mode="standard", minutes=15), t(themes=["pin"], mode="standard", minutes=15)])
    )
    assert c.dropped == 1
    assert sum(x.minutes for x in out.days[0].tasks) == PARAMS.minutes


def test_a_count_too_big_for_the_minutes_is_cut() -> None:
    out, _ = check(plan([t(themes=["fork"], mode="standard", count=100, minutes=6)]))
    assert out.days[0].tasks[0].params["count"] == 4  # 6 minutes at 1.5 a puzzle


def test_a_game_is_used_at_most_once_per_task_type() -> None:
    out, c = check(plan([t(REVIEW, game="G1", minutes=5), t(REVIEW, game="G1", minutes=5), GOOD]))
    assert c.dropped == 1
    assert sum(1 for x in out.days[0].tasks if x.type == REVIEW) == 1


def test_a_lesson_uses_only_a_topic_that_was_sent() -> None:
    out, _ = check(plan([t(LESSON, topic="theme:fork"), GOOD]))
    assert out.days[0].tasks[0].params == {"topic": "theme:fork"}
    assert out.days[0].tasks[0].title == "Lesson: Fork"
    _, c = check(plan([t(LESSON, topic="theme:pin"), GOOD]))  # a real topic, but not on the list sent
    assert c.dropped == 1


def test_a_reflection_question_is_plain_text_with_no_address() -> None:
    long = "Why? see https://evil.example/x " + "x" * 400
    out, _ = check(plan([t(REFLECTION, prompt=long), GOOD]))
    prompt = out.days[0].tasks[0].params["prompt"]
    assert "evil.example" not in prompt and len(prompt) <= 200


def test_the_ai_plan_survives_json() -> None:
    out, _ = check(plan([GOOD]))
    assert type(out).from_json(json.loads(json.dumps(out.to_json()))) == out


# ---- the schema ----


def test_the_schema_gains_trend_always_and_plan_only_for_your_reports() -> None:
    base = {"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string"}}}  # fmt: skip
    theirs = add_to_schema(base, plan=False)
    yours = add_to_schema(base, plan=True)
    assert "trend" in theirs["required"] and "plan" not in theirs["properties"]
    assert set(yours["required"]) == {"summary", "trend", "plan"}
    assert base["required"] == ["summary"]  # the original is untouched


# ---- what's added to the prompt ----


def test_nothing_is_added_when_nothing_is_on() -> None:
    assert prompt_parts(comparison=None, progress=None, params=None, journal=None) == ""


def test_the_journal_appears_only_when_given() -> None:
    entry = JournalLine("I rushed in time trouble.", "note", "G2", 15, "time:low_clock")
    without = prompt_parts(comparison={"a": 1}, progress={"b": 2}, params=PARAMS, journal=None)
    assert "rushed" not in without and "journal" not in without.lower()
    with_it = prompt_parts(comparison=None, progress=None, params=None, journal=[entry])
    assert '"note":"I rushed in time trouble."' in with_it
    assert '"game":"G2"' in with_it and '"ply":15' in with_it


def test_the_shape_is_stated() -> None:
    assert "1 week(s), 2 training day(s) a week, 20 minutes a day" in prompt_parts(comparison=None, progress=None, params=PARAMS, journal=None)  # fmt: skip
