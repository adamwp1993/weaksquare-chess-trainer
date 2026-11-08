"""FR-13.7, 13.8 (v0.14): parsing and checking a study's PGN. Invented studies only (SR-12a): no real study text."""

from __future__ import annotations

import json

import chess
import pytest

from weaksquare.core import study_pgn as sp
from weaksquare.core.study_pgn import (
    Node,
    Shape,
    clean_text,
    mainline,
    node_from_json,
    node_to_json,
    parse_shapes,
    parse_study,
)

SID = "AbCd1234"


def chapter(
    name: str,
    moves: str,
    *,
    cid: str = "Ch000001",
    mode: str | None = None,
    orientation: str = "white",
    fen: str | None = None,
    variant: str = "Standard",
    annotator: str = "https://lichess.org/@/test_author",
) -> str:
    h = [
        f'[Event "Test study: {name}"]',
        '[StudyName "Test study"]',
        f'[ChapterName "{name}"]',
        f'[ChapterURL "https://lichess.org/study/{SID}/{cid}"]',
        f'[Annotator "{annotator}"]',
        f'[Variant "{variant}"]',
        f'[Orientation "{orientation}"]',
    ]
    if mode:
        h.append(f'[ChapterMode "{mode}"]')
    if fen:
        h += [f'[FEN "{fen}"]', '[SetUp "1"]']
    return "\n".join(h) + "\n\n" + moves + "\n\n"


NORMAL = chapter(
    "Main idea",
    "{ Intro [%csl Ge4] } 1. e4 { Grab the centre [%cal Gd2d4,Rz9z1] } 1... e5 $1 "
    "(1... c5 { A side line } 2. Nf3) 2. Nc3 *",
    cid="Ch000001",
)
GAMEBOOK = chapter("Your turn", "1. e4 c6 2. d4 d5 *", cid="Ch000002", mode="gamebook", orientation="black")


def test_a_normal_chapter_keeps_its_tree_comments_shapes_and_side_lines() -> None:
    st = parse_study(SID, NORMAL + GAMEBOOK)
    assert (st.title, st.author, len(st.chapters)) == ("Test study", "test_author", 2)
    c = st.chapters[0]
    assert (c.chapter_id, c.title, c.mode, c.orientation, c.rejected, c.text_only) == (
        "Ch000001", "Main idea", "normal", "white", None, False,
    )  # fmt: skip
    assert c.root.comment == "Intro"
    assert c.root.shapes == [Shape("e4", None, "green")]
    e4 = c.root.children[0]
    assert (e4.san, e4.uci, e4.comment) == ("e4", "e2e4", "Grab the centre")
    assert e4.shapes == [Shape("d2", "d4", "green")]  # the invalid Rz9z1 is dropped, the valid arrow kept
    assert [n.san for n in e4.children] == ["e5", "c5"]
    assert e4.children[0].nags == [1]
    assert e4.children[1].comment == "A side line"
    assert [n.san for n in mainline(c.root)] == ["e4", "e5", "Nc3"]
    assert c.move_count == 5


def test_a_gamebook_chapter_keeps_its_mode_and_orientation() -> None:
    c = parse_study(SID, GAMEBOOK).chapters[0]
    assert (c.mode, c.orientation, c.chapter_id) == ("gamebook", "black", "Ch000002")


def test_an_illegal_chapter_is_rejected_and_the_rest_kept() -> None:
    bad = chapter("Broken", "1. e4 e5 2. Ke3 Nf6 3. Qh5 *", cid="Ch000003")
    st = parse_study(SID, NORMAL + bad + GAMEBOOK)
    assert [c.rejected is None for c in st.chapters] == [True, False, True]
    broken = st.chapters[1]
    assert broken.rejected is not None and "illegal" in broken.rejected
    assert broken.root.children == []
    assert [c.title for c in st.usable] == ["Main idea", "Your turn"]


def test_another_variant_is_rejected() -> None:
    c = parse_study(SID, chapter("House", "1. e4 *", variant="Crazyhouse")).chapters[0]
    assert c.rejected is not None and "standard chess" in c.rejected


def test_a_decorative_board_with_no_moves_is_a_text_chapter() -> None:
    """Adam, v0.14 planning: kept as text, not rejected."""
    st = parse_study(
        SID,
        chapter("Welcome", "{ Hello and welcome! }", fen="8/8/8/8/8/8/8/8 w - - 0 1")
        + chapter("Pawn art", "{ Art }", fen="8/1P3P2/PpP1PpP1/8/8/8/8/8 w - - 0 1", cid="Ch000002"),
    )
    assert [(c.text_only, c.rejected) for c in st.chapters] == [(True, None), (True, None)]
    assert st.chapters[0].root.comment == "Hello and welcome!"
    assert st.chapters[0].root.children == []
    assert st.chapters[1].start_fen.startswith("8/1P3P2/")


def test_moves_from_an_impossible_position_are_rejected() -> None:
    c = parse_study(SID, chapter("Bad", "1. a3 *", fen="8/8/8/8/8/8/P7/8 w - - 0 1")).chapters[0]
    assert c.rejected == "starts from an impossible position"


def test_a_custom_start_position() -> None:
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 0 1"
    c = parse_study(SID, chapter("From here", "1. f4 exf4 *", fen=fen)).chapters[0]
    assert c.start_fen == fen and [n.san for n in mainline(c.root)] == ["f4", "exf4"]


def test_text_is_cleaned_but_never_interpreted() -> None:
    raw = "Look ‮evil‬ here https://example.com/x <b>bold</b> [%clk 0:01:00] [%eval 0.3]\x07 done"
    assert clean_text(raw) == "Look evil here https://example.com/x <b>bold</b> done"
    assert clean_text("a" * 5000).endswith("…") and len(clean_text("a" * 5000)) == sp.MAX_COMMENT + 1
    assert clean_text("one\r\n\r\n\r\n\r\ntwo") == "one\n\ntwo"
    assert clean_text(None) == ""


