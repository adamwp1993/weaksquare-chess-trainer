"""Regression tests for QA v0.13 round 2 (B2, B18 is in the e2e file, B29, B30, B31), past what QA's own tests cover."""

from __future__ import annotations

import threading
import time
from typing import Any

import chess
import pytest

from tests.integration.test_opening_notes import finish
from tests.integration.test_qa_v013_notes import FAMILY, api, configure  # noqa: F401
from tests.integration.test_qa_v013_round2 import store
from weaksquare.core.opening_sources import MAX_WORD_CHARS, clean_page
from weaksquare.core.openings import validate_scope

E4, E5, NF3, NC6, BC4 = "e2e4", "e7e5", "g1f3", "b8c6", "f1c4"


# ---- B31, and the heading pattern found beside it ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("=" * 300_000 + "x", id="run of equals"),
        pytest.param("= " * 150_000 + "x", id="spaced equals"),
        pytest.param("=a" * 150_000, id="equals and letters"),
        pytest.param("a." * 150_000, id="dots"),
        pytest.param("a-" * 150_000, id="hyphens"),
        pytest.param(("a." * (MAX_WORD_CHARS // 2) + " ") * 3_000, id="the longest words that are still checked"),
    ],
)
def test_a_large_hostile_page_cleans_in_good_time(text: str) -> None:
    started = time.perf_counter()
    clean_page(text)
    assert time.perf_counter() - started < 3.0


def test_a_run_too_long_to_be_a_word_is_dropped_and_its_neighbours_stay() -> None:
    assert clean_page(f"Before {'a.' * 100} after") == "Before  after"


def test_a_long_link_goes_with_the_rest_of_its_word() -> None:
    assert "evil" not in clean_page(f"See https://evil.example/{'x' * 500} for more")


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        ("== Plans ==", "Plans"),
        ("=== Plans for Black ===  ", "Plans for Black"),
        ("= A = B =", "A = B"),
        ("==References==", ""),
        ("= Plans", "= Plans"),
        ("Plans =", "Plans ="),
        ("====", "===="),
    ],
)
def test_headings_read_as_they_did(line: str, kept: str) -> None:
    assert clean_page(line) == kept


def test_a_dropped_section_keeps_going_until_a_heading_at_its_level() -> None:
    page = "== Plans ==\nKeep.\n== See also ==\nGone.\n=== Deeper ===\nGone too.\n== Theory ==\nKept."
    assert clean_page(page) == "Plans\nKeep.\nTheory\nKept."


# ---- B2: the notes Export and Delete cover ----------------------------------------------------------------------------


def test_delete_really_removes_a_note_on_a_line_through_another_family(api: Any) -> None:  # noqa: F811
    """QA's example: the Catalan shows Bd2 on the Bogo-Indian's line."""
    configure(api)
    catalan = "Catalan Opening"
    api._openings.set_extend(False)
    api._openings.set_scope("light")
    lines = api._openings.lines(catalan).lines
    own = set(api._openings.family_keys(catalan))
    index, ply = next(
        (i, p) for i, line in enumerate(lines) for p, m in enumerate(line.moves) if m.key_before not in own
    )
    move = lines[index].moves[ply]
    finish(api, api._opening_notes.start_note(catalan, index, ply))
    assert api._opening_notes.note(move.key_before, move.uci, "move") is not None
    api._opening_notes.delete(catalan)
    assert api._opening_notes.note(move.key_before, move.uci, "move") is None


def test_delete_doesnt_reach_every_line_that_passes_through_its_root(api: Any) -> None:  # noqa: F811
    """King's Pawn Game's root is 1. e4, so every 1. e4 line passes through it, and paid-for notes must survive."""
    keys = set(api._opening_notes._note_keys("King's Pawn Game"))
    after_caro = chess.Board()
    for san in ("e4", "c6", "d4", "d5", "e5", "Bf5"):
        after_caro.push_san(san)
    from weaksquare.core.openings import position_key

    assert position_key(after_caro) not in keys


def test_your_current_custom_scope_is_covered(api: Any) -> None:  # noqa: F811
    api._openings.set_scope("custom", 5, 9)
    keys = set(api._opening_notes._note_keys("Queen's Gambit"))
    for line in api._openings.lines("Queen's Gambit", validate_scope("custom", 5, 9), False).lines:
        assert all(m.key_before in keys for m in line.moves)


