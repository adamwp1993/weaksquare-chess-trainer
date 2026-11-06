"""Since last report (v0.12, FR-10.73)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from weaksquare.core.report_compare import (
    BETTER,
    NOT_ENOUGH,
    SAME,
    WORSE,
    Comparison,
    PuzzleChange,
    Side,
    compare,
    prompt_json,
    puzzle_changes,
    validate_trend,
)
from weaksquare.core.stats import AttemptRow


def w(key: str, per10: float) -> dict[str, Any]:
    return {"key": key, "label": key.upper(), "per10": per10}


def side(
    rid: int, day: int, games: range | list[int], weak: list[dict[str, Any]], *, source: str = "games",
    per10: dict[str, float] | None = None, measures: dict[str, Any] | None = None, settings: Any = "same",
) -> Side:  # fmt: skip
    ids = list(games)
    data: dict[str, Any] = {
        "source": source, "games": len(ids), "weaknesses": weak, "missed": weak, "whole_game": [],
        "per10": per10 or {"blunders": 1.0, "mistakes": 2.0, "inaccuracies": 3.0},
    }  # fmt: skip
    if measures is not None:
        data["measures"] = measures
    if settings == "same":
        data["analysis_settings"] = {"think_s": 0.3}
    elif settings is not None:
        data["analysis_settings"] = settings
    return Side(rid, f"2026-11-{day:02d}T10:00:00+00:00", data, frozenset(ids))


def changes(c: Comparison | None) -> dict[str, Any]:
    assert c is not None
    return {x.key: x for x in c.weaknesses}


OLD = side(1, 1, range(10), [w("missed:fork", 4.0), w("allowed:pin", 2.0)])


def test_no_earlier_report_no_comparison() -> None:
    assert compare(OLD, []) is None


def test_rates_and_changes_match_the_two_reports() -> None:
    cur = side(2, 11, range(10, 20), [w("missed:fork", 3.0), w("allowed:pin", 2.5)])
    c = compare(cur, [OLD])
    assert c is not None
    assert (c.days_between, c.new_games, c.shared_games, c.enough_new_games) == (10, 10, 0, True)
    fork, pin = changes(c)["missed:fork"], changes(c)["allowed:pin"]
    assert (fork.then, fork.now, fork.delta, fork.verdict) == (4.0, 3.0, -1.0, BETTER)
    assert (pin.then, pin.now, pin.delta, pin.verdict) == (2.0, 2.5, 0.5, WORSE)


def test_no_change_is_said_to_be_the_same() -> None:
    c = compare(side(2, 2, range(10, 20), [w("missed:fork", 4.0)]), [OLD])
    assert changes(c)["missed:fork"].verdict == SAME


def test_new_and_gone_are_marked() -> None:
    c = compare(side(2, 2, range(10, 20), [w("missed:fork", 4.0), w("habit:hungPiece", 1.0)]), [OLD])
    assert changes(c)["habit:hungPiece"].flag == "new"
    assert changes(c)["habit:hungPiece"].then is None
    assert changes(c)["allowed:pin"].flag == "gone"
    assert changes(c)["allowed:pin"].now == 0.0
    assert changes(c)["missed:fork"].flag is None


def test_a_new_weakness_has_no_verdict_because_it_has_no_earlier_rate() -> None:
    c = compare(side(2, 2, range(10, 20), [w("habit:hungPiece", 1.0)]), [OLD])
    assert changes(c)["habit:hungPiece"].verdict == NOT_ENOUGH
    assert changes(c)["habit:hungPiece"].delta is None


def test_fewer_than_5_new_games_is_not_enough_however_big_the_change() -> None:
    cur = side(2, 2, [*range(2, 10), 100, 101, 102, 103], [w("missed:fork", 0.5)])
    c = compare(cur, [OLD])
    assert c is not None
    assert (c.new_games, c.shared_games, c.enough_new_games) == (4, 8, False)
    assert changes(c)["missed:fork"].verdict == NOT_ENOUGH
    assert all(h.verdict == NOT_ENOUGH for h in c.health)


def test_exactly_5_new_games_is_enough() -> None:
    cur = side(2, 2, [*range(5, 10), 100, 101, 102, 103, 104], [w("missed:fork", 0.5)])
    assert changes(compare(cur, [OLD]))["missed:fork"].verdict == BETTER


def test_fewer_than_5_games_in_a_report_is_not_enough() -> None:
    small = side(1, 1, range(4), [w("missed:fork", 4.0)])
    assert changes(compare(side(2, 2, range(10, 20), [w("missed:fork", 1.0)]), [small]))["missed:fork"].verdict == NOT_ENOUGH  # fmt: skip
    assert changes(compare(side(2, 2, range(10, 14), [w("missed:fork", 1.0)]), [OLD]))["missed:fork"].verdict == NOT_ENOUGH  # fmt: skip


def test_game_health_is_compared() -> None:
    cur = side(2, 2, range(10, 20), [], per10={"blunders": 0.5, "mistakes": 2.0, "inaccuracies": 4.0})
    h = {m.key: m for m in compare(cur, [OLD]).health}  # type: ignore[union-attr]
    assert h["health:blunders"].verdict == BETTER
    assert h["health:mistakes"].verdict == SAME
    assert h["health:inaccuracies"].verdict == WORSE


def test_settings_are_flagged_when_they_differ_or_are_unknown() -> None:
    cur = side(2, 2, range(10, 20), [], settings={"think_s": 1.0})
    assert compare(cur, [OLD]).settings == "different"  # type: ignore[union-attr]
    assert compare(side(2, 2, range(10, 20), []), [OLD]).settings == "same"  # type: ignore[union-attr]
    old_style = side(1, 1, range(10), [], settings=None)
    assert compare(side(2, 2, range(10, 20), []), [old_style]).settings == "unknown"  # type: ignore[union-attr]


def _measures(games: int = 10, *, score: float = 50.0, conv: float = 40.0, low: float | None = 8.0, late: int = 5) -> dict[str, Any]:  # fmt: skip
    return {
        "games": games,
        "openings": [{"family": "Sicilian", "games": games, "score": score}, {"family": "Only here", "games": games, "score": 10.0}],
        "conversion": {"games": games, "rate": conv},
        "saves": {"games": games, "rate": 10.0},
        "time": {"games": games, "low_error_rate": low},
        "king": {"games": games, "late": late},
    }  # fmt: skip


def test_whole_game_measures_that_both_reports_have_are_compared() -> None:
    old = side(1, 1, range(10), [], measures=_measures())
    m = _measures(score=60.0, conv=30.0, low=None, late=2)
    m["openings"] = [m["openings"][0]]
    c = compare(side(2, 2, range(10, 20), [], measures=m), [old])
    assert c is not None
    got = {x.key: x for x in c.measures}
    assert got["opening_score:Sicilian"].verdict == BETTER
    assert got["conversion"].verdict == WORSE
    assert got["saves"].verdict == SAME
    assert got["late_castling"].verdict == BETTER
    assert "low_clock" not in got  # only this report's clock data is missing: nothing to compare
    assert "opening_score:Only here" not in got


def test_a_measures_own_group_has_the_5_game_guard() -> None:
    old = side(1, 1, range(10), [], measures=_measures(games=4))
    c = compare(side(2, 2, range(10, 20), [], measures=_measures(score=90.0)), [old])
    assert c is not None
    assert {x.key: x.verdict for x in c.measures}["opening_score:Sicilian"] == NOT_ENOUGH


def test_a_report_with_no_measures_compares_none() -> None:
    c = compare(side(2, 2, range(10, 20), [], measures=_measures()), [OLD])
    assert c is not None and c.measures == ()


def test_the_trend_covers_up_to_5_reports() -> None:
    sides = [side(i, i, range(i * 100, i * 100 + 10), [w("missed:fork", float(i))]) for i in range(1, 7)]
    c = compare(sides[-1], sides[:-1])
    assert c is not None
    assert [rid for rid, _ in c.history] == [2, 3, 4, 5, 6]
    assert changes(c)["missed:fork"].series == (2.0, 3.0, 4.0, 5.0, 6.0)


def test_a_report_missing_from_the_trend_shows_a_gap() -> None:
    a = side(1, 1, range(10), [w("missed:fork", 1.0)])
    b = side(2, 2, range(10, 20), [])
    c = side(3, 3, range(20, 30), [w("missed:fork", 3.0)])
    assert changes(compare(c, [a, b]))["missed:fork"].series == (1.0, None, 3.0)


def test_puzzle_history_reports_compare_accuracy_without_game_guards() -> None:
    def ps(rid: int, acc: float) -> Side:
        row = {"key": "puzzle:fork", "label": "Fork", "puzzle_accuracy": acc, "per10": 0.0}
        return Side(rid, f"2026-11-0{rid}T10:00:00+00:00", {"source": "puzzles", "games": 0, "puzzles": [row]}, frozenset())  # fmt: skip

    c = compare(ps(2, 0.7), [ps(1, 0.5)])
    assert c is not None and c.puzzle_history
    row = changes(c)["puzzle:fork"]
    assert (row.then, row.now, row.verdict) == (50.0, 70.0, BETTER)
    assert c.health == () and c.measures == ()


# ---- puzzle accuracy between the reports ----


def attempt(day: int, win: bool, themes: tuple[str, ...] = ("fork",), **kw: Any) -> AttemptRow:
    return AttemptRow(win, win, win, 1500, themes, 2, finished_at=datetime(2026, 11, day, 9, tzinfo=UTC), **kw)


THEN = datetime(2026, 11, 10, 10, tzinfo=UTC)
NOW = datetime(2026, 11, 20, 10, tzinfo=UTC)


def test_puzzle_accuracy_up_to_the_older_report_against_between_the_two() -> None:
    rows = [attempt(1, i < 5) for i in range(10)] + [attempt(15, i < 8) for i in range(10)] + [attempt(25, False)]
    got = puzzle_changes(rows, {"missed:fork": ["fork"]}, THEN, NOW)["missed:fork"]
    assert (got.then_attempts, got.then_first_try, got.now_attempts, got.now_first_try) == (10, 5, 10, 8)
    assert (got.then, got.now, got.verdict) == (50.0, 80.0, BETTER)


def test_puzzle_accuracy_needs_10_attempts_each_side() -> None:
    rows = [attempt(1, True) for _ in range(9)] + [attempt(15, False) for _ in range(10)]
    assert puzzle_changes(rows, {"k": ["fork"]}, THEN, NOW)["k"].verdict == NOT_ENOUGH


def test_misclicks_danger_and_other_themes_do_not_count_and_an_attempt_counts_once() -> None:
    rows = [
        attempt(1, False, reason="misclick"),
        attempt(1, True, mode="danger_spotting"),
        attempt(1, True, ("pin",)),
        attempt(1, True, ("fork", "hangingPiece")),
    ]
    got = puzzle_changes(rows, {"k": ["fork", "hangingPiece"]}, THEN, NOW)["k"]
    assert got.then_attempts == 1


# ---- for the AI ----


def test_the_prompt_part_holds_aggregates_only() -> None:
    a = side(1, 1, range(777, 787), [w("missed:fork", 4.0)])
    cur = side(2, 11, range(900, 910), [w("missed:fork", 3.0)])
    c = compare(cur, [a])
    assert c is not None
    out = prompt_json(c, [10, 0])
    assert out["reports"] == [{"label": "1 report ago", "days_before_this_report": 10}, {"label": "this report", "days_before_this_report": 0}]  # fmt: skip
    assert out["weaknesses"][0]["rates"] == {"1 report ago": 4.0, "this report": 3.0}
    text = json.dumps(out)
    for leak in ("2026", "777", "900", "MISSED:FORK", "created_at", "game_id"):
        assert leak not in text


def test_the_prompt_part_labels_a_short_series_from_the_end() -> None:
    a = side(1, 1, range(10), [])
    b = side(2, 2, range(10, 20), [w("missed:fork", 2.0)])
    cur = side(3, 3, range(20, 30), [w("missed:fork", 1.0)])
    out = prompt_json(compare(cur, [a, b]), [2, 1, 0])  # type: ignore[arg-type]
    assert out["weaknesses"][0]["rates"] == {"2 reports ago": None, "1 report ago": 2.0, "this report": 1.0}


def test_puzzle_change_goes_with_its_weakness() -> None:
    p = {"missed:fork": PuzzleChange(10, 5, 10, 8, BETTER)}
    c = compare(side(2, 2, range(10, 20), [w("missed:fork", 3.0)]), [OLD], p)
    assert changes(c)["missed:fork"].puzzle == p["missed:fork"]
    out = prompt_json(c, [1, 0])  # type: ignore[arg-type]
    fork = next(x for x in out["weaknesses"] if x["key"] == "missed:fork")
    assert fork["puzzle_first_try_pct"] == {"before_last_report": 50.0, "since_last_report": 80.0}


# ---- the AI's trend statements (FR-10.73) ----


def _cmp(new_games: range = range(10, 20)) -> Comparison:
    c = compare(side(2, 2, new_games, [w("missed:fork", 3.0), w("allowed:pin", 3.0)]), [OLD])
    assert c is not None
    return c


def test_a_true_statement_is_kept_with_its_text_cleaned() -> None:
    raw = [{"key": "missed:fork", "change": "improved", "comment": "  Better  now, see https://example.com/x  "}]
    notes, dropped = validate_trend(raw, _cmp())
    assert dropped == 0
    assert notes[0].key == "missed:fork" and "example.com" not in notes[0].comment and "  " not in notes[0].comment


def test_a_statement_that_contradicts_the_numbers_is_dropped() -> None:
    notes, dropped = validate_trend([{"key": "allowed:pin", "change": "improved", "comment": "Great!"}], _cmp())
    assert notes == [] and dropped == 1


def test_improvement_with_too_few_new_games_is_dropped() -> None:
    raw = [{"key": "missed:fork", "change": "improved", "comment": "Better."}]
    notes, dropped = validate_trend(raw, _cmp(range(5, 14)))
    assert notes == [] and dropped == 1


def test_an_unknown_key_or_a_bad_shape_is_dropped() -> None:
    raw = [
        {"key": "missed:invented", "change": "worse", "comment": "x"},
        {"key": "missed:fork", "change": "sideways", "comment": "x"},
        {"key": "missed:fork", "change": "improved", "comment": ""},
        {"key": "missed:fork", "change": "improved"},
        "nonsense",
    ]
    assert validate_trend(raw, _cmp()) == ([], 5)
    assert validate_trend("not a list", _cmp()) == ([], 0)


def test_no_comparison_keeps_no_statements() -> None:
    assert validate_trend([{"key": "k", "change": "same", "comment": "x"}], None) == ([], 1)


def test_one_statement_per_weakness() -> None:
    raw = [{"key": "missed:fork", "change": "improved", "comment": "a"}, {"key": "missed:fork", "change": "improved", "comment": "b"}]  # fmt: skip
    notes, dropped = validate_trend(raw, _cmp())
    assert [n.comment for n in notes] == ["a"] and dropped == 1
