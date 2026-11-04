"""QA v0.2: edge cases beyond the builder's tests (history filters, help, openings, quality, ratios,
presets, settings). Written by the independent QA pass (qa/QA-v0.2.md)."""

from __future__ import annotations

import dataclasses
import sqlite3

import chess
import pytest

from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.filters import FilterSpec, RatioBucket

OPEN = {"min_popularity": None, "min_plays": None, "exclude_solved_here": False}


def _row(services, puzzle_id: str) -> sqlite3.Row:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT * FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()


def _attempts(services) -> list[sqlite3.Row]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()


def _serve(services, puzzle_id: str, rating: int):  # type: ignore[no-untyped-def]
    """Start a session pinned to this puzzle's rating and move on until it's served."""
    sid = services.sessions.start(FilterSpec(rating_min=rating, rating_max=rating, queue_size=None, **OPEN)).session_id
    while (view := services.sessions.next_puzzle(sid)) is not None:
        if view.puzzle_id == puzzle_id:
            return sid, view
    raise AssertionError(f"{puzzle_id} never came up")


def _win(services, puzzle_id: str, rating: int) -> None:  # type: ignore[no-untyped-def]
    sid, _ = _serve(services, puzzle_id, rating)
    for uci in _row(services, puzzle_id)["moves"].split()[1::2]:
        services.sessions.submit_move(sid, uci)


def _lose(services, puzzle_id: str, rating: int) -> None:  # type: ignore[no-untyped-def]
    sid, _ = _serve(services, puzzle_id, rating)
    services.sessions.request_help(sid, "hint")


def _a_puzzle(services, min_length: int = 1) -> tuple[str, int]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        r = conn.execute(
            "SELECT id, rating FROM pz.puzzles WHERE length >= ? ORDER BY n LIMIT 1", (min_length,)
        ).fetchone()
    return r["id"], r["rating"]


# ---- FR-3.9 history: the sequence of results decides --------------------------------------------
def test_history_filters_follow_the_latest_result(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services)
    pinned = {"rating_min": rating, "rating_max": rating, "min_popularity": None, "min_plays": None}
    everything = services.sessions._puzzles.count(FilterSpec(**{**pinned, "exclude_solved_here": False}))

    def counts() -> tuple[int, int]:
        excl = services.sessions._puzzles.count(FilterSpec(**pinned, exclude_solved_here=True))
        misses = services.sessions._puzzles.count(FilterSpec(**pinned, only_my_misses=True))
        return excl, misses

    assert counts() == (everything, 0)
    _lose(services, pid, rating)  # failed only: still offered, and it's a miss
    assert counts() == (everything, 1)
    _win(services, pid, rating)  # solved since: hidden, and no longer a miss
    assert counts() == (everything - 1, 0)
    _lose(services, pid, rating)  # missed again after a win: still hidden by Exclude solved, but a miss
    assert counts() == (everything - 1, 1)
    # Only my misses overrides Exclude solved (plan build note): the puzzle is served.
    sid = services.sessions.start(FilterSpec(**pinned, only_my_misses=True, exclude_solved_here=True)).session_id
    view = services.sessions.next_puzzle(sid)
    assert view is not None and view.puzzle_id == pid


def test_only_my_misses_with_no_history_cannot_start(services) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.sessions.start(FilterSpec(only_my_misses=True))


# ---- §7.2 help ----------------------------------------------------------------------------------
def test_hint_mid_line_points_at_the_next_player_move(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services, min_length=2)
    moves = _row(services, pid)["moves"].split()
    sid, _ = _serve(services, pid, rating)
    services.sessions.submit_move(sid, moves[1])  # first player move right, reply played
    hint = services.sessions.request_help(sid, "hint")
    assert hint.help.hint_square == moves[3][:2]
    assert hint.outcome is not None and not hint.outcome.win
    (row,) = [r for r in _attempts(services) if r["puzzle_id"] == pid]
    assert (row["first_move_correct"], row["line_correct"], row["help_used"]) == (1, 0, "hint")


