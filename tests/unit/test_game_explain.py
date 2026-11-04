"""Game Review AI (v0.9, §11.4): the anonymized context, Explain this move's input, and validation of
Explain my game's answer. ROADMAP v0.9 *Done when*: "an anonymization test (no names, URLs, dates or
clocks in the prompt)"."""

from __future__ import annotations

import json
from typing import Any

import chess
import pytest

from weaksquare.core.engine import EngineLine
from weaksquare.core.explain import SCHEMA, build_prompt, validate
from weaksquare.core.game_explain import (
    NARRATIVE_SCHEMA,
    NARRATIVE_SYSTEM_PROMPT,
    GameNarrative,
    NarrativeInput,
    build_narrative_prompt,
    move_input,
    san_moves,
    validate_narrative,
)
from weaksquare.core.game_review import grade_game, key_moments
from weaksquare.core.games import parse_single_pgn
from weaksquare.core.preset_suggestion import validate_preset
from weaksquare.core.puzzle import NO_PREMOVE

# Everything a real export carries that must never reach an LLM (FR-8.16, FR-11.19). The values are
# made-up (SR-12a) but distinctive, so the test can search the prompt for each one.
PGN = """[Event "Rated Blitz game"]
[Site "https://lichess.org/AbCdEfGh"]
[Date "2026.10.30"]
[UTCDate "2026.10.30"]
[UTCTime "21:14:05"]
[White "ZzSecretWhiteName"]
[Black "QqSecretBlackName"]
[WhiteElo "1876"]
[BlackElo "1923"]
[TimeControl "180+2"]
[Termination "Normal"]
[Annotator "SomeCoachName"]

1. e4 { [%clk 0:03:00] } e5 { [%clk 0:02:59] } 2. Qh5 { [%clk 0:02:57] a cheeky comment } Nc6 { [%clk 0:02:55] }
3. Bc4 { [%clk 0:02:50] } Nf6 { [%clk 0:02:31] } 4. Qxf7# { [%clk 0:02:49] } 1-0
"""
FORBIDDEN = [
    "ZzSecretWhiteName", "QqSecretBlackName", "SomeCoachName", "lichess.org", "AbCdEfGh", "https", "2026",
    "21:14", "1876", "1923", "180+2", "clk", "0:02", "cheeky", "Rated", "Blitz", "Event", "Site", "Elo",
]  # fmt: skip


def _line(cp_white: int | None, pv: str, mate_white: int | None = None) -> list[EngineLine]:
    return [EngineLine(cp=cp_white, mate=mate_white, pv=tuple(pv.split()))]


def _game() -> tuple[str, tuple[str, ...], list[Any]]:
    g = parse_single_pgn(PGN)
    analyses = [
        _line(30, "e2e4 e7e5"),
        _line(30, "e7e5 g1f3"),
        _line(40, "d1h5 b8c6"),
        _line(-60, "b8c6 f1c4"),
        _line(-50, "f1c4 d8e7"),
        [*_line(-40, "d8e7 b1c3"), EngineLine(cp=-30, mate=None, pv=("g7g6", "h5f3"))],
        _line(None, "h5f7", mate_white=1),
        None,
    ]
    return g.start_fen, g.moves, grade_game(g.start_fen, g.moves, analyses)


def _narrative_input(color: str = "black") -> NarrativeInput:
    fen, moves, rows = _game()
    plies = tuple(r.ply for r in key_moments(rows, color, 5)) if color != "both" else (5,)
    return NarrativeInput(fen, moves, tuple(rows), color, "loss", plies)


# ---- anonymization (FR-8.16, FR-11.19) ----------------------------------------------------------------


def test_the_narrative_prompt_holds_no_pgn_header_name_rating_date_url_clock_or_comment() -> None:
    prompt = build_narrative_prompt(_narrative_input())
    for word in FORBIDDEN:
        assert word not in prompt, word
    assert "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#" in prompt  # the SAN move list is all of the game text
    assert "You played Black." in prompt and "Result: you lost." in prompt
    assert "ply 5" in prompt and "best was Qe7" in prompt


def test_the_move_prompt_holds_no_game_metadata_either() -> None:
    _, _, rows = _game()
    inp = move_input(rows[5])
    assert inp is not None
    prompt = build_prompt(inp)
    for word in FORBIDDEN:
        assert word not in prompt, word


