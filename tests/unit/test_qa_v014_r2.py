"""QA v0.14 round 2 (independent): regressions around the B1 fix. The stored tree is now flat (`{"v": 2, "nodes": […]}`)
and every walk is a loop: damaged rows are refused, the move cap holds, order survives storage, and the bridge's
flattening, the repertoire walk and the re-check all work on trees far deeper than Python's recursion limit."""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import chess
import pytest

from weaksquare.bridge.api import _flatten_study_tree
from weaksquare.core.study_pgn import (
    MAX_NODES,
    Node,
    mainline,
    node_from_json,
    node_to_json,
    parse_study,
    stored_comment,
    walk,
)
from weaksquare.core.study_repertoire import study_moves


def _chapter(study: str, movetext: str, extra: str = "") -> str:
    return (
        f'[Event "S: C1"]\n[StudyName "S"]\n[ChapterName "C1"]\n'
        f'[ChapterURL "https://lichess.org/study/{study}/Chap0001"]\n{extra}\n{movetext} *\n'
    )


def _shuffle(plies: int, start: int = 1) -> str:
    cycle = ["Nf3", "Nf6", "Ng1", "Ng8"]
    out = []
    for i in range(plies):
        if i % 2 == 0:
            out.append(f"{start + i // 2}.")
        out.append(cycle[i % 4])
    return " ".join(out)


@contextmanager
def _shallow_stack(headroom: int = 120) -> Iterator[None]:
    """Only `headroom` frames above the caller: any recursion per move fails at once."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + headroom)
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


def _run_shallow(fn: Callable[[], Any]) -> Any:
    with _shallow_stack():
        return fn()


# ---- storage format ---------------------------------------------------------------------------------------------------
def test_qa14r2_order_comments_shapes_and_glyphs_survive_storage_through_json() -> None:
    pgn = _chapter(
        "TestRt01",
        "{ start [%csl Gd4] } 1. e4 $1 { a [%cal Re2e4] } 1... e5 (1... c5 { b } (1... e6 { c } 2. d4)) 2. Nf3 $6 Nc6",
    )
    root = parse_study("TestRt01", pgn).chapters[0].root
    stored = json.loads(json.dumps(node_to_json(root)))
    assert stored["v"] == 2 and "p" not in stored["nodes"][0]
    assert all(0 <= n["p"] < i for i, n in enumerate(stored["nodes"]) if i)  # parents always come first
    back = node_from_json(stored, chess.Board())
    assert node_to_json(back) == node_to_json(root)
    after_e4 = back.children[0]
    assert [c.san for c in after_e4.children] == ["e5", "c5", "e6"]  # main line first, side lines in order
    assert (root.comment, [(s.orig, s.color) for s in root.shapes]) == ("start", [("d4", "green")])
    assert after_e4.nags == [1] and after_e4.shapes[0].dest == "e4"


@pytest.mark.parametrize(
    "tree",
    [
        None,
        [],
        {"v": 1, "nodes": [{}]},
        {"children": []},  # the pre-fix nested format
        {"v": 2, "nodes": []},
        {"v": 2, "nodes": [{"p": 0}]},  # the root has a parent
        {"v": 2, "nodes": [{}, {"p": 1, "uci": "e2e4"}]},  # a node its own parent
        {"v": 2, "nodes": [{}, {"p": 2, "uci": "e2e4"}, {"p": 0, "uci": "d2d4"}]},  # parent comes later
        {"v": 2, "nodes": [{}, {"p": True, "uci": "e2e4"}]},  # bool isn't an index
        {"v": 2, "nodes": [{}, {"p": -1, "uci": "e2e4"}]},
        {"v": 2, "nodes": [{}, {"p": "0", "uci": "e2e4"}]},
        {"v": 2, "nodes": [{}, {"p": 0, "uci": "e2e5"}]},  # illegal
        {"v": 2, "nodes": [{}, {"p": 0, "uci": "zz"}]},
        {"v": 2, "nodes": [{}, "e2e4"]},
        {"v": 2, "nodes": [{}] + [{"p": 0, "uci": "e2e4"}] * (MAX_NODES + 1)},  # over the cap
    ],
)
def test_qa14r2_a_damaged_stored_tree_is_refused(tree: object) -> None:
    with pytest.raises(ValueError):
        node_from_json(tree, chess.Board())


def test_qa14r2_stored_text_survives_and_a_damaged_text_chapter_reads_as_empty() -> None:
    assert stored_comment(node_to_json(Node(comment="Just text."))) == "Just text."
    assert stored_comment({"children": []}) == "" and stored_comment(None) == ""


def test_qa14r2_the_move_cap_still_holds_at_5000() -> None:
    ok = parse_study("TestCp01", _chapter("TestCp01", _shuffle(MAX_NODES))).chapters[0]
    assert ok.rejected is None and ok.move_count == MAX_NODES
    back = node_from_json(node_to_json(ok.root), chess.Board())
    assert len(walk(back)) == MAX_NODES + 1
    over = parse_study("TestCp01", _chapter("TestCp01", _shuffle(MAX_NODES + 1))).chapters[0]
    assert over.rejected is not None and "too large" in over.rejected


# ---- nothing recurses per move ---------------------------------------------------------------------------------------
def test_qa14r2_parse_store_recheck_flatten_and_repertoire_never_recurse_per_move() -> None:
    # A 700-ply main line, and a 600-ply side line instead of 1. Nf3 (1. Nc3 and a knight shuffle).
    side_line = " ".join(m.replace("Nf3", "Nc3").replace("Ng1", "Nb1") for m in _shuffle(600).split())
    pgn = _chapter("TestDp01", "1. Nf3 (" + side_line + ") " + _shuffle(700)[len("1. Nf3 ") :])
    with _shallow_stack():
        st = parse_study("TestDp01", pgn)
    c = st.chapters[0]
    assert c.rejected is None, c.rejected
    assert len(mainline(c.root)) == 700
    stored = json.dumps(node_to_json(c.root))
    flat = _run_shallow(lambda: _flatten_study_tree(node_from_json(json.loads(stored), chess.Board()), c.start_fen))
    assert len(flat) == c.move_count + 1
    # ids are pre-order; children point forward to their own parent; positions follow the moves
    for m in flat:
        for k in m.children:
            assert flat[k].parent == m.id and k > m.id
            b = chess.Board(m.fen)
            b.push_uci(flat[k].uci or "")
            assert b.fen() == flat[k].fen
    last = flat[0]
    while last.children:
        last = flat[last.children[0]]
    assert last.ply == 700
    moves = _run_shallow(lambda: study_moves(c.root, c.start_fen, True))
    # Each shuffle repeats its positions: Nf3 Nf6 Ng1 Ng8 (4), then Nc3 Nf6 Nb1 (3; its Ng8 is the same position
    # and move as the main line's), so de-duplicated by position there are 7 (FR-13.11: positions matched by key).
    assert len(moves) == 7
    assert _run_shallow(lambda: study_moves(c.root, c.start_fen, False))


def test_qa14r2_a_text_chapter_flattens_to_its_board_and_text() -> None:
    flat = _flatten_study_tree(Node(comment="Pawn art."), "8/8/8/3pp3/3PP3/8/8/8 w - - 0 1")
    assert len(flat) == 1
    assert (flat[0].fen, flat[0].comment, flat[0].children, flat[0].san) == (
        "8/8/8/3pp3/3PP3/8/8/8 w - - 0 1",
        "Pawn art.",
        [],
        None,
    )
