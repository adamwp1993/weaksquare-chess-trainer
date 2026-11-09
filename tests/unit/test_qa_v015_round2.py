"""QA v0.15 round 2 (independent): B1 and B5 around the fix. Invented data only."""

from __future__ import annotations

import pytest

from weaksquare.core.analysis_pgn import parse_analysis_pgn
from weaksquare.core.games import GameError


@pytest.mark.parametrize(
    "text",
    [
        "1. e4 -- 2. d4 *",  # out of check, on the main line
        "1. e4 e5 (1... -- 2. d4) 2. Nf3 *",  # in a side line
        "1. e4 e5 (1... c5 (1... -- )) 2. Nf3 *",  # in a nested side line
        "1. e4 Z0 2. d4 *",  # the other spelling
    ],
)
def test_qa_r2_b1_a_null_move_anywhere_refuses_the_game_with_its_reason(text: str) -> None:
    with pytest.raises(GameError) as e:
        parse_analysis_pgn(text)
    assert "null move" in e.value.reason


def test_qa_r2_b1_only_the_game_with_a_null_move_is_skipped() -> None:
    text = '[White "A"]\n\n1. e4 e5 *\n\n[White "B"]\n\n1. d4 -- *\n\n[White "C"]\n\n1. c4 *\n'
    games, skipped = parse_analysis_pgn(text)
    assert [g.index for g in games] == [0, 2]
    assert len(skipped) == 1 and "Game 2" in skipped[0] and "null move" in skipped[0]


def test_qa_r2_b1_a_double_dash_in_a_comment_is_not_a_null_move() -> None:
    games, _ = parse_analysis_pgn("1. e4 {a quiet move -- or is it?} e5 *")
    assert games[0].move_count == 2


def test_qa_r2_b5_a_game_from_a_set_position_counts_its_half_moves() -> None:
    games, _ = parse_analysis_pgn('[SetUp "1"]\n[FEN "4k3/4p3/8/8/8/8/8/4K3 b - - 0 1"]\n\n1... e5 (1... e6) 2. Kd2 *')
    assert games[0].move_count == 2