def test_san_moves_numbers_a_game_that_starts_with_black() -> None:
    fen = "4k3/8/8/8/8/8/4P3/4K3 b - - 0 30"
    assert san_moves(fen, ["e8d7", "e2e4"]) == "30... Kd7 31. e4"


# ---- Explain this move (FR-11.17) -------------------------------------------------------------------


def test_move_input_uses_the_best_line_as_the_solution_and_the_played_move_as_the_refutation() -> None:
    _, _, rows = _game()
    nf6 = rows[5]
    inp = move_input(nf6)
    assert inp is not None
    assert inp.fen == nf6.fen_before and inp.moves == (NO_PREMOVE, "d8e7")  # cut to whole moves of yours
    assert inp.refutation is not None and inp.refutation.wrong_move == "g8f6"
    assert inp.refutation.line == ("h5f7",)
    assert inp.game_move is not None and inp.game_move.classification == "blunder"
    prompt = build_prompt(inp)
    assert "Mode: Game Review" in prompt and "they played Nf6" in prompt and "went wrong with Nf6" in prompt
    assert "Qxf7#" in prompt  # the refutation in SAN
    # Explain's validation is reused unchanged: the step must be the best move.
    answer = {"summary": "Qe7 defends f7.", "key_ideas": ["defence"], "steps": [
        {"ply": 0, "move": "Qe7", "text": "It covers f7.", "variation": [],
         "annotations": [{"type": "arrow", "from": "d8", "to": "e7", "color": "green"}]},
        {"ply": 0, "move": "Nf6", "text": "Wrong move.", "variation": [], "annotations": []},
    ]}  # fmt: skip
    x = validate(inp, json.dumps(answer))
    assert x is not None and [s.san for s in x.steps] == ["Qe7"] and x.discarded == 1


def test_move_input_for_the_best_move_has_no_refutation_and_no_best_line_means_none() -> None:
    _, _, rows = _game()
    assert rows[0].classification == "best"
    inp = move_input(rows[0])
    assert inp is not None and inp.refutation is None
    assert "the best move" in build_prompt(inp) and "used help" not in build_prompt(inp)
    from dataclasses import replace

    assert move_input(replace(rows[0], lines=())) is None
    assert move_input(replace(rows[0], lines=(EngineLine(0, None, ("e7e5",)),))) is None  # illegal stored line


# ---- Explain my game: validation (FR-11.18) ---------------------------------------------------------------


def _answer(**over: Any) -> str:
    body: dict[str, Any] = {
        "opening_summary": "You met an early queen sortie.",
        "turning_point_ply": 5,
        "recurring_themes": ["king safety"],
        "takeaways": ["Check what the queen attacks.", "Defend f7 first."],
        "moments": [{
            "ply": 5, "played": "Nf6", "text": "Nf6 leaves f7 to the queen.",
            "annotations": [{"type": "arrow", "from": "h5", "to": "f7", "color": "red"},
                            {"type": "circle", "from": "f7", "to": None, "color": "yellow"}],
            "better_line": ["Qe7", "Nc3"],
        }],
        "preset": {"themes": ["mateIn1", "defensiveMove"], "rating_min": 1200, "rating_max": 1600},
    }  # fmt: skip
    body.update(over)
    return json.dumps(body)


def test_a_good_narrative_is_kept() -> None:
    n = validate_narrative(_narrative_input(), _answer())
    assert n is not None and n.discarded == 0
    assert n.turning_point == 5 and n.takeaways == ("Check what the queen attacks.", "Defend f7 first.")
    (m,) = n.moments
    assert (m.ply, m.played_san, m.better_line, m.better_uci) == (5, "Nf6", ("Qe7", "Nc3"), ("d8e7", "b1c3"))
    assert [a.kind for a in m.annotations] == ["arrow", "circle"]
    assert n.preset is not None and n.preset.themes == ("mateIn1", "defensiveMove")
    assert (n.preset.rating_min, n.preset.rating_max) == (1200, 1600)
    assert GameNarrative.from_json(n.to_json()) == n  # what the cache stores


@pytest.mark.parametrize(
    "moment",
    [
        {"ply": 3, "played": "Nc6"},  # not a key moment that was sent
        {"ply": 5, "played": "Nc6"},  # names another move
        {"ply": 99, "played": "Nf6"},
        {"ply": True, "played": "Nf6"},
    ],
)
def test_moments_for_other_plies_or_moves_are_dropped(moment: dict[str, Any]) -> None:
    raw = {"text": "x", "annotations": [], "better_line": [], **moment}
    n = validate_narrative(_narrative_input(), _answer(moments=[raw]))
    assert n is not None and n.moments == () and n.discarded == 1


