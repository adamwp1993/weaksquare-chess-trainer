"""The Coach's free report and the Suggested mix (v0.10, §10.5 and §10.7): pure, on hand-made errors."""

from __future__ import annotations

from weaksquare.core.coach import ErrorRow, GameInfo, PuzzleTheme, build_report, trend
from weaksquare.core.filters import FilterSpec
from weaksquare.core.suggested_mix import LONG_THEMES, MY_SHARE, build_suggestion, mode_for

GAMES = [GameInfo(i, f"2026-10-{i + 1:02d}", "rapid", "loss" if i % 2 else "win") for i in range(10)]


def err(gid: int, ply: int, kind: str | None, themes: tuple[str, ...] = (), habits: tuple[str, ...] = (),
        cls: str = "blunder", loss: int = 300) -> ErrorRow:  # fmt: skip
    return ErrorRow(gid, ply, cls, kind, "middlegame", loss, themes, habits, False)


ERRORS = [
    *[err(g, 20, "allowed", ("fork", "middlegame", "short")) for g in range(6)],  # 6 allowed forks
    *[err(g, 30, "missed", ("pin", "advantage", "short"), loss=200) for g in range(3)],  # 3 missed pins
    err(1, 24, "other", (), ("hungPiece",), cls="mistake", loss=150),
    err(2, 4, "allowed", ("fork",)),  # in the opening: skipped
    err(3, 40, None, (), (), cls="inaccuracy", loss=60),
]


def test_rates_are_per_10_games_and_rank_by_rate_times_severity() -> None:
    r = build_report("games", GAMES, ERRORS, {})
    assert r.games == 10
    assert [w.key for w in r.allowed] == ["allowed:fork"]
    fork = r.allowed[0]
    assert fork.count == 6 and fork.per10 == 6.0 and fork.severity == 300 and fork.score == 18.0
    assert r.missed[0].key == "missed:pin" and r.missed[0].per10 == 3.0 and r.missed[0].multi_move == 3
    assert [w.key for w in r.habits] == ["habit:hungPiece"]
    assert r.weaknesses[0].key == "allowed:fork"
    assert r.per10 == {"blunders": 9.0, "mistakes": 1.0, "inaccuracies": 1.0}
    assert not any(w.name in ("middlegame", "short", "advantage") for w in r.missed + r.allowed)  # not weaknesses


def test_the_opening_is_skipped() -> None:
    r = build_report("games", GAMES, [err(2, 4, "allowed", ("fork",))], {})
    assert r.allowed == [] and r.per10["blunders"] == 0


def test_reasons_are_counted_per_weakness_and_overall() -> None:
    reasons = {(0, 20): "didntLook", (1, 20): "didntLook", (2, 20): "miscalculated"}
    r = build_report("games", GAMES, ERRORS, reasons)
    assert r.allowed[0].reasons == {"didntLook": 2, "miscalculated": 1}
    assert r.reasons == {"didntLook": 2, "miscalculated": 1}


def test_examples_are_the_worst_moments_with_game_and_ply() -> None:
    r = build_report("games", GAMES, ERRORS, {})
    assert len(r.allowed[0].examples) == 5 and all(e.ply == 20 for e in r.allowed[0].examples)


def test_puzzle_history_source_and_the_gap_table() -> None:
    hist = [PuzzleTheme("fork", 30, 27), PuzzleTheme("pin", 20, 8, lichess_nb=10, lichess_first_wins=4)]
    r = build_report("puzzles", GAMES, ERRORS, {}, hist)
    assert r.games == 0 and r.allowed == []
    assert [w.key for w in r.puzzles] == ["puzzle:pin", "puzzle:fork"]
    assert r.puzzles[0].puzzle_accuracy == 0.4
    both = build_report("both", GAMES, ERRORS, {}, hist)
    fork = next(g for g in both.gap if g.theme == "fork")
    assert fork.puzzle_accuracy == 0.9 and fork.allowed_per10 == 6.0  # solved in puzzles, walked into in games
    assert both.gap[0].theme == "fork"


def test_trend_against_the_previous_report() -> None:
    old = build_report("games", GAMES, ERRORS[:3], {})
    new = build_report("games", GAMES, ERRORS, {})
    t = trend(new, old.to_json())
    assert t["allowed:fork"] == 3.0 and t["missed:pin"] == 3.0
    assert trend(new, None) == {}


def test_suggestion_ratios_long_share_and_rating_band() -> None:
    r = build_report("games", GAMES, ERRORS, {})
    s = build_suggestion(r, puzzle_rating=1800, recent_accuracy=0.75, has_game_puzzles=True)
    assert s is not None
    groups = {b.themes: b.weight for b in s.spec.ratios}
    assert sum(groups.values()) == 100
    assert groups[LONG_THEMES] >= 10  # never left out
    assert groups[("fork",)] > groups[("pin",)]  # the #1 leak gets the biggest share
    assert (s.spec.rating_min, s.spec.rating_max) == (1650, 1950)
    assert s.mode == "danger_spotting"  # Allowed forks dominate, with no reasons tagged
    assert s.spec.source == "lichess" and s.spec.my_share is None  # Danger spotting is Lichess-only
    assert any("per 10 games, your #1 leak" in line for line in s.why)


def test_mistake_reasons_pick_the_mode() -> None:
    reasons = {(g, 20): "miscalculated" for g in range(6)}
    r = build_report("games", GAMES, ERRORS, reasons)
    s = build_suggestion(r, puzzle_rating=None, recent_accuracy=None, has_game_puzzles=True)
    assert s is not None and s.mode == "commit_line"
    assert s.spec.source == "both" and s.spec.my_share == MY_SHARE and s.spec.my_origins == ("coach",)
    assert (s.spec.rating_min, s.spec.rating_max) == (1350, 1650)  # 1500 when the rating is unknown
    FilterSpec.from_json(s.spec.to_json())  # a valid saved filter


def test_fewer_than_five_tagged_misses_keeps_the_default_mode() -> None:
    r = build_report("games", GAMES, ERRORS, {(0, 20): "miscalculated"})
    assert mode_for(r.allowed[0]) == ("danger_spotting", None)


def test_unknown_pattern_lowers_the_band_and_accuracy_nudges_it() -> None:
    reasons = {(g, 20): "unknownPattern" for g in range(6)}
    r = build_report("games", GAMES, ERRORS, reasons)
    s = build_suggestion(r, puzzle_rating=1800, recent_accuracy=0.5, has_game_puzzles=False)
    assert s is not None and (s.spec.rating_min, s.spec.rating_max) == (1350, 1650)  # -100, then -200


def test_rushed_is_flagged_as_time_use() -> None:
    reasons = {(g, 20): "rushed" for g in range(6)}
    r = build_report("games", GAMES, ERRORS, reasons)
    s = build_suggestion(r, puzzle_rating=1800, recent_accuracy=None, has_game_puzzles=False)
    assert s is not None and any("time-use issue" in line for line in s.why)


def test_no_weaknesses_means_no_suggestion() -> None:
    r = build_report("games", GAMES, [], {})
    assert build_suggestion(r, puzzle_rating=None, recent_accuracy=None, has_game_puzzles=False) is None
