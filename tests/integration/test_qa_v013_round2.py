"""QA v0.13 round 2: pressing on the fixes at 1e6a0f9 and what they could have broken. Real database, fake provider and
engine, invented page text, no network. A test exposing an open bug is marked xfail with its ID."""

from __future__ import annotations

import threading
import time
from typing import Any

import chess
import pytest

from tests.integration.test_opening_notes import finish
from tests.integration.test_qa_v013_notes import FAMILY, api, configure, provider  # noqa: F401
from weaksquare.core.opening_explain import REF_CLOSE, REF_OPEN, _reference
from weaksquare.core.opening_sources import clean_page, page_title, page_url
from weaksquare.core.openings import STARTING_KEY, position_key, validate_scope
from weaksquare.core.repertoire import NewMove
from weaksquare.jobs.runner import CancelToken

E4, E5, NF3, NC6, BC4, D4, D5, C4 = "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "d2d4", "d7d5", "c2c4"


def store(a: Any, color: str, *lines: list[str]) -> None:
    for line in lines:
        board = chess.Board()
        moves = []
        for uci in line:
            move = chess.Move.from_uci(uci)
            moves.append(NewMove(position_key(board), uci, board.san(move), "you"))
            board.push(move)
        a._repertoire._repo.add_moves(color, moves, "2026-11-01T12:00:00+00:00")


def ok(r: dict[str, Any]) -> Any:
    assert r["ok"], r
    return r["data"]


def key_after(*moves: str) -> str:
    b = chess.Board()
    for m in moves:
        b.push(chess.Move.from_uci(m))
    return position_key(b)


# ---- B2: Export and Delete cover every line an opening shows ------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    [
        "Italian Game",
        "Caro-Kann Defense",
        "Catalan Opening",
        "East Indian Defense",
    ],
)
def test_every_move_an_opening_shows_is_covered_by_its_notes(api: Any, family: str) -> None:  # noqa: F811
    keys = set(api._opening_notes._note_keys(family))
    for preset in ("light", "standard", "deep"):
        for line in api._openings.lines(family, validate_scope(preset), False).lines:
            for m in line.moves:
                assert m.key_before in keys, (preset, line.name, m.san)


def test_every_move_past_the_book_is_covered_too(api: Any) -> None:  # noqa: F811
    scope = validate_scope("custom", 3, 20)
    book = api._openings.lines(FAMILY, scope, False).lines
    api._openings.extend_now(book, 20, CancelToken(), lambda *_: None)
    keys = set(api._opening_notes._note_keys(FAMILY))
    for line in api._openings.lines(FAMILY, scope, True).lines:
        for m in line.moves:
            assert m.key_before in keys, (line.name, m.san, m.source)


# ---- B8 and B9: the opening's row ----------------------------------------------------------------------------------------


def test_an_opening_you_have_practised_can_still_be_removed(api: Any) -> None:  # noqa: F811
    """`opening_attempts.opening_id` must not block deleting the row, and the attempts stay."""
    api._openings.set_scope("custom", 0, 4)
    api._openings.set_extend(False)
    api._repertoire.add_lines("white", FAMILY, [0])
    oid = api._repertoire.openings("white")[0].id
    s = ok(api.start_practice("white", "all", oid))
    ok(api.play_practice_move(s["session_id"], "a2a3"))
    rep = ok(api.remove_repertoire_move("white", STARTING_KEY, E4))
    assert rep["rows"] == [] and rep["openings"] == []
    assert len(api._opening_practice._attempts.for_color("white")) == 1
    assert ok(api.get_opening_stats("white")) == []


def test_removing_one_branch_keeps_an_opening_that_can_still_be_reached(api: Any) -> None:  # noqa: F811
    api._openings.set_scope("custom", 1, 4)
    api._openings.set_extend(False)
    api._repertoire.add_lines("white", FAMILY, [0, 1])
    rep = ok(api.get_repertoire("white"))
    leaf = rep["rows"][-1]
    rep = ok(api.remove_repertoire_move("white", leaf["position_key"], leaf["move_uci"]))
    assert [o["name"] for o in rep["openings"]] == [FAMILY]


def test_what_if_lists_the_opening_it_leads_to_and_it_can_be_practised_alone(api: Any) -> None:  # noqa: F811
    ok(api.add_opening_deviation("white", [E4], "a7a6", D4))
    rep = ok(api.get_repertoire("white"))
    assert [o["name"] for o in rep["openings"]] == ["St. George Defense"]
    s = ok(api.start_practice("white", "all", rep["openings"][0]["id"]))
    assert s["state"] == "your_move"
    assert ok(api.get_opening_stats("white"))[0]["name"] == "St. George Defense"


