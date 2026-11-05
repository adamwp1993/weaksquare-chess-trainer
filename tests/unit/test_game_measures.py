"""Whole-game measures and weaknesses (v0.11, FR-10.53, FR-10.57): the 5-game guard on every measure, and
each kind's occurrences and rate on synthetic digests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from weaksquare.core.digest import Digest, Moment, PawnStructure, TimeUse
from weaksquare.core.game_measures import MIN_GAMES, build_measures, game_weaknesses


def dg(**kw: Any) -> Digest:
    base: dict[str, Any] = {
        "color": "white",
        "result": "win",
        "eco": "B90",
        "opening": "Sicilian Defense: Najdorf Variation",
        "family": "Sicilian Defense",
        "plies": 80,
        "moments": (),
        "castled_ply": 9,
        "opp_castled_ply": 10,
        "moves_before_castling": 4,
        "minors_developed": 4,
        "early_queen_moves": 0,
        "castled_late": False,
        "structure": PawnStructure(),
        "opp_structure": PawnStructure(),
        "trades_ahead": 0,
        "trades_behind": 0,
        "eval_opening_end": 0,
        "opening_errors": 0,
        "errors_by_phase": {"opening": 0, "middlegame": 0, "endgame": 0},
    }
    base.update(kw)
    return Digest(**base)


def m(ply: int, swing: int = 300, phase: str = "middlegame", cls: str = "blunder", **kw: Any) -> Moment:
    return Moment(
        ply=ply, move=f"{(ply + 1) // 2}. Nf3", fen="8/8/8/8/8/8/8/8 w - - 0 1", played="Nf3", best="Nc3",
        eval_before=0, swing=swing, classification=cls, kind="other", phase=phase, **kw,
    )  # fmt: skip


def games(*ds: Digest) -> list[tuple[int, Digest]]:
    return list(enumerate(ds, start=1))


def keys(ds: list[tuple[int, Digest]]) -> dict[str, Any]:
    return {w.key: w for w in game_weaknesses(ds, build_measures(ds))}


def test_an_opening_needs_five_games() -> None:
    bad = dg(eval_opening_end=-150, result="loss")
    four = games(*[bad] * 4, *[dg(family="Italian Game")] * 6)
    ms = build_measures(four)
    sic = next(o for o in ms.openings if o.family == "Sicilian Defense")
    assert sic.games == 4 and sic.enough is False and sic.score == 0.0 and sic.avg_eval_end == -150
    assert "opening:Sicilian Defense" not in keys(four)
    five = games(*[bad] * 4, dg(), *[dg(family="Italian Game")] * 5)
    w = keys(five)["opening:Sicilian Defense"]
    assert w.count == 4 and w.per10 == 4.0 and w.kind == "opening"
    assert w.severity == 100  # no moment: the default severity


def test_an_opening_error_counts_and_links_to_its_moment() -> None:
    early = dg(opening_errors=1, moments=(m(17, swing=250, phase="opening"),))
    w = keys(games(early, *[dg()] * 4))["opening:Sicilian Defense"]
    assert w.count == 1 and w.severity == 250
    assert (w.examples[0].game_id, w.examples[0].ply) == (1, 16)  # 0-based


def test_endgame_types_need_five_games_and_count_endgame_errors() -> None:
    rook = dg(endgame="rook", endgame_errors=1, result="loss", moments=(m(61, phase="endgame"),))
    clean = dg(endgame="rook")
    four = games(*[rook] * 3, clean)
    assert build_measures(four).endgames[0].enough is False
    assert "endgame:rook" not in keys(four)
    five = games(*[rook] * 3, clean, clean)
    row = build_measures(five).endgames[0]
    assert (row.type, row.games, row.wins, row.losses, row.errors, row.enough) == ("rook", 5, 2, 3, 3, True)
    w = keys(five)["endgame:rook"]
    assert w.count == 3 and w.per10 == 6.0 and w.themes == ("rookEndgame",)


def test_conversion_from_plus_two() -> None:
    held_won = dg(held_plus2=True)
    held_drawn = dg(held_plus2=True, result="draw", moments=(m(50, swing=400),))
    four = games(held_won, held_won, held_won, held_drawn, dg())
    assert build_measures(four).conversion.enough is False
    assert "phase:conversion" not in keys(four)
    five = games(held_won, held_won, held_won, held_drawn, held_drawn)
    conv = build_measures(five).conversion
    assert (conv.games, conv.hits, conv.rate, conv.enough) == (5, 3, 60.0, True)
    w = keys(five)["phase:conversion"]
    assert w.count == 2 and w.severity == 400


def test_saves_from_minus_two() -> None:
    lost = dg(held_minus2=True, result="loss")
    saved = dg(held_minus2=True, result="draw")
    s = build_measures(games(lost, lost, saved, saved, saved)).saves
    assert (s.games, s.hits, s.rate, s.enough) == (5, 3, 60.0, True)
    assert build_measures(games(lost, saved)).saves.enough is False


def _clock(low_moves: int, low_errors: int, other_moves: int = 30, other_errors: int = 0) -> TimeUse:
    return TimeUse(True, low_moves, low_errors, low_errors, other_moves, other_errors, other_errors)


def test_low_clock_blunders_against_the_rest() -> None:
    hurried = dg(time=_clock(5, 1), moments=(m(70, swing=500, clock_pct=4),))
    calm = dg(time=_clock(5, 0))
    ds = games(hurried, hurried, calm, calm, calm)
    t = build_measures(ds).time
    assert (t.games, t.low_moves, t.low_errors, t.low_error_rate, t.other_error_rate) == (5, 25, 2, 8.0, 0.0)
    w = keys(ds)["time:low_clock"]
    assert w.count == 2 and w.severity == 500
    # the same number of errors when your clock is fine: not a time weakness
    sloppy = games(*[replace(d, time=_clock(5, 1, 30, 10)) for _, d in ds])
    assert "time:low_clock" not in keys(sloppy)
    assert "time:low_clock" not in keys(ds[:4])  # 4 games with low-clock moves: not enough


def test_castling_late_only_when_it_costs_you() -> None:
    late_loss = dg(castled_late=True, castled_ply=None, result="loss")
    on_time_win = dg()
    ds = games(late_loss, late_loss, on_time_win, on_time_win, on_time_win)
    k = build_measures(ds).king
    assert (k.games, k.late, k.late_score, k.on_time_score, k.enough) == (5, 2, 0.0, 100.0, True)
    w = keys(ds)["habit:castledLate"]
    assert w.count == 2 and w.kind == "habit" and w.examples[0].ply == 22  # your 12th move as White
    late_win = dg(castled_late=True, result="win")
    assert "habit:castledLate" not in keys(games(late_win, late_win, *[on_time_win] * 3))
    assert "habit:castledLate" not in keys(games(late_loss, late_loss, on_time_win, on_time_win))


def test_errors_per_phase_per_10_games() -> None:
    ds = games(dg(errors_by_phase={"opening": 1, "middlegame": 2, "endgame": 0}), dg())
    assert build_measures(ds).errors_per10_by_phase == {"opening": 5.0, "middlegame": 10.0, "endgame": 0.0}


@pytest.mark.parametrize("n", range(MIN_GAMES))
def test_every_measure_is_guarded_below_five_games(n: int) -> None:
    d = dg(
        eval_opening_end=-300, opening_errors=2, endgame="pawn", endgame_errors=1, held_plus2=True,
        held_minus2=True, result="loss", castled_late=True, time=_clock(5, 2),
    )  # fmt: skip
    ds = games(*[d] * n)
    ms = build_measures(ds)
    flags = [o.enough for o in ms.openings] + [e.enough for e in ms.endgames]
    flags += [ms.conversion.enough, ms.saves.enough, ms.time.enough, ms.king.enough]
    assert not any(flags)
    assert game_weaknesses(ds, ms) == []


def test_ranked_by_score() -> None:
    bad = dg(eval_opening_end=-150, endgame="rook", endgame_errors=1, moments=(m(61, swing=900, phase="endgame"),))
    ws = game_weaknesses(games(*[bad] * 5), build_measures(games(*[bad] * 5)))
    assert [w.key for w in ws] == ["endgame:rook", "opening:Sicilian Defense"]
    assert ws[0].score > ws[1].score
