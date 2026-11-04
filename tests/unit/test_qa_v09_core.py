"""QA v0.9 (independent): pure edge cases of Game Review AI's context and validation, beyond the builder's
tests: repeated moments, arrows past the cap, a bool turning point, a bad stored engine line, a promotion in
the better line, and the recommended preset's limits (FR-11.18, Adam's minimal preset)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import chess
import pytest

from tests.unit.test_game_explain import _answer, _game, _narrative_input
from weaksquare.core.engine import EngineLine
from weaksquare.core.game_explain import (
    NarrativeInput,
    build_narrative_prompt,
    move_input,
    validate_narrative,
)
from weaksquare.core.game_review import grade_game
from weaksquare.core.preset_suggestion import preset_themes, validate_preset


def test_qa_a_repeated_moment_is_dropped_and_the_first_kept() -> None:
    first = {"ply": 5, "played": "Nf6", "text": "first", "annotations": [], "better_line": []}
    second = {**first, "text": "second"}
    n = validate_narrative(_narrative_input(), _answer(moments=[first, second]))
    assert n is not None and [m.text for m in n.moments] == ["first"] and n.discarded == 1


def test_qa_arrows_past_the_cap_are_dropped_and_counted() -> None:
    arrow = {"type": "arrow", "from": "h5", "to": "f7", "color": "red"}
    raw = {"ply": 5, "played": "Nf6", "text": "x", "annotations": [arrow] * 8, "better_line": []}  # cap 6
    n = validate_narrative(_narrative_input(), _answer(moments=[raw]))
    assert n is not None and len(n.moments[0].annotations) == 6 and n.discarded == 2


def test_qa_a_bool_turning_point_is_dropped() -> None:
    n = validate_narrative(_narrative_input(), _answer(turning_point_ply=True))
    assert n is not None and n.turning_point is None and n.discarded == 1


def test_qa_html_in_the_text_is_kept_as_text_for_the_ui_to_escape() -> None:
    raw = {"ply": 5, "played": "Nf6", "text": "<img src=x onerror=alert(1)>", "annotations": [], "better_line": []}
    n = validate_narrative(_narrative_input(), _answer(moments=[raw]))
    assert n is not None and n.moments[0].text == "<img src=x onerror=alert(1)>"


def test_qa_a_bad_stored_engine_line_never_crashes_a_prompt() -> None:
    fen, moves, rows = _game()
    bad = replace(rows[5], lines=(EngineLine(cp=-40, mate=None, pv=("d8e7", "a1a8", "zz99")),))
    inp = move_input(bad)
    assert inp is not None and inp.moves[1:] == ("d8e7",)
    rows2 = list(rows)
    rows2[5] = bad
    prompt = build_narrative_prompt(NarrativeInput(fen, moves, tuple(rows2), "black", "loss", (5,)))
    assert "best was Qe7" in prompt
    assert move_input(replace(rows[5], lines=())) is None


def test_qa_a_promotion_in_the_better_line_is_validated() -> None:
    fen = "8/4P3/8/8/8/8/k7/6K1 w - - 0 1"
    moves = ("g1f1", "a2b2")
    analyses = [
        [EngineLine(cp=900, mate=None, pv=("e7e8q", "a2b2"))],
        [EngineLine(cp=-300, mate=None, pv=("a2b3",))],
        None,
    ]
    rows = grade_game(fen, moves, analyses)
    assert rows[0].classification in ("mistake", "blunder")
    inp = NarrativeInput(fen, moves, tuple(rows), "white", "draw", (0,))
    raw = {"ply": 0, "played": "Kf1", "text": "Promote.", "annotations": [], "better_line": ["e8=Q", "Kb2"]}
    n = validate_narrative(inp, _answer(moments=[raw], turning_point_ply=0))
    assert n is not None and n.moments[0].better_uci == ("e7e8q", "a2b2")
    prompt = build_narrative_prompt(inp)
    assert "Start position (FEN): " + fen in prompt and "1. Kf1 Kb2" in prompt


@pytest.mark.parametrize(
    ("raw", "themes", "lo", "hi", "dropped"),
    [
        ({"themes": ["fork", "pin", "skewer", "mateIn2"], "rating_min": None, "rating_max": None},
         ("fork", "pin", "skewer"), None, None, 1),
        ({"themes": ["fork", "middlegame", "long", "master"], "rating_min": 1200, "rating_max": 1600},
         ("fork",), 1200, 1600, 3),
        ({"themes": ["fork"], "rating_min": "1200", "rating_max": 1600}, ("fork",), None, 1600, 1),
        ({"themes": ["fork"], "rating_min": 1800, "rating_max": 1200}, ("fork",), None, None, 2),
        ({"themes": ["fork"], "rating_min": -5, "rating_max": 99999}, ("fork",), None, None, 2),
        ({"themes": ["fork", "fork"], "rating_min": None, "rating_max": None}, ("fork",), None, None, 1),
    ],
)  # fmt: skip
def test_qa_preset_limits(raw: dict[str, Any], themes: tuple[str, ...], lo: Any, hi: Any, dropped: int) -> None:
    p, d = validate_preset(raw)
    assert p is not None and (p.themes, p.rating_min, p.rating_max, d) == (themes, lo, hi, dropped)


def test_qa_no_valid_theme_means_no_preset_and_only_motifs_and_mates_are_offered() -> None:
    assert validate_preset({"themes": ["opening", "endgame"], "rating_min": 1000, "rating_max": 1500})[0] is None
    assert validate_preset(None) == (None, 0)
    allowed = preset_themes()
    assert "fork" in allowed and "mateIn1" in allowed
    for key in ("opening", "middlegame", "endgame", "short", "long", "master", "crushing", "oneMove"):
        assert key not in allowed, key


def test_qa_the_narrative_round_trips_through_the_cache_json() -> None:
    n = validate_narrative(_narrative_input(), _answer())
    assert n is not None
    assert json.loads(n.to_json())["moments"][0]["better_uci"] == ["d8e7", "b1c3"]
    assert chess.Move.from_uci(n.moments[0].better_uci[0])
