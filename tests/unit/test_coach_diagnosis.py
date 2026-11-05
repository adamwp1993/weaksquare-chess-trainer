"""The whole-game AI diagnosis (v0.11, FR-10.54–10.56, 10.60, FR-8.16): what each kind of run sends, and
the evidence rule."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.unit.test_digest import ITALIAN, make_rows
from weaksquare.core.coach_diagnosis import (
    NoteItem,
    Sent,
    build_prompt,
    strip_urls,
    title_key,
    validate,
)
from weaksquare.core.coach_llm import ExamplePosition
from weaksquare.core.digest import Digest, build_digest
from weaksquare.core.game_explain import san_moves
from weaksquare.core.lessons import catalog

LEAKS = ("player_a", "opponent_b", "lichess.org", "chess.com", "2026", "[%clk", "game_id", "Site", "[Event", "[%")


def _digest() -> Digest:
    evals = [0, 0, 0, 0, 0, -300, -300, -300, -300, -300, -300]
    rows = make_rows(ITALIAN, evals, clocks=[600, 600, 590, 580, 30, 570, 20, 560, 10, 550], base=600)
    return build_digest(rows=rows, color="white", result="0-1", eco="C50", opening="Italian Game", base_seconds=600)


REPORT: dict[str, Any] = {
    "source": "games",
    "games": 2,
    "per10": {"blunders": 5.0},
    "results": {"loss": 2},
    "reasons": {},
    "low_clock_errors": 1,
    "missed": [{"key": "missed:fork", "label": "Missed: Fork", "count": 2, "per10": 10.0, "game_id": 99}],
    "whole_game": [{"key": "time:low_clock", "label": "Mistakes under 10% of your clock", "count": 2}],
    "measures": {"games": 2, "openings": [{"family": "Italian Game", "games": 2, "enough": False}]},
    "examples": [{"game_id": 4242, "ply": 4}],
    "first_played": "2026-10-01T10:00:00Z",
}
GAMES = [("G1", _digest()), ("G2", _digest())]
EXAMPLE = (
    ExamplePosition("E1", "missed:fork", make_rows(ITALIAN)[4].fen_before, "f1c4", ("f1c4",), ("fork",), 300),
    "G1",
    5,
)
TOPICS = catalog(["Italian Game"])
MOVES = {"G1": san_moves(make_rows(ITALIAN)[0].fen_before, [r.move_uci for r in make_rows(ITALIAN)])}


def _prompt(**kw: Any) -> tuple[str, Sent]:
    return build_prompt(REPORT, GAMES, [EXAMPLE], "summary", TOPICS, **kw)


def test_a_standard_prompt_has_no_move_lists() -> None:
    text, sent = _prompt()
    assert "Move lists" not in text and "1. e4 e5 2. Nf3" not in text
    for leak in LEAKS:
        assert leak not in text, leak
    assert '"game":"G1"' in text and '"move":"3. Bc4"' in text and '"ply":5' in text
    assert "4242" not in text and "99" not in text.replace("0.99", "")  # report game ids never copied
    assert "clock_left_pct" in text and "600" not in text  # time as a percentage, never the raw clock
    assert sent.plies == {"G1": {5}, "G2": {5}}
    assert sent.keys == {"missed:fork", "time:low_clock"}
    assert "concept:timeManagement" in sent.topics and "opening:Italian Game" in sent.topics


def test_an_advanced_prompt_adds_san_only() -> None:
    text, sent = _prompt(moves=MOVES)
    assert "Move lists (Advanced analysis; SAN only):" in text
    assert "G1: 1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6 5. d3 O-O" in text
    for leak in LEAKS:
        assert leak not in text, leak
    assert sent.plies["G1"] == set(range(1, 11)) and sent.plies["G2"] == {5}


def test_notes_appear_only_when_included_and_without_urls() -> None:
    plain, _ = _prompt()
    assert "notes" not in plain.lower().split("lesson topic ids")[0]
    note = NoteItem(strip_urls("saw it on https://example.org/x and www.foo.com, missed it"), "didntLook", "G1", 5)
    puzzle = NoteItem("forgot the back rank", None, source="puzzle")
    text, _ = _prompt(notes=[note, puzzle])
    assert "Your own notes" in text
    assert '"note":"saw it on [link removed] and [link removed] missed it"' in text
    assert "example.org" not in text and "foo.com" not in text
    assert '"note":"forgot the back rank","source":"puzzle"' in text


def _answer(*weaknesses: dict[str, Any], presets: list[Any] | None = None) -> str:
    return json.dumps({"summary": "You lose on the clock.", "weaknesses": list(weaknesses), "presets": presets or []})


def _w(evidence: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    w = {
        "key": None, "category": "time", "title": "Time trouble", "explanation": "You blunder late.",
        "advice": "Keep 10 minutes.", "topic": "concept:timeManagement", "evidence": evidence,
    }  # fmt: skip
    w.update(kw)
    return w


def _sent() -> Sent:
    return Sent(plies={"G1": {5, 9}, "G2": {5}, "G3": {7}}, keys={"time:low_clock"}, topics={"concept:timeManagement"})


def test_an_invented_game_label_or_ply_is_dropped() -> None:
    ev: list[dict[str, Any]] = [
        {"game": "G1", "ply": 5}, {"game": "G9", "ply": 5}, {"game": "G2", "ply": 6}, {"game": "G1", "ply": "5"},
    ]  # fmt: skip
    d = validate(_answer(_w(ev)), _sent(), None)
    assert d is not None
    (f,) = d.findings
    assert [(e.game, e.ply) for e in f.evidence] == [("G1", 5)]
    assert d.discarded == 3


def test_a_weakness_with_no_valid_evidence_is_dropped() -> None:
    d = validate(_answer(_w([{"game": "G7", "ply": 1}]), _w([])), _sent(), None)
    assert d is not None and d.findings == ()


def test_fewer_than_three_games_is_tentative() -> None:
    two = _w([{"game": "G1", "ply": 5}, {"game": "G1", "ply": 9}, {"game": "G2", "ply": 5}])
    three = _w([{"game": "G1", "ply": 5}, {"game": "G2", "ply": 5}, {"game": "G3", "ply": 7}], title="Three")
    d = validate(_answer(two, three), _sent(), None)
    assert d is not None
    assert [f.tentative for f in d.findings] == [True, False]


def test_keys_topics_and_categories_are_checked() -> None:
    ev = [{"game": "G1", "ply": 5}]
    d = validate(
        _answer(
            _w(ev, key="time:low_clock"),
            _w(ev, key="time:low_clock", title="Again"),  # a second one on the same key: an observation
            _w(ev, key="made:up", topic="https://evil.example/x", category="wizardry", title="Odd"),
        ),
        _sent(),
        None,
    )
    assert d is not None
    assert [(f.key, f.topic, f.category) for f in d.findings] == [
        ("time:low_clock", "concept:timeManagement", "time"),
        (None, "concept:timeManagement", "time"),
        (None, None, "other"),
    ]


def test_a_url_written_by_the_llm_is_never_kept() -> None:
    ev = [{"game": "G1", "ply": 5}]
    w = _w(ev, explanation="See https://evil.example/phish now", advice="Go to www.bad.com or bad.org/page")
    raw = json.dumps({"summary": "Visit http://x.io/y", "weaknesses": [w], "presets": []})
    d = validate(raw, _sent(), None)
    assert d is not None
    blob = json.dumps(d.to_json())
    for bad in ("evil.example", "bad.com", "bad.org", "x.io", "http"):
        assert bad not in blob, bad
    assert "[link removed]" in d.findings[0].explanation


def test_at_most_eight_weaknesses() -> None:
    ev = [{"game": "G1", "ply": 5}]
    d = validate(_answer(*[_w(ev, title=f"W{i}") for i in range(10)]), _sent(), None)
    assert d is not None and len(d.findings) == 8 and d.discarded == 2


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"weaknesses": []})])
def test_a_broken_answer_is_none(text: str) -> None:
    assert validate(text, _sent(), None) is None


def test_the_fallback_preset_and_round_trip() -> None:
    fallback = {"name": "Mix", "themes": ["fork"], "rating_min": 1400, "rating_max": 1700, "lengths": [],
                "mode": "standard", "queue_size": 20}  # fmt: skip
    d = validate(_answer(_w([{"game": "G1", "ply": 5}])), _sent(), fallback)
    assert d is not None and d.fallback_preset and d.presets[0].themes == ("fork",)
    from weaksquare.core.coach_diagnosis import Diagnosis

    assert Diagnosis.from_json(d.to_json()) == d


def test_title_key_normalizes() -> None:
    assert title_key("  You attack BEFORE castling! ") == title_key("you attack before castling")
