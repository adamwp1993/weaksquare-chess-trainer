"""Explain's context and validation (FR-8.2–8.4; ROADMAP v0.7 *Done when*: "annotation-validation tests
drop illegal moves and squares"). Pure: no LLM, no engine."""

from __future__ import annotations

import json
from typing import Any

import pytest

from weaksquare.core.explain import (
    MAX_ANNOTATIONS,
    SCHEMA,
    SYSTEM_PROMPT,
    DangerFact,
    EngineLineFact,
    ExplainInput,
    Explanation,
    RefutationFact,
    build_prompt,
    validate,
)

# Fixture puzzle 0OT49: Black plays f5, then you (White) play exf6 e.p., Black Bxf6, you Bxf8.
FEN = "2r2rk1/5pbp/1q2p1p1/4P3/pB1pQP2/Pp1P4/1P4PP/2R2R1K b - - 1 25"
MOVES = ("f7f5", "e5f6", "g7f6", "b4f8")
INP = ExplainInput(FEN, MOVES, ("Crushing", "En passant"))


def answer(**over: Any) -> str:
    body: dict[str, Any] = {
        "summary": "En passant opens the long diagonal and wins the exchange.",
        "steps": [
            {"ply": 0, "move": "exf6", "text": "Take en passant.", "variation": [],
             "annotations": [{"type": "arrow", "from": "e5", "to": "f6", "color": "green"}]},
            {"ply": 1, "move": "Bxf6", "text": "Black recaptures.", "variation": [], "annotations": []},
            {"ply": 2, "move": "Bxf8", "text": "The rook on f8 falls.", "variation": ["Rxf8"],
             "annotations": [{"type": "circle", "from": "f8", "to": None, "color": "red"}]},
        ],
        "key_ideas": ["en passant", "discovered attack"],
    }  # fmt: skip
    body.update(over)
    return json.dumps(body)


def steps_with(**step: Any) -> str:
    base = {"ply": 0, "move": "exf6", "text": "t", "annotations": [], "variation": []}
    return answer(steps=[base | step])


# ---- validation ------------------------------------------------------------------------------------


def test_a_good_answer_is_kept_whole() -> None:
    e = validate(INP, answer())
    assert e is not None and e.discarded == 0
    assert [(s.ply, s.side, s.san, s.uci) for s in e.steps] == [
        (0, "you", "exf6", "e5f6"), (1, "opponent", "Bxf6", "g7f6"), (2, "you", "Bxf8", "b4f8"),
    ]  # fmt: skip
    assert e.steps[0].annotations[0].kind == "arrow" and e.steps[2].annotations[0].dest is None
    assert e.steps[2].variation == ("Rxf8",)
    assert e.key_ideas == ("en passant", "discovered attack")


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "arrow", "from": "e5", "to": "i9", "color": "green"},  # off the board
        {"type": "arrow", "from": "z1", "to": "f6", "color": "green"},
        {"type": "arrow", "from": "e5", "to": "e5", "color": "green"},  # goes nowhere
        {"type": "arrow", "from": "e5", "to": None, "color": "green"},
        {"type": "circle", "from": "e5", "to": "f6", "color": "green"},
        {"type": "arrow", "from": "e5", "to": "f6", "color": "purple"},  # unknown color
        {"type": "square", "from": "e5", "to": None, "color": "green"},
        {"type": "arrow", "from": "E5", "to": "F6", "color": "green"},
        "e5f6",
    ],
)
def test_invalid_annotations_are_dropped_and_counted(bad: Any) -> None:
    good = {"type": "circle", "from": "f6", "to": None, "color": "blue"}
    e = validate(INP, steps_with(annotations=[bad, good]))
    assert e is not None and e.discarded == 1
    assert [a.orig for a in e.steps[0].annotations] == ["f6"]


def test_too_many_annotations_are_capped() -> None:
    many = [{"type": "circle", "from": f"a{i}", "to": None, "color": "blue"} for i in range(1, 9)]
    e = validate(INP, steps_with(annotations=many))
    assert e is not None and len(e.steps[0].annotations) == MAX_ANNOTATIONS and e.discarded == 8 - MAX_ANNOTATIONS


def test_a_step_naming_the_wrong_move_is_dropped() -> None:
    e = validate(INP, steps_with(move="Qe4xg6"))  # not the solution's move at ply 0
    assert e is not None and e.steps == () and e.discarded == 1


def test_the_move_may_be_given_as_uci_or_san() -> None:
    e = validate(INP, steps_with(move="e5f6"))
    assert e is not None and e.steps[0].san == "exf6"


@pytest.mark.parametrize("ply", [-1, 3, 99, "0", True, None])
def test_plies_the_solution_doesnt_have_are_dropped(ply: Any) -> None:
    e = validate(INP, steps_with(ply=ply))
    assert e is not None and e.steps == () and e.discarded == 1


def test_a_repeated_ply_keeps_the_first() -> None:
    first = {"ply": 0, "move": "exf6", "text": "first", "annotations": [], "variation": []}
    e = validate(INP, answer(steps=[first, first | {"text": "second"}]))
    assert e is not None and [s.text for s in e.steps] == ["first"] and e.discarded == 1