def test_a_url_in_a_title_stays_text() -> None:
    c = parse_study(SID, chapter("Blitz https://lichess.org/tournament/abc", "1. e4 *")).chapters[0]
    assert c.title == "Blitz https://lichess.org/tournament/abc"


@pytest.mark.parametrize(
    ("comment", "shapes"),
    [
        ("[%csl Gd4,Rz9,Ye5]", [Shape("d4", None, "green"), Shape("e5", None, "yellow")]),
        ("[%cal Ge2e4,Xe2e4,Bg1f3,Ga1a9]", [Shape("e2", "e4", "green"), Shape("g1", "f3", "blue")]),
        ("[%cal Ge2e2]", [Shape("e2", None, "green")]),
        ("[%csl Gd4][%csl Rd4]", [Shape("d4", None, "green")]),
        ("[%csl Gd4 , Re5]", [Shape("d4", None, "green"), Shape("e5", None, "red")]),
        ("[%clk 0:01:00]", []),
        (None, []),
    ],
)
def test_shapes_drop_only_the_invalid_item(comment: object, shapes: list[Shape]) -> None:
    assert parse_shapes(comment) == shapes


def test_author_comes_only_from_a_lichess_profile_link() -> None:
    assert parse_study(SID, chapter("x", "1. e4 *", annotator="https://evil.com/@/x")).author is None
    assert parse_study(SID, chapter("x", "1. e4 *", annotator="someone")).author is None


def test_a_huge_chapter_is_rejected_and_the_next_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "MAX_NODES", 4)  # Big has 5 moves, the gamebook 4
    big = chapter("Big", "1. e4 e5 2. Nf3 Nc6 3. Bb5 *", cid="Ch000009")
    st = parse_study(SID, big + GAMEBOOK)
    assert st.chapters[0].rejected is not None and "too large" in st.chapters[0].rejected
    assert st.chapters[1].title == "Your turn" and st.chapters[1].rejected is None


def test_empty_or_bad_input() -> None:
    with pytest.raises(ValueError):
        parse_study(SID, "")
    with pytest.raises(ValueError):
        parse_study("not-an-id", NORMAL)


def test_the_pgn_hash_tells_versions_apart() -> None:
    assert parse_study(SID, NORMAL).pgn_hash == parse_study(SID, NORMAL).pgn_hash
    assert parse_study(SID, NORMAL).pgn_hash != parse_study(SID, NORMAL + GAMEBOOK).pgn_hash


def test_stored_json_round_trips_and_is_rechecked() -> None:
    c = parse_study(SID, NORMAL).chapters[0]
    stored = json.loads(json.dumps(node_to_json(c.root)))
    assert node_to_json(node_from_json(stored, chess.Board(c.start_fen))) == stored
    # A damaged row can't put an illegal move on the board.
    stored["nodes"][1]["uci"] = "e2e5"
    with pytest.raises(ValueError):
        node_from_json(stored, chess.Board())
    for bad in (
        {"v": 2, "nodes": [{}, {"p": 0, "uci": "zz"}]},
        {"v": 2, "nodes": [{}, {"p": 1, "uci": "e2e4"}]},  # a parent must come first: no cycles
        {"v": 2, "nodes": [{}, {"p": True, "uci": "e2e4"}]},
        {"v": 2, "nodes": [{"p": 0}]},
        {"v": 2, "nodes": []},
        {"v": 1, "nodes": [{}]},
        {"children": [{"uci": "e2e4"}]},  # the old nested layout
    ):
        with pytest.raises(ValueError):
            node_from_json(bad, chess.Board())
    # A stored shape with a bad square or colour is dropped on reading.
    shaped = node_from_json(
        {"v": 2, "nodes": [{"shapes": [["e4", None, "green"], ["z9", None, "red"], ["e2", "e4", "purple"]]}]}
    )
    assert shaped.shapes == [Shape("e4", None, "green")]


def test_qa14_b1_deep_trees_never_recurse_per_move() -> None:
    """Regression (QA v0.14-B1): a 300-move main line and side lines nested 300 deep are kept whole, stored as JSON,
    read back and walked, with Python's recursion limit far below their depth."""
    import sys

    from weaksquare.core.study_pgn import walk
    from weaksquare.core.study_repertoire import study_moves

    cycle = ["Nf3", "Nf6", "Ng1", "Ng8"]
    long_line = " ".join(f"{i // 2 + 1}. {cycle[i % 4]}" if i % 2 == 0 else cycle[i % 4] for i in range(600))
    pgn = f'[Event "S: C1"]\n[ChapterURL "https://lichess.org/study/{SID}/Chap0001"]\n\n{long_line} *\n'
    # Side lines nested 300 deep: at every move, the main move ends and the side line goes on.
    nested = Node()
    at = nested
    for i in range(300):
        side = Node(san=cycle[i % 4], uci=["g1f3", "g8f6", "f3g1", "f6g8"][i % 4])
        at.children = [Node(san="a3" if i % 2 == 0 else "a6", uci="a2a3" if i % 2 == 0 else "a7a6"), side]
        at = side
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(200)
    try:
        long_root = parse_study(SID, pgn).chapters[0].root
        assert len(mainline(long_root)) == 600
        for root in (long_root, nested):
            stored = json.loads(json.dumps(node_to_json(root)))
            back = node_from_json(stored, chess.Board())
            assert node_to_json(back) == stored and len(walk(back)) == len(walk(root))
            assert study_moves(back, chess.STARTING_FEN, True)
    finally:
        sys.setrecursionlimit(old)