def test_answer_from_mid_line_is_legal_from_its_start(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services, min_length=2)
    moves = _row(services, pid)["moves"].split()
    sid, _ = _serve(services, pid, rating)
    services.sessions.submit_move(sid, moves[1])
    services.sessions.request_help(sid, "hint")
    ans = services.sessions.request_help(sid, "answer").help
    board = chess.Board(ans.answer_fen)
    for uci in ans.answer_moves:
        move = chess.Move.from_uci(uci)
        assert move in board.legal_moves
        board.push(move)
    assert list(ans.answer_moves) == moves[3:]
    assert len(ans.answer_sounds) == len(ans.answer_moves)


def test_hint_after_a_wrong_move_is_free(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services)
    row = _row(services, pid)
    moves = row["moves"].split()
    board = chess.Board(row["fen"])
    board.push_uci(moves[0])
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != moves[1] and not board.gives_check(m))
    sid, _ = _serve(services, pid, rating)
    assert services.sessions.submit_move(sid, wrong).outcome is not None
    again = services.sessions.request_help(sid, "hint")
    assert again.outcome is None and again.help.hint_square == moves[1][:2]
    answer = services.sessions.request_help(sid, "answer")  # no second Hint needed once decided
    assert answer.outcome is None
    rows = [r for r in _attempts(services) if r["puzzle_id"] == pid]
    assert [(r["win"], r["help_used"]) for r in rows] == [(0, "none")]


def test_repeated_hints_record_one_loss(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services)
    sid, _ = _serve(services, pid, rating)
    for _ in range(5):
        services.sessions.request_help(sid, "hint")
    assert len([r for r in _attempts(services) if r["puzzle_id"] == pid]) == 1


def test_hint_after_solving_is_refused_but_answer_is_free(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services)
    _win(services, pid, rating)
    sid, _ = _serve(services, pid, rating)
    for uci in _row(services, pid)["moves"].split()[1::2]:
        services.sessions.submit_move(sid, uci)
    with pytest.raises(ConflictError):
        services.sessions.request_help(sid, "hint")
    assert services.sessions.request_help(sid, "answer").outcome is None
    wins = [r["win"] for r in _attempts(services) if r["puzzle_id"] == pid]
    assert wins == [1, 1]


# ---- FR-3.7 / FR-3.8 / FR-3.10 validation and boundaries ----------------------------------------
def test_unknown_opening_matches_nothing(services) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(openings=("No_Such_Opening",), **OPEN)
    assert services.mixer.count(spec) == 0
    with pytest.raises(ValidationError):
        services.sessions.start(spec)


def test_a_family_includes_its_variations(services) -> None:  # type: ignore[no-untyped-def]
    catalog = services.mixer.opening_catalog()
    fam = next(f for f in catalog if f.variations)
    family_count = services.mixer.count(FilterSpec(openings=(fam.family.tag,), **OPEN))
    var_total = sum(services.mixer.count(FilterSpec(openings=(v.tag,), **OPEN)) for v in fam.variations)
    assert family_count >= var_total > 0
    both = services.mixer.count(FilterSpec(openings=(fam.family.tag, fam.variations[0].tag), **OPEN))
    assert both == family_count


@pytest.mark.parametrize("pop", [-100, 100])
def test_popularity_bounds_accepted(services, pop: int) -> None:  # type: ignore[no-untyped-def]
    FilterSpec(min_popularity=pop).validate()


@pytest.mark.parametrize(
    "kw",
    [
        {"min_popularity": 101},
        {"min_popularity": -101},
        {"min_plays": -1},
        {"ratios": (RatioBucket(("fork",), 50), RatioBucket(("pin",), 49))},
        {"ratios": (RatioBucket(("fork",), 100),)},
        {"ratios": (RatioBucket(("fork",), 50), RatioBucket((), 50))},
        {"ratios": (RatioBucket(("fork",), 0), RatioBucket(("pin",), 100))},
        {"ratios": (RatioBucket(("fork",), 50), RatioBucket(("pin",), 50)), "themes": ("mate",)},
    ],
)
def test_bad_quality_and_ratio_values_refused(kw: dict) -> None:
    with pytest.raises(ValidationError):
        FilterSpec(**kw).validate()  # type: ignore[arg-type]


