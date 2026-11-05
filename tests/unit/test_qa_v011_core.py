"""QA v0.11 (independent): edge cases of the pure whole-game coaching code (REQUIREMENTS §10.11, FR-8.16).
Tests marked xfail document bugs from qa/QA-v0.11.md; they flip to XPASS once fixed."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.unit.test_digest import ITALIAN, digest, make_rows
from tests.unit.test_game_measures import dg, games, m
from weaksquare.core.coach_diagnosis import Sent, build_prompt, strip_urls, validate
from weaksquare.core.coach_llm import validate as validate_keyed
from weaksquare.core.game_measures import build_measures, game_weaknesses
from weaksquare.core.lessons import (
    CURATED,
    catalog,
    curated,
    is_allowed,
    search_url,
    topic,
    validate_custom_template,
)

EV = [{"game": "G1", "ply": 5}]


def _sent() -> Sent:
    return Sent(plies={"G1": {5, 9}, "G2": {5}, "G3": {7}}, keys={"time:low_clock"}, topics={"theme:fork"})


def _w(**kw: Any) -> dict[str, Any]:
    w: dict[str, Any] = {
        "key": None, "category": "tactical", "title": "T", "explanation": "E", "advice": "A", "topic": None,
        "evidence": EV,
    }  # fmt: skip
    w.update(kw)
    return w


def _answer(*ws: dict[str, Any], presets: list[dict[str, Any]] | None = None) -> str:
    return json.dumps({"summary": "S", "weaknesses": list(ws), "presets": presets or []})


# ---- evidence rule (FR-10.55) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "ev",
    [
        {"game": "G1", "ply": 5.0},  # a float is not a ply
        {"game": "G1", "ply": True},  # nor a bool
        {"game": "g1", "ply": 5},  # labels are exact
        {"game": " G1", "ply": 5},
        {"game": "G1", "ply": 0},
        {"game": "G1", "ply": -5},
        {"game": "G1", "ply": 6},  # not a ply that was sent for G1
        {"game": "G2", "ply": 9},  # a ply of another game
        {"game": "E1", "ply": 5},  # an example id is not a game label
        {"game": None, "ply": 5},
        "G1:5",
        [],
    ],
)
def test_qa_any_malformed_citation_is_dropped(ev: Any) -> None:
    d = validate(_answer(_w(evidence=[ev])), _sent(), None)
    assert d is not None and d.findings == ()


def test_qa_duplicate_citations_count_once_for_tentative() -> None:
    w = _w(evidence=[{"game": "G1", "ply": 5}] * 3 + [{"game": "G1", "ply": 9}])
    d = validate(_answer(w), _sent(), None)
    assert d is not None
    (f,) = d.findings
    assert len(f.evidence) == 2 and f.tentative  # one game cited, however often


def test_qa_evidence_is_not_a_dict_of_weaknesses() -> None:
    d = validate(json.dumps({"summary": "S", "weaknesses": {"a": 1}, "presets": "x"}), _sent(), None)
    assert d is not None and d.findings == () and d.presets == ()


def test_qa_a_key_that_was_not_sent_makes_an_observation() -> None:
    d = validate(_answer(_w(key="missed:fork")), _sent(), None)
    assert d is not None and d.findings[0].key is None


# ---- URLs from the LLM and in notes (FR-8.16, FR-10.59, FR-10.60) -----------------------------------

URL_FORMS = [
    "youtu.be/dQw4w9WgXcQ",
    "bit.ly/3abcXYZ",
    "chessable.co.uk/course/1",
    "example.de/seite",
    "ftp://files.example/x",
]


@pytest.mark.xfail(
    reason="QA v0.11 B2: strip_urls only knows .com/.org/.net/.io bare domains and http(s)/www", strict=True
)
@pytest.mark.parametrize("url", URL_FORMS)
def test_qa_strip_urls_removes_every_web_address(url: str) -> None:
    out = strip_urls(f"see {url} later")
    assert url not in out and "[link removed]" in out


def test_qa_strip_urls_keeps_chess_text() -> None:
    for text in ("1. e4 e5 2. Nf3", "Rxe5+ wins.", "23... Nf6 was best", "Kg1-h1. Then Qd8#."):
        assert strip_urls(text) == text


@pytest.mark.xfail(reason="QA v0.11 B1: an AI preset's name keeps a URL the LLM wrote", strict=True)
def test_qa_a_url_in_an_ai_preset_name_is_never_kept() -> None:
    preset = {
        "name": "Forks: see https://evil.example/x", "themes": ["fork"], "rating_min": 1200, "rating_max": 1500,
        "lengths": [], "mode": "standard", "queue_size": 20,
    }  # fmt: skip
    d = validate(_answer(_w(), presets=[preset]), _sent(), None)
    assert d is not None and d.presets
    assert "evil.example" not in d.presets[0].name


@pytest.mark.xfail(reason="QA v0.11 B1: the puzzle-history (keyed) coaching keeps URLs the LLM wrote", strict=True)
def test_qa_a_url_in_puzzle_history_coaching_is_never_kept() -> None:
    raw = json.dumps(
        {
            "summary": "Visit https://evil.example/x",
            "weaknesses": [{"key": "puzzles:fork", "explanation": "see www.evil.com", "drill": "go to evil.org/a"}],
            "presets": [],
        }
    )
    c = validate_keyed(raw, ["puzzles:fork"], None)
    assert c is not None
    blob = json.dumps(c.to_json())
    for bad in ("evil.example", "evil.com", "evil.org"):
        assert bad not in blob, bad


# ---- prompt: what goes in (FR-8.16, FR-10.54) --------------------------------------------------------


def test_qa_the_prompt_copies_only_allow_listed_report_fields() -> None:
    report = {
        "source": "games", "games": 1, "per10": {}, "results": {}, "reasons": {}, "low_clock_errors": 0,
        "subject_label": "player_a (Lichess)", "first_played": "2026-10-01", "game_ids": [4242],
        "missed": [{"key": "missed:fork", "label": "Missed: Fork", "examples": [{"game_id": 4242, "ply": 3}],
                    "per10": 1.0, "count": 1}],
        "measures": {"games": 1, "openings": [{"family": "Italian Game", "games": 1}]},
    }  # fmt: skip
    d = digest(make_rows(ITALIAN))
    user, _ = build_prompt(report, [("G1", d)], [], "summary", catalog(["Italian Game"]))
    for leak in ("player_a", "2026", "4242", "game_id", "subject_label", "examples"):
        assert leak not in user, leak


def test_qa_a_standard_prompt_never_lists_a_whole_game() -> None:
    long = [*ITALIAN, "c3", "d6", "Re1", "a6", "Bb3", "Ba7", "h3", "h6", "Nbd2", "Re8"]
    d = digest(make_rows(long))
    user, sent = build_prompt({"source": "games"}, [("G1", d)], [], "detailed", catalog())
    assert "Move lists" not in user
    assert len(sent.plies["G1"]) <= 5  # only the key moments are citable


# ---- measures: the 5-game guard (FR-10.53) -----------------------------------------------------------


def test_qa_conversion_with_four_games_makes_no_weakness_even_if_all_lost() -> None:
    ds = games(*[dg(held_plus2=True, result="loss", moments=(m(41),))] * 4, *[dg()] * 10)
    ms = build_measures(ds)
    assert not ms.conversion.enough
    assert "phase:conversion" not in {w.key for w in game_weaknesses(ds, ms)}


def test_qa_an_endgame_type_with_four_games_makes_no_weakness() -> None:
    eg = dg(endgame="rook", endgame_errors=3, moments=(m(61, phase="endgame"),), result="loss")
    ds = games(*[eg] * 4, *[dg()] * 10)
    ms = build_measures(ds)
    assert {e.type: e.enough for e in ms.endgames} == {"rook": False}
    assert not any(w.key.startswith("endgame:") for w in game_weaknesses(ds, ms))


def test_qa_low_clock_needs_five_clocked_games() -> None:
    from weaksquare.core.digest import TimeUse

    hot = dg(time=TimeUse(True, 3, 3, 3, 30, 0, 0), moments=(m(51, clock_pct=5),))
    ds = games(*[hot] * 4, *[dg()] * 10)
    ms = build_measures(ds)
    assert not ms.time.enough and "time:low_clock" not in {w.key for w in game_weaknesses(ds, ms)}
    ds5 = games(*[hot] * 5, *[dg()] * 10)
    assert "time:low_clock" in {w.key for w in game_weaknesses(ds5, build_measures(ds5))}


def test_qa_low_clock_is_no_weakness_when_you_err_as_often_otherwise() -> None:
    from weaksquare.core.digest import TimeUse

    even = dg(time=TimeUse(True, 10, 1, 1, 10, 1, 1), moments=(m(51, clock_pct=5),))
    ds = games(*[even] * 6)
    assert "time:low_clock" not in {w.key for w in game_weaknesses(ds, build_measures(ds))}


def test_qa_digest_for_black_held_and_castling() -> None:
    # Black is up +2 (White view -250) for a full move: held from Black's side, not White's.
    evals = [0, 0, 0, 0, 0, 0, -250, -250, -250, -250, -250]
    rows = make_rows(ITALIAN, evals)
    b = digest(rows, color="black", result="1/2-1/2")
    w = digest(rows, color="white", result="1/2-1/2")
    assert b.held_plus2 and not b.held_minus2 and b.castled_ply == 10
    assert w.held_minus2 and not w.held_plus2
    assert b.result == "draw"


# ---- lessons (FR-10.59) ------------------------------------------------------------------------------


def test_qa_every_curated_url_is_https_lichess_practice_or_learn() -> None:
    for tid, links in CURATED.items():
        assert links, tid
        for _, url in links:
            assert is_allowed(url), url
            assert url.startswith(("https://lichess.org/practice/", "https://lichess.org/learn")), url


@pytest.mark.parametrize(
    "tid", ["https://evil.example", "opening:https://evil.example", "theme:", "theme:notATheme", "", "concept:x"]
)
def test_qa_unknown_topics_are_refused(tid: str) -> None:
    assert topic(tid, ["Italian Game"]) is None
    assert curated(tid) == []


def test_qa_search_links_stay_on_the_site_whatever_the_topic() -> None:
    t = topic("opening:Evil&q=1#frag/../x?y", ["Evil&q=1#frag/../x?y"])
    assert t is not None
    for site, host in (("youtube", "www.youtube.com"), ("chesscom", "www.chess.com")):
        url = search_url(site, t)
        from urllib.parse import parse_qs, urlsplit

        parts = urlsplit(url)
        assert parts.hostname == host and parts.fragment == ""
        assert len(parse_qs(parts.query)) == 1


@pytest.mark.parametrize(
    "bad",
    ["javascript:alert(1)//{q}", "file:///C:/x?{q}", "https://{q}", "https:///path?q={q}", "data:text/html,{q}"],
)
def test_qa_a_custom_search_site_must_be_https_with_a_host(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_custom_template(bad)


@pytest.mark.xfail(reason="QA v0.11 B4: mistakes per phase have no sample-size guard (shown from 1 game)", strict=True)
def test_qa_errors_per_phase_are_guarded_below_five_games() -> None:
    j = build_measures(games(dg(errors_by_phase={"opening": 1, "middlegame": 0, "endgame": 0}))).to_json()
    flags = [v.get("enough") for k, v in j.items() if "phase" in k and isinstance(v, dict) and "enough" in v]
    flags += [v for k, v in j.items() if "phase" in k and k.endswith("enough")]
    assert flags and not any(flags)


@pytest.mark.xfail(reason="QA v0.11 B2: no word boundary after the TLD, so 'Qd1.Coming' loses a word", strict=True)
@pytest.mark.parametrize("text", ["I played Qd1.Coming back was better", "I lost on time.Commitment issue"])
def test_qa_strip_urls_leaves_words_after_a_missing_space(text: str) -> None:
    assert strip_urls(text) == text


@pytest.mark.xfail(reason="QA v0.11 B6: the whole-game prompt drops v0.10's puzzles-vs-games table", strict=True)
def test_qa_the_diagnosis_still_sends_the_puzzles_vs_games_table() -> None:
    report = {
        "source": "both",
        "gap": [{"theme": "fork", "puzzle_accuracy": 0.91, "puzzle_attempts": 40, "missed_per10": 3.0,
                 "allowed_per10": 1.0}],
    }  # fmt: skip
    user, _ = build_prompt(report, [("G1", digest(make_rows(ITALIAN)))], [], "summary", catalog())
    assert '"missed_per10":3.0' in user and '"puzzle_attempts":40' in user