@pytest.mark.parametrize(
    "variation",
    [
        ["Ke7"],  # after Bxf8 it's Black to move, and the king on g8 can't reach e7
        ["Bxf8"],  # no black bishop reaches f8
        ["Rxf8", "Rxf8", "Rxf8"],  # Black has no second rook for the third capture
        ["xx"],
        [1],
        ["Rxf8"] * 9,  # longer than the cap
    ],
)
def test_illegal_variations_are_dropped_whole(variation: list[Any]) -> None:
    step = {"ply": 2, "move": "Bxf8", "text": "t", "annotations": [], "variation": variation}
    e = validate(INP, answer(steps=[step]))
    assert e is not None and e.steps[0].variation == () and e.discarded == 1


def test_a_legal_variation_is_kept_in_san() -> None:
    step = {"ply": 2, "move": "Bxf8", "text": "t", "annotations": [], "variation": [" Rxf8 ", "Qxg6+"]}
    e = validate(INP, answer(steps=[step]))
    assert e is not None and e.steps[0].variation == ("Rxf8", "Qxg6+") and e.discarded == 0
    step["variation"] = ["c8f8"]  # UCI is understood too, and shown as SAN
    e = validate(INP, answer(steps=[step]))
    assert e is not None and e.steps[0].variation == ("Rxf8",)


def test_text_is_capped_and_cleaned() -> None:
    e = validate(INP, answer(summary="a\x00b" + "x" * 5000, key_ideas=["  fork ", "", 7, "y" * 200] + ["z"] * 9))
    assert e is not None
    assert e.summary.startswith("ab") and len(e.summary) == 1200
    assert e.key_ideas[0] == "fork" and len(e.key_ideas[1]) == 60 and len(e.key_ideas) == 6


def test_html_is_kept_as_text_for_the_ui_to_escape() -> None:
    """FR-8.7: validation doesn't render; the UI shows the text escaped (React text nodes)."""
    e = validate(INP, answer(summary="<img src=x onerror=alert(1)> wins"))
    assert e is not None and e.summary == "<img src=x onerror=alert(1)> wins"


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"steps": []}', '{"summary": 5}', "null"])
def test_answers_that_arent_the_schema_are_rejected(text: str) -> None:
    assert validate(INP, text) is None


def test_steps_and_ideas_of_the_wrong_type_are_tolerated() -> None:
    e = validate(INP, answer(steps="nope", key_ideas={"a": 1}))
    assert e is not None and e.steps == () and e.key_ideas == ()


def test_round_trips_through_the_cache_format() -> None:
    e = validate(INP, answer())
    assert e is not None and Explanation.from_json(e.to_json()) == e


# ---- the context (SR-11 allowlist) --------------------------------------------------------------------


def test_prompt_has_the_facts() -> None:
    inp = ExplainInput(
        FEN, MOVES, ("Crushing",),
        engine_lines=(EngineLineFact("+4.1 for you", ("e5f6", "g7f6", "b4f8")),),
        refutation=RefutationFact("2r2rk1/5pbp/1q2p1p1/4Pp2/pB1pQP2/Pp1P4/1P4PP/2R2R1K w - f6 0 26", "e4e1",
                                  ("b6b4",), "-1.2 for you"),
    )  # fmt: skip
    p = build_prompt(inp)
    assert "You play White" in p and "The opponent has just played f5." in p
    assert "0: you exf6 [e5f6]" in p and "2: you Bxf8 [b4f8]" in p
    assert "captures a pawn en passant" in p and "captures the rook" in p
    assert "Themes: Crushing" in p
    assert "Stockfish's top lines" in p and "+4.1 for you: exf6 Bxf6 Bxf8" in p
    assert "went wrong with Qe1" in p and "refutation: Qxb4" in p


def test_prompt_never_names_the_puzzle_or_its_rating() -> None:
    p = build_prompt(INP)
    assert "0OT49" not in p and "lichess" not in p.lower() and "rating" not in p.lower()


def test_danger_spotting_context() -> None:
    safe = build_prompt(ExplainInput(FEN, MOVES, (), danger=DangerFact("g8h8", True, "unsafe")))
    assert "Danger spotting" in safe and "Kh8 highlighted" in safe and "a safe move" in safe
    assert "The player's call: unsafe" in safe
    blunder = build_prompt(ExplainInput(FEN, MOVES, (), danger=DangerFact("f7f5", False, "safe")))
    assert "f5 was the real blunder" in blunder


def test_commit_the_line_context() -> None:
    p = build_prompt(ExplainInput(FEN, MOVES, (), entered_line=("e5f6", "g7f6", "e4g6")))
    assert "The player entered: exf6 Bxf6 Qxg6" in p


def test_schema_is_strict_mode_shaped() -> None:
    """OpenAI's strict mode needs every property required and no extra properties, at every level."""

    def walk(node: Any) -> None:
        if isinstance(node, dict) and node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        if isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(SCHEMA)
    assert "never invent" in SYSTEM_PROMPT.lower()
