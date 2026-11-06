"""The repertoire graph (v0.13, FR-12.4): transpositions share a position, and removal keeps what's still
reachable."""

from __future__ import annotations

import pytest

from weaksquare.core.errors import ValidationError
from weaksquare.core.openings import STARTING_KEY
from weaksquare.core.repertoire import (
    Edge,
    after,
    check_color,
    line_to_moves,
    reachable,
    removal,
    tree_rows,
    your_positions,
)


def edges(*lines: list[str]) -> list[Edge]:
    """Repertoire edges from lines of UCI moves, with repeats merged as the UNIQUE constraint would."""
    out: dict[tuple[str, str], Edge] = {}
    for line in lines:
        for m in line_to_moves([(uci, "book") for uci in line]):
            out.setdefault((m.position_key, m.move_uci), Edge(m.position_key, m.move_uci, m.san, m.source))
    return list(out.values())


# 1.Nf3 d5 2.d4 and 1.d4 d5 2.Nf3 reach the same position.
ORDER_A = ["g1f3", "d7d5", "d2d4", "g8f6"]
ORDER_B = ["d2d4", "d7d5", "g1f3", "g8f6"]


def test_two_move_orders_share_the_position_after_them() -> None:
    graph = edges(ORDER_A, ORDER_B)
    # 3 moves differ on the way there, then the one shared reply: 3 + 3 + 1 distinct edges, minus the shared d5s
    # are at different positions, so only ...Nf6 merges.
    assert len(graph) == 7


def test_removing_one_move_order_keeps_the_position_the_other_still_reaches() -> None:
    graph = edges(ORDER_A, ORDER_B)
    gone = removal(graph, STARTING_KEY, "g1f3")
    assert {e.san for e in gone} == {"Nf3", "d5", "d4"}  # 1.Nf3, its ...d5 and 2.d4
    left = [e for e in graph if e not in gone]
    assert "Nf6" in {e.san for e in left}
    assert reachable(left) == {(e.position_key, e.move_uci) for e in left}


def test_removing_a_move_deletes_what_only_it_could_reach() -> None:
    graph = edges(["e2e4", "e7e5", "g1f3"], ["e2e4", "c7c5", "g1f3"])
    e4 = after(STARTING_KEY, "e2e4")
    gone = removal(graph, e4, "c7c5")
    assert {e.san for e in gone} == {"c5", "Nf3"}
    assert len(graph) - len(gone) == 3


def test_removing_the_only_first_move_empties_the_repertoire() -> None:
    graph = edges(["e2e4", "e7e5"])
    assert len(removal(graph, STARTING_KEY, "e2e4")) == 2


def test_tree_rows_list_a_transposed_position_once_and_mark_it() -> None:
    rows = tree_rows(edges(ORDER_A, ORDER_B), "white")
    assert sum(1 for r in rows if r.edge.san == "Nf6") == 1
    assert sum(1 for r in rows if r.transposes) == 1


def test_tree_rows_say_whose_move_it_is() -> None:
    rows = tree_rows(edges(["e2e4", "e7e5"]), "black")
    assert [(r.edge.san, r.yours, r.depth) for r in rows] == [("e4", False, 0), ("e5", True, 1)]


def test_your_positions_are_the_reachable_ones_on_your_move() -> None:
    orphan = Edge(after(STARTING_KEY, "a2a3"), "a7a6", "a6", "book")
    graph = [*edges(["e2e4", "e7e5", "g1f3", "b8c6"]), orphan]
    black = your_positions(graph, "black")
    assert [e.san for moves in black.values() for e in moves] == ["e5", "Nc6"]
    white = your_positions(graph, "white")
    assert [e.san for moves in white.values() for e in moves] == ["e4", "Nf3"]


def test_main_moves_come_first() -> None:
    a = Edge(STARTING_KEY, "d2d4", "d4", "book", is_main=False, sort_order=0)
    b = Edge(STARTING_KEY, "e2e4", "e4", "book", is_main=True, sort_order=5)
    assert [r.edge.san for r in tree_rows([a, b], "white")][:1] == ["e4"]


@pytest.mark.parametrize("line", [["e2e5"], ["bad"], ["e2e4", "e2e4"]])
def test_an_illegal_move_never_enters(line: list[str]) -> None:
    with pytest.raises(ValidationError):
        line_to_moves([(uci, "you") for uci in line])


def test_color_is_checked() -> None:
    assert check_color("white") == "white"
    with pytest.raises(ValidationError):
        check_color("red")