def test_what_if_inside_an_opening_stays_listed_under_it(api: Any) -> None:  # noqa: F811
    root = list(api._openings.root(FAMILY).moves)
    ok(api.add_opening_deviation("white", root, "h7h6", D4))
    assert [o["name"] for o in ok(api.get_repertoire("white"))["openings"]] == [FAMILY]


# ---- B11, B17, B26: sessions -----------------------------------------------------------------------------------------------


def test_a_limited_session_never_asks_past_its_limit_whatever_you_do(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5, NF3, NC6, BC4, "g8f6", D4])
    p = api._opening_practice
    s = p.start("white", mode="all", limit=2)
    s = p.play(s.session_id, "a2a3")  # a miss counts
    s = p.proceed(s.session_id)
    assert s.state == "your_move" and s.decisions == 1
    s = p.show_answer(s.session_id)
    s = p.proceed(s.session_id)
    assert s.state == "line_end" and s.decisions == 2
    assert p.proceed(s.session_id).state == "finished"


def test_a_line_cut_off_by_the_limit_isnt_counted_as_finished_clean(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5, NF3, NC6, BC4])
    p = api._opening_practice
    s = p.start("white", mode="all", limit=1)
    s = p.play(s.session_id, E4)
    assert s.state == "line_end"
    assert s.lines_clean == 0


def test_branches_list_each_side_of_a_split_and_limit_the_session(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5, NF3], [E4, "c7c5", "b1c3"], [D4, D5, C4])
    found = {b["label"]: b["position_key"] for b in ok(api.get_practice_branches("white", None))}
    assert set(found) == {"1. e4", "1. d4", "1. e4 e5", "1. e4 c5"}
    s = ok(api.start_practice("white", "all", None, found["1. d4"]))
    assert s["remaining"] == 1
    s = ok(api.play_practice_move(s["session_id"], D4))  # the walk there isn't a target, and isn't recorded
    assert s["position_key"] == key_after(D4, D5) and s["attempt_id"] is None
    s = ok(api.play_practice_move(s["session_id"], C4))
    assert s["attempt_id"] is not None and s["remaining"] == 0
    assert len(api._opening_practice._attempts.for_color("white")) == 1


def test_a_branch_with_nothing_of_yours_after_it_isnt_offered(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5], [E4, "c7c5"])  # both replies end the line: nothing to answer
    assert ok(api.get_practice_branches("white", None)) == []


def test_branches_within_one_opening_stay_in_it(api: Any) -> None:  # noqa: F811
    api._openings.set_scope("custom", 3, 6)
    api._openings.set_extend(False)
    api._repertoire.add_lines("white", FAMILY, [0, 1, 2, 3])
    store(api, "white", [D4, D5, C4])
    oid = api._repertoire.openings("white")[0].id
    keys = {b["position_key"] for b in ok(api.get_practice_branches("white", oid))}
    assert keys and key_after(D4) not in keys
    assert key_after(D4) in {b["position_key"] for b in ok(api.get_practice_branches("white", None))}


def test_branches_stay_quick_on_the_largest_repertoire_a_build_can_make(api: Any) -> None:  # noqa: F811
    p = api._repertoire.build_now(
        "white", FAMILY, {"max_moves": 20, "max_positions": 200, "max_replies": 6, "min_share": 0}
    )
    api._repertoire.save_proposal(p.id)
    started = time.perf_counter()
    found = ok(api.get_practice_branches("white", None))
    took = time.perf_counter() - started
    assert found and took < 3.0, f"{len(found)} branches in {took:.1f}s"


def test_a_session_for_one_opening_doesnt_take_another_openings_first_moves(api: Any) -> None:  # noqa: F811
    api._openings.set_scope("custom", 0, 4)
    api._openings.set_extend(False)
    api._repertoire.add_lines("white", FAMILY, [0])
    store(api, "white", [D4, D5, C4])
    oid = api._repertoire.openings("white")[0].id
    p = api._opening_practice
    s = p.start("white", opening_id=oid, mode="all", limit=100)
    assert s.remaining == len(
        [
            k
            for k in p._limit("white", p._repertoire.edges("white"), oid, None)
            if k in p._cards("white", p._repertoire.edges("white"))
        ]
    )
    assert key_after(D4, D5) not in p._limit("white", p._repertoire.edges("white"), oid, None)