# ---- B29: a line the limit stopped -------------------------------------------------------------------------------------


def test_a_line_the_limit_stopped_says_so_and_a_finished_one_doesnt(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5, NF3, NC6, BC4])
    p = api._opening_practice
    s = p.start("white", mode="all", limit=1)
    s = p.play(s.session_id, E4)
    assert s.state == "line_end" and s.line_cut and s.lines_clean == 0 and s.lines_lost == 0
    assert p.proceed(s.session_id).state == "finished"

    s = p.start("white", mode="all", limit=100)
    assert not s.line_cut
    while s.state == "your_move":
        s = p.play(s.session_id, _answer(api, s))
    assert s.state == "line_end" and not s.line_cut and s.lines_clean == 1


def _answer(api: Any, s: Any) -> str:  # noqa: F811
    from weaksquare.core.repertoire import by_position

    return by_position(api._repertoire.edges("white"))[s.position_key][0].move_uci


def test_a_missed_line_the_limit_stopped_still_counts_as_lost(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5, NF3, NC6, BC4])
    p = api._opening_practice
    s = p.start("white", mode="all", limit=1)
    s = p.play(s.session_id, "a2a3")
    s = p.proceed(s.session_id)
    assert s.state == "line_end" and s.line_cut and s.lines_lost == 1 and s.lines_clean == 0


def test_the_bridge_says_when_the_limit_stopped_a_line(api: Any) -> None:  # noqa: F811
    store(api, "white", [E4, E5, NF3, NC6, BC4])
    s = api._opening_practice.start("white", mode="all", limit=1)
    s = api.play_practice_move(s.session_id, E4)
    assert s["ok"] and s["data"]["line_cut"] is True


# ---- B30: answers you're waiting on never replace each other -----------------------------------------------------------


def test_two_notes_on_one_position_both_keep_their_figures(api: Any) -> None:  # noqa: F811
    configure(api)
    api._openings.set_extend(False)
    api._openings.set_scope("custom", 0, 4)
    engine = api._engine
    busy, release = threading.Event(), threading.Event()

    def hold() -> None:
        with engine._engine_lock:
            busy.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    busy.wait(5)
    results: list[Any] = []
    key = api._openings.lines(FAMILY).lines[0].moves[0].key_before
    workers = [threading.Thread(target=lambda: results.append(api._openings.interactive_lines(key))) for _ in range(2)]
    for w in workers:
        w.start()
    time.sleep(0.2)
    release.set()
    holder.join()
    for w in workers:
        w.join()
    assert len(results) == 2 and all(results)


def test_the_learn_board_still_drops_an_older_position_for_a_newer_one(api: Any) -> None:  # noqa: F811
    """Only the position you're looking at matters there, so B30's fix leaves it superseding."""
    engine = api._engine
    busy, release = threading.Event(), threading.Event()

    def hold() -> None:
        with engine._engine_lock:
            busy.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    busy.wait(5)
    answers: dict[str, Any] = {}
    first_board = chess.Board()
    first_board.push_uci(E4)
    second_board = chess.Board()
    second_board.push_uci("d2d4")

    def ask(name: str, board: chess.Board) -> None:
        answers[name] = api._openings.analyze(board.fen(), "board", "white")

    first = threading.Thread(target=ask, args=("first", first_board))
    first.start()
    time.sleep(0.2)
    second = threading.Thread(target=ask, args=("second", second_board))
    second.start()
    time.sleep(0.2)
    release.set()
    holder.join()
    first.join()
    second.join()
    assert answers["first"].superseded and not answers["second"].superseded


def test_a_note_keeps_its_figures_when_asked_during_a_board_analysis(api: Any) -> None:  # noqa: F811
    configure(api)
    api._openings.set_extend(False)
    api._openings.set_scope("custom", 0, 4)
    board = chess.Board()
    board.push_uci("h2h3")
    api._openings.analyze(board.fen(), "board", "white")
    finish(api, api._opening_notes.start_note(FAMILY, 0, 0))
    from tests.integration.test_qa_v013_notes import provider

    assert "engine:" in provider(api).requests[-1].user
