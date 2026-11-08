"""FR-13.11 (v0.14): which study moves join a repertoire, conflicts, and reachability. Pure; invented lines."""

from __future__ import annotations

import chess

from weaksquare.core.openings import STARTING_KEY, position_key
from weaksquare.core.repertoire import Edge, line_to_moves, reachable
from weaksquare.core.study_pgn import Node, mainline
from weaksquare.core.study_repertoire import plan_add, resolve, study_moves


def tree(*lines: str) -> Node:
    """A tree from space-separated UCI lines; the first is the main line."""
    root = Node()
    for line in lines:
        node = root
        board = chess.Board()
        for uci in line.split():
            move = chess.Move.from_uci(uci)
            nxt = next((c for c in node.children if c.uci == uci), None)
            if nxt is None:
                nxt = Node(san=board.san(move), uci=uci)
                node.children.append(nxt)
            board.push(move)
            node = nxt
    return root


def edges_of(ucis: str, source: str = "you") -> list[Edge]:
    return [
        Edge(m.position_key, m.move_uci, m.san, m.source) for m in line_to_moves([(u, source) for u in ucis.split()])
    ]


START = chess.STARTING_FEN
# 1.e4 e5 2.Nc3 Nf6 3.f4, with a side line 2...Nc6 3.f4 and a side line for White 3.Bc4.
VIENNA = tree("e2e4 e7e5 b1c3 g8f6 f2f4", "e2e4 e7e5 b1c3 b8c6 f2f4", "e2e4 e7e5 b1c3 g8f6 f1c4")


def test_main_line_only_by_default() -> None:
    moves = study_moves(VIENNA, START, include_side_lines=False)
    assert [m.san for m in moves] == ["e4", "e5", "Nc3", "Nf6", "f4"]
    assert {m.source for m in moves} == {"study"}
    assert [n.san for n in mainline(VIENNA)] == ["e4", "e5", "Nc3", "Nf6", "f4"]


def test_side_lines_add_every_move_once() -> None:
    moves = study_moves(VIENNA, START, include_side_lines=True)
    assert [m.san for m in moves] == ["e4", "e5", "Nc3", "Nf6", "f4", "Bc4", "Nc6", "f4"]
    assert len({(m.position_key, m.move_uci) for m in moves}) == len(moves)


def test_a_new_repertoire_takes_the_whole_main_line() -> None:
    cands = study_moves(VIENNA, START, False)
    plan = plan_add([], cands, "white")
    assert [m.san for m in plan.new] == ["e4", "e5", "Nc3", "Nf6", "f4"]
    assert (plan.already, plan.unreachable, plan.conflicts) == (0, 0, [])


def test_moves_you_have_are_counted_not_added_again() -> None:
    have = edges_of("e2e4 e7e5 b1c3")
    plan = plan_add(have, study_moves(VIENNA, START, False), "white")
    assert [m.san for m in plan.new] == ["Nf6", "f4"]
    assert plan.already == 3


def test_a_conflict_keeps_your_move_unless_you_choose_the_study() -> None:
    have = edges_of("e2e4 e7e5 g1f3")  # you play 2.Nf3, the study 2.Nc3
    cands = study_moves(VIENNA, START, False)
    plan = plan_add(have, cands, "white")
    assert len(plan.conflicts) == 1
    c = plan.conflicts[0]
    assert (c.yours, c.study, c.path) == (["Nf3"], ["Nc3"], ["e4", "e5"])
    assert plan.new == []  # Nc3 and everything after it wait on your choice
    assert plan.unreachable == 0  # reachable if you choose the study's move
    to_add, mains = resolve(have, cands, "white", {})
    assert to_add == [] and mains == []
    to_add, mains = resolve(have, cands, "white", {c.position_key: "study"})
    assert [m.san for m in to_add] == ["Nc3", "Nf6", "f4"]
    assert mains == [(c.position_key, "b1c3")]  # the study's move becomes main; Nf3 stays as a sideline


def test_the_other_sides_moves_never_conflict() -> None:
    have = edges_of("e2e4 c7c5")  # Black's 1...c5 is already a reply you know
    plan = plan_add(have, study_moves(VIENNA, START, False), "white")
    assert plan.conflicts == []
    assert [m.san for m in plan.new] == ["e5", "Nc3", "Nf6", "f4"]


def test_a_transposition_reuses_its_position() -> None:
    # You reach the Vienna position by 1.Nc3 e5 2.e4; the study by 1.e4 e5 2.Nc3. Same position, same key.
    have = edges_of("b1c3 e7e5 e2e4")
    cands = study_moves(VIENNA, START, False)
    plan = plan_add(have, cands, "white")
    after_vienna = chess.Board()
    for u in ("b1c3", "e7e5", "e2e4"):
        after_vienna.push_uci(u)
    nf6 = next(m for m in plan.new if m.san == "Nf6")
    assert nf6.position_key == position_key(after_vienna)
    # 1.e4 itself conflicts with your 1.Nc3: kept as yours, the rest still joins through the transposition.
    assert [c.study for c in plan.conflicts] == [["e4"]]
    assert [m.san for m in plan.new] == ["Nf6", "f4"]


def test_a_chapter_from_a_set_position_joins_only_if_you_reach_it() -> None:
    board = chess.Board()
    for u in ("e2e4", "e7e5", "b1c3"):
        board.push_uci(u)
    fen = board.fen()
    chapter = Node(children=[Node(san="Nf6", uci="g8f6", children=[Node(san="f4", uci="f2f4")])])
    cands = study_moves(chapter, fen, False)
    alone = plan_add([], cands, "white")
    assert alone.new == [] and alone.unreachable == 2
    joined = plan_add(edges_of("e2e4 e7e5 b1c3"), cands, "white")
    assert [m.san for m in joined.new] == ["Nf6", "f4"] and joined.unreachable == 0


def test_nothing_added_is_ever_unreachable() -> None:
    have = edges_of("e2e4 e7e5 g1f3")
    cands = study_moves(VIENNA, START, True)
    for choice in ({}, {plan_add(have, cands, "white").conflicts[0].position_key: "study"}):
        to_add, _ = resolve(have, cands, "white", choice)  # type: ignore[arg-type]
        ok = reachable(have + [Edge(m.position_key, m.move_uci, m.san, m.source) for m in to_add], (STARTING_KEY,))
        assert all((m.position_key, m.move_uci) in ok for m in to_add)
