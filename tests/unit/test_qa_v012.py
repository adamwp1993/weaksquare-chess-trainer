"""QA v0.12: invariants of the pure code on many inputs (FR-10.61, 10.62, 10.66, 10.73). Fixed seeds, so it's repeatable."""

from __future__ import annotations

import random
from typing import Any

import pytest

from weaksquare.core.plan import (
    MINUTES_MAX,
    MINUTES_MIN,
    TASK_TYPES,
    Context,
    PlanParams,
    build_plan,
    first_day,
    training_dates,
)
from weaksquare.core.plan_llm import validate_plan
from weaksquare.core.report_compare import Side, compare, prompt_json, validate_trend

KEYS = ["missed:fork", "allowed:pin", "habit:hangingPiece", "opening:Sicilian", "endgame:rook", "phase:conversion",
        "time:low_clock", "habit:castledLate", "puzzle:fork"]  # fmt: skip


def _report(rnd: random.Random) -> dict[str, Any]:
    picks = rnd.sample(KEYS, rnd.randint(0, len(KEYS)))
    weak = []
    for k in picks:
        kind, name = k.split(":", 1)
        weak.append(
            {"key": k, "kind": kind, "name": name, "label": k, "score": rnd.uniform(0, 9), "themes": rnd.choice([["fork"], ["pin", "fork"], []]),
             "mode": rnd.choice([None, "danger_spotting", "commit_line", "bogus"]),
             "examples": [{"game_id": g, "ply": 4, "cp_loss": 300} for g in rnd.sample(range(1, 8), rnd.randint(0, 3))]}
        )  # fmt: skip
    return {"weaknesses": weak[: len(weak) // 2], "whole_game": weak[len(weak) // 2 :]}


def _ctx(rnd: random.Random) -> Context:
    games = {g: f"game {g}" for g in range(1, 8) if rnd.random() < 0.7}
    return Context(rnd.randint(400, 2800), rnd.random() < 0.5, rnd.random() < 0.5, rnd.choice([0.2, 1.5, 9.0]), games,
                   frozenset(g for g in games if rnd.random() < 0.5))  # fmt: skip


def _params(rnd: random.Random) -> PlanParams:
    days = sorted(rnd.sample(range(7), rnd.randint(1, 7)))
    return PlanParams(
        rnd.randint(1, 4), tuple(days), rnd.choice([MINUTES_MIN, 11, 20, 24, 25, 49, 50, 77, MINUTES_MAX])
    )


@pytest.mark.parametrize("seed", range(150))
def test_qa_every_plan_fits_the_minutes_and_has_two_to_four_known_tasks(seed: int) -> None:
    rnd = random.Random(seed)
    params = _params(rnd)
    draft = build_plan(_report(rnd), params, _ctx(rnd))
    assert len(draft.days) == params.weeks * len(params.weekdays)
    for d in draft.days:
        assert 2 <= len(d.tasks) <= 4
        assert sum(t.minutes for t in d.tasks) == params.minutes
        assert all(t.type in TASK_TYPES and t.minutes > 0 and t.title for t in d.tasks)


def _garbage_task(rnd: random.Random) -> Any:
    return rnd.choice(
        [
            None, 3, "x", [], {}, {"type": "puzzles"}, {"type": None, "minutes": 5},
            {"type": "puzzles", "minutes": rnd.choice([-5, 0, 2, 3, 10, 10**9, True, "5", 5.5]), "themes": rnd.choice([["fork"], ["fork", "fork"], ["nope"], "fork", [1], []]),
             "mode": rnd.choice(["standard", "danger_spotting", None, "x", 7]), "count": rnd.choice([1, 0, -1, True, "3", 10**9, None]),
             "rating_min": rnd.choice([None, 5000, -1, 1000, "x", 1.5]), "rating_max": rnd.choice([None, 100, 1200, []])},
            {"type": "game_puzzles", "minutes": 5, "severities": rnd.choice([["blunder"], ["nope"], "blunder", []]), "count": 3},
            {"type": "retry", "minutes": 5, "game": rnd.choice(["G1", "G2", "G99", 1, None, "../x"])},
            {"type": "review", "minutes": 6, "game": rnd.choice(["G1", "G2", "G99", None])},
            {"type": "lesson", "minutes": 4, "topic": rnd.choice(["theme:fork", "nope", None, 3])},
            {"type": "reflection", "minutes": 4, "prompt": rnd.choice(["Why?", "", None, " " * 5, "https://evil.example/x", "y" * 900, 7]),
             "weakness_key": rnd.choice(["missed:fork", "invented", None, 3])},
        ]
    )  # fmt: skip


@pytest.mark.parametrize("seed", range(250))
def test_qa_any_ai_answer_gives_a_complete_plan_in_the_asked_shape(seed: int) -> None:
    """FR-10.66: whatever comes back, the plan is complete, in your shape, and only of the closed list."""
    rnd = random.Random(seed)
    params = _params(rnd)
    ctx = _ctx(rnd)
    report = _report(rnd)
    draft = build_plan(report, params, ctx)
    keys = [w["key"] for g in ("weaknesses", "whole_game") for w in report[g]]

    def game(label: str, kind: str) -> tuple[int, str] | None:
        return (1, "game 1") if label == "G1" else (2, "game 2") if label == "G2" and kind == "review" else None

    raw = {
        "weeks": [
            {
                "days": [
                    {"tasks": [_garbage_task(rnd) for _ in range(rnd.randint(0, 7))]} for _ in range(rnd.randint(0, 9))
                ]
            }
            for _ in range(rnd.randint(0, 6))
        ]
    }
    plan, check = validate_plan(raw, draft, ctx, keys, ["theme:fork"], game)
    assert plan.params == params and len(plan.days) == len(draft.days)
    for d, base in zip(plan.days, draft.days, strict=True):
        assert (d.week, d.position) == (base.week, base.position)
        assert 2 <= len(d.tasks) <= 4, d
        assert sum(t.minutes for t in d.tasks) == params.minutes, d
        for t in d.tasks:
            assert t.type in TASK_TYPES and t.minutes > 0
            assert "evil.example" not in t.title
            assert t.weakness_key is None or t.weakness_key in keys
    assert check.ai_tasks >= 0 and check.dropped >= 0 and check.filled >= 0


@pytest.mark.parametrize("seed", range(40))
def test_qa_training_dates_stay_on_picked_days_and_start_today_if_picked(seed: int) -> None:
    from datetime import date, timedelta

    rnd = random.Random(seed)
    params = _params(rnd)
    today = date(2026, 1, 1) + timedelta(days=rnd.randint(0, 400))
    start = first_day(today, params.weekdays)
    assert start >= today and (start - today).days < 7 and start.weekday() in params.weekdays
    assert (start == today) == (today.weekday() in params.weekdays)
    dates = training_dates(start, params.weekdays, params.weeks)
    assert len(dates) == params.weeks * len(params.weekdays) and len({d for _, d in dates}) == len(dates)
    assert all(d.weekday() in params.weekdays for _, d in dates)
    assert [d for _, d in dates] == sorted(d for _, d in dates)


def _side(i: int, games: range, per10: float | None, **kw: Any) -> Side:
    weak = [] if per10 is None else [{"key": "missed:fork", "label": "Forks", "per10": per10, "score": 1.0}]
    return Side(
        i,
        f"2026-01-{i:02d}T10:00:00+00:00",
        {"source": "games", "games": len(games), "weaknesses": weak, "missed": weak, **kw},
        frozenset(games),
    )


@pytest.mark.parametrize(
    ("old_games", "new_games", "verdict"),
    [
        (range(1, 5), range(100, 110), "not_enough"),  # 4 games in the older report
        (range(1, 11), range(100, 104), "not_enough"),  # 4 in the newer
        (range(1, 11), range(1, 15), "not_enough"),  # 14 games but 4 new
        (range(1, 11), range(6, 16), "better"),  # exactly 5 new, 5 shared
        (range(1, 6), range(100, 105), "better"),  # exactly 5 and 5
    ],
)
def test_qa_the_guard_at_its_edges(old_games: range, new_games: range, verdict: str) -> None:
    c = compare(_side(2, new_games, 1.0), [_side(1, old_games, 3.0)])
    assert c is not None and c.weaknesses[0].verdict == verdict


def test_qa_the_same_rate_within_rounding_is_same_and_exactly_the_limit_moves() -> None:
    a = compare(_side(2, range(100, 110), 3.04), [_side(1, range(1, 11), 3.0)])
    assert a is not None and a.weaknesses[0].verdict == "same"
    b = compare(_side(2, range(100, 110), 3.5), [_side(1, range(1, 11), 3.0)])
    assert b is not None and b.weaknesses[0].verdict == "worse"


def test_qa_a_trend_claim_can_never_be_better_than_the_numbers() -> None:
    c = compare(_side(2, range(100, 110), 5.0), [_side(1, range(1, 11), 3.0)])
    assert c is not None and c.weaknesses[0].verdict == "worse"
    for claim in ("improved", "same", "IMPROVED", "better", "not_enough", None, 3):
        kept, dropped = validate_trend([{"key": "missed:fork", "change": claim, "comment": "Nice."}], c)
        assert kept == [] and dropped == 1
    assert validate_trend([{"key": "invented", "change": "worse", "comment": "x"}], c) == ([], 1)
    assert validate_trend([{"key": "missed:fork", "change": "worse", "comment": "  "}], c) == ([], 1)
    kept, _ = validate_trend(
        [{"key": "missed:fork", "change": "worse", "comment": "See https://evil.example/x now."}], c
    )
    assert kept and "evil.example" not in kept[0].comment
    twice, dropped = validate_trend([{"key": "missed:fork", "change": "worse", "comment": "a"}] * 2, c)
    assert len(twice) == 1 and dropped == 1
    assert validate_trend("nope", c) == ([], 0) and validate_trend([{"key": "x"}], None) == ([], 1)


def test_qa_a_five_report_series_is_oldest_first_and_labeled_with_days() -> None:
    sides = [_side(i, range(i * 100, i * 100 + 10), float(i)) for i in range(1, 6)]
    c = compare(sides[-1], sides[:-1])
    assert c is not None and c.weaknesses[0].series == (1.0, 2.0, 3.0, 4.0, 5.0)
    j = prompt_json(c, [4, 3, 2, 1, 0])
    assert [r["label"] for r in j["reports"]] == [
        "4 reports ago",
        "3 reports ago",
        "2 reports ago",
        "1 report ago",
        "this report",
    ]
    assert list(j["weaknesses"][0]["rates"].values()) == [1.0, 2.0, 3.0, 4.0, 5.0]
    # A sixth report drops the oldest.
    more = _side(6, range(600, 610), 6.0)
    c6 = compare(more, sides)
    assert c6 is not None and c6.weaknesses[0].series == (2.0, 3.0, 4.0, 5.0, 6.0)