@pytest.mark.parametrize(
    "line",
    [
        ["Qe7", "Ke3"],  # an illegal second move
        ["g6"],  # legal, but not Stockfish's best move
        ["Qe7", "Nc3", "a6", "a3", "b6", "b3", "c6"],  # too long
        ["Qe7", 5],
        ["--"],  # a null move
    ],
)
def test_bad_better_lines_are_dropped_and_counted(line: list[Any]) -> None:
    raw = {"ply": 5, "played": "Nf6", "text": "x", "annotations": [], "better_line": line}
    n = validate_narrative(_narrative_input(), _answer(moments=[raw]))
    assert n is not None and n.moments[0].better_line == () and n.discarded == 1


def test_bad_annotations_turning_point_and_texts_are_dropped() -> None:
    raw = {"ply": 5, "played": "g8f6", "text": "  \x07fine  ", "better_line": [],
           "annotations": [{"type": "arrow", "from": "z9", "to": "f7", "color": "red"},
                           {"type": "arrow", "from": "h5", "to": "f7", "color": "purple"},
                           {"type": "circle", "from": "f7", "to": None, "color": "blue"}]}  # fmt: skip
    n = validate_narrative(_narrative_input(), _answer(moments=[raw], turning_point_ply=42, takeaways=["", 3, "ok"]))
    assert n is not None
    assert n.moments[0].text == "fine" and len(n.moments[0].annotations) == 1
    assert n.turning_point is None and n.takeaways == ("ok",)
    assert n.discarded == 2 + 1 + 2


def test_answers_that_arent_the_json_asked_for_are_refused() -> None:
    inp = _narrative_input()
    for text in ["not json", "[]", json.dumps({"opening_summary": 3}), json.dumps({"moments": []})]:
        assert validate_narrative(inp, text) is None


def test_the_schema_is_strict_mode_compatible() -> None:
    def check(node: dict[str, Any]) -> None:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                check(child)
        if node.get("type") == "array":
            check(node["items"])

    check(NARRATIVE_SCHEMA)
    check(SCHEMA)
    assert "never invent" in NARRATIVE_SYSTEM_PROMPT.lower()


# ---- the preset (FR-11.18, FR-10.23) ------------------------------------------------------------------


def test_preset_validation_drops_unknown_themes_and_bad_ranges() -> None:
    p, dropped = validate_preset({"themes": ["fork", "notATheme", "fork", "pin", "skewer", "mateIn2"],
                                  "rating_min": 1800, "rating_max": 1200})  # fmt: skip
    assert p is not None and p.themes == ("fork", "pin", "skewer")  # at most 3, known, no repeats
    assert (p.rating_min, p.rating_max) == (None, None)  # min above max: the range goes, the themes stay
    assert dropped == 3 + 2
    assert validate_preset({"themes": [], "rating_min": None, "rating_max": None}) == (None, 0)
    assert validate_preset({"themes": ["opening", "long"], "rating_min": None, "rating_max": None})[0] is None
    assert validate_preset(None) == (None, 0)
    p, dropped = validate_preset({"themes": ["fork"], "rating_min": "1200", "rating_max": 9000})
    assert p is not None and (p.rating_min, p.rating_max) == (None, None) and dropped == 2
    p, _ = validate_preset({"themes": ["fork"], "rating_min": 1000, "rating_max": None})
    assert p is not None and (p.rating_min, p.rating_max) == (1000, None)


def test_the_prompt_lists_only_preset_themes_that_validate() -> None:
    prompt = build_narrative_prompt(_narrative_input())
    allowed = prompt.rsplit("Allowed theme keys for the preset: ", 1)[1].split(", ")
    assert "fork" in allowed and "mateIn1" in allowed and "opening" not in allowed
    p, dropped = validate_preset({"themes": allowed[:3], "rating_min": None, "rating_max": None})
    assert p is not None and dropped == 0


def test_both_sides_review_counts_every_move_as_yours() -> None:
    prompt = build_narrative_prompt(_narrative_input("both"))
    assert "reviewing both sides" in prompt
    assert chess.Board().fen() not in prompt  # a standard start isn't repeated as a FEN