# ---- B25: the interactive engine for a note you asked for ---------------------------------------------------------------


def test_two_notes_asked_together_both_keep_their_engine_figures(api: Any) -> None:  # noqa: F811
    from tests.fakes.engine import FakeEngine

    configure(api)
    api._openings.set_extend(False)
    api._openings.set_scope("custom", 0, 4)
    engine = api._engine
    # Stockfish is busy on the Learn board, as it is for a second or so after each step.
    busy = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with engine._engine_lock:
            busy.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    busy.wait(5)
    first = api._opening_notes.start_note(FAMILY, 0, 0)
    time.sleep(0.3)
    second = api._opening_notes.start_note(FAMILY, 0, 1)
    time.sleep(0.3)
    release.set()
    holder.join()
    finish(api, first)
    finish(api, second)
    assert FakeEngine.instances
    prompts = [r.user for r in provider(api).requests]
    assert len(prompts) == 2
    assert all("engine:" in p for p in prompts), prompts


def test_a_note_you_asked_for_and_a_prefetch_keep_to_their_own_engines(api: Any) -> None:  # noqa: F811
    configure(api)
    api._openings.set_extend(False)
    api._openings.set_scope("custom", 0, 4)
    finish(api, api._opening_notes.start_note(FAMILY, 0, 0))
    assert api._engine._engine is not None and api._engine._bg is None
    finish(api, api._opening_notes.start_prefetch(FAMILY, "light", None, None, False))
    assert api._engine._bg is not None


# ---- B4, B15, B20: Wikibooks text ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [1, 2, 5, 50])
def test_a_marker_nested_to_any_depth_cant_survive(depth: int) -> None:
    text = "planted"
    for _ in range(depth):
        text = REF_CLOSE[:5] + text.replace("planted", REF_CLOSE + "planted") + REF_CLOSE[5:]
    out = _reference(text + REF_OPEN[:4] + REF_OPEN + REF_OPEN[4:])
    assert out.count(REF_CLOSE) == 1 and out.count(REF_OPEN) == 1 and out.endswith(REF_CLOSE)


@pytest.mark.parametrize(
    "text",
    [
        "1.e4 e5 2.Nf3 Nc6 3.Bc4/3.Bb5 are both fine.",
        "After 5.O-O/5.Be2 White castles, i.e. quickly, e.g. on move 7.",
        "White's pawn on e4, etc. Then 8...Bg4/8...Be7, as in Fischer vs. Spassky, Reykjavik 1972.",
        "Black plays ...Nf6. White replies d4.",
        "a/b/c files, rook on the a1-h8 diagonal: Qd1-h5/Qd1-f3.",
        "The Ruy Lopez (Spanish) and King's Gambit (2.f4).",
    ],
)
def test_ordinary_chess_writing_is_left_alone(text: str) -> None:
    assert clean_page(text) == text


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x",
        "ftp://evil.example/x",
        "//evil.example/x",
        "evil.example/landing",
        "www.evil.example",
        "evil.com",
        "sub.evil.org/path?a=1",
        "EVIL.COM/X",
        "hxxp://evil.example/x",
    ],
)
def test_the_wider_link_filter_catches_these(url: str) -> None:
    assert "evil" not in clean_page(f"Before {url} after").lower()


def _clean_seconds(unit: str, size: int = 20_000) -> float:
    text = unit * (size // len(unit))
    started = time.perf_counter()
    clean_page(text)
    return time.perf_counter() - started


@pytest.mark.parametrize("unit", ["a.b/", "x.y.z ", "www.", "//", "aa "])
def test_most_long_pages_clean_at_once(unit: str) -> None:
    assert _clean_seconds(unit) < 3.0


@pytest.mark.parametrize("unit", ["a.", "a-"])
def test_a_long_hostile_run_cleans_in_good_time(unit: str) -> None:
    assert _clean_seconds(unit) < 3.0


def test_a_title_keeps_castling_and_promotion_and_drops_only_the_mark() -> None:
    assert page_title(["O-O+"]).endswith("/1. O-O")
    assert page_title(["O-O-O#"]).endswith("/1. O-O-O")
    assert page_title(["a8=Q+"]).endswith("/1. a8=Q")
    assert page_url(page_title(["a8=Q#"])).endswith("/1._a8%3DQ")