def test_popularity_threshold_is_inclusive(services) -> None:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        pop = conn.execute("SELECT popularity FROM pz.puzzles ORDER BY n LIMIT 1").fetchone()[0]
        expected = conn.execute("SELECT COUNT(*) FROM pz.puzzles WHERE popularity >= ?", (pop,)).fetchone()[0]
    assert services.mixer.count(FilterSpec(min_popularity=pop, min_plays=None, exclude_solved_here=False)) == expected


def test_ratio_groups_with_an_unknown_theme_and_overlaps(services) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(ratios=(RatioBucket(("fork",), 40), RatioBucket(("fork", "pin"), 40),
                              RatioBucket(("noSuchTheme",), 20)), **OPEN)  # fmt: skip
    total, groups = services.mixer.counts_with_buckets(spec)
    fork = services.mixer.count(FilterSpec(themes=("fork",), **OPEN))
    fork_pin = services.mixer.count(FilterSpec(themes=("fork", "pin"), **OPEN))
    assert groups == [fork, fork_pin, 0] and total == fork_pin
    info = services.sessions.start(dataclasses.replace(spec, queue_size=10))
    assert info.empty_buckets == [2]


def test_ratios_respect_exclude_solved(services) -> None:  # type: ignore[no-untyped-def]
    pid, rating = _a_puzzle(services)
    themes = _row(services, pid)["themes"].split()
    spec = FilterSpec(ratios=(RatioBucket((themes[0],), 50), RatioBucket(("fork",), 50)),
                      rating_min=rating, rating_max=rating, min_popularity=None, min_plays=None)  # fmt: skip
    before, (g0, _) = services.mixer.counts_with_buckets(spec)
    _win(services, pid, rating)
    after, (g0_after, _) = services.mixer.counts_with_buckets(spec)
    assert (before - after, g0 - g0_after) == (1, 1)


# ---- FR-3.13 / settings boundaries --------------------------------------------------------------
def test_preset_name_of_exactly_60_characters(services) -> None:  # type: ignore[no-untyped-def]
    services.presets.save("x" * 60, FilterSpec())
    assert [p.name for p in services.presets.list()] == ["x" * 60]


def test_preset_with_invalid_filters_is_refused_over_the_bridge(paths, clock, services) -> None:  # type: ignore[no-untyped-def]
    from tests.helpers import build_api

    api = build_api(paths, clock)
    bad = {**FilterSpec().to_json(), "min_popularity": 500}
    assert api.save_preset("Bad", bad)["error"]["code"] == "invalid_argument"
    assert api.save_preset("Mine", {**FilterSpec().to_json(), "source": "mine"})["ok"] is False
    assert api.list_presets()["data"] == []


@pytest.mark.parametrize("volume", [0, 100])
def test_volume_bounds_accepted(services, volume: int) -> None:  # type: ignore[no-untyped-def]
    services.ui_settings.set("ui.sounds", {"on": True, "volume": volume, "set": "piano"})
    s = services.ui_settings.get().sounds
    assert (s.on, s.volume, s.set) == (True, volume, "piano")


@pytest.mark.parametrize(
    "value",
    [
        {"on": True, "volume": 101, "set": "sfx"},
        {"on": True, "volume": -1, "set": "sfx"},
        {"on": True, "volume": 50, "set": "standard"},  # Lichess's non-free set must never be selectable
        {"on": "yes", "volume": 50, "set": "sfx"},
    ],
)
def test_bad_sound_settings_refused(services, value: dict) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.ui_settings.set("ui.sounds", value)


def test_sound_defaults_match_fr_1_13(services) -> None:  # type: ignore[no-untyped-def]
    s = services.ui_settings.get()
    assert (s.sounds.on, s.sounds.volume, s.sounds.set) == (True, 70, "sfx")
    assert s.color_scheme == "light" and s.auto_check is True
