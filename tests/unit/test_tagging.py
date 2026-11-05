"""The lichess-puzzler tagger on known positions (FR-10.12)."""

from __future__ import annotations

import typing

from weaksquare.core import themes
from weaksquare.core.tagging import MATE_CP, tag_line
from weaksquare.vendor.lichess_puzzler.model import TagKind

# Black's last move h7h6, then Nc7+ forks the king and the rook on a8.
FORK = "r3k3/7p/8/3N4/8/8/8/6K1 b - - 0 1"
# Black's last move a7a6, then Rd8 mates on the back rank.
BACK_RANK = "6k1/p4ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1"
# Black's queen goes to d4, where the knight takes it for free.
HANGING = "4k3/3q4/8/8/8/5N2/8/4K3 b - - 0 1"


def test_fork() -> None:
    tags = tag_line(FORK, "h7h6", ["d5c7", "e8d7", "c7a8"], 500)
    assert "fork" in tags
    assert "short" in tags


def test_back_rank_mate_in_one() -> None:
    tags = tag_line(BACK_RANK, "a7a6", ["d1d8"], MATE_CP)
    assert {"mateIn1", "mate", "backRankMate", "oneMove"} <= set(tags)


def test_hanging_piece() -> None:
    tags = tag_line(HANGING, "d7d4", ["f3d4"], 900)
    assert "hangingPiece" in tags
    assert "crushing" in tags


def test_no_premove_uses_a_null_move() -> None:
    tags = tag_line("r3k3/7p/8/3N4/8/8/8/6K1 w - - 0 1", None, ["d5c7", "e8d7", "c7a8"], 500)
    assert "fork" in tags


def test_line_is_trimmed_to_end_on_the_solver() -> None:
    assert "oneMove" in tag_line(FORK, "h7h6", ["d5c7", "e8d7"], 500)


def test_illegal_input_is_cut_or_untagged() -> None:
    assert tag_line(FORK, "h7h6", ["d5c7", "e8d7", "a1a8"], 500) == tag_line(FORK, "h7h6", ["d5c7"], 500)
    assert tag_line(FORK, "e2e4", ["d5c7"], 500) == ()
    assert tag_line(FORK, "h7h6", [], 500) == ()
    assert tag_line(FORK, "h7h6", ["zz"], 500) == ()
    assert tag_line("not a fen", "h7h6", ["d5c7"], 500) == ()


def test_every_tag_is_a_puzzle_db_theme() -> None:
    for fen, pre, line, cp in [
        (FORK, "h7h6", ["d5c7", "e8d7", "c7a8"], 500),
        (BACK_RANK, "a7a6", ["d1d8"], MATE_CP),
        (HANGING, "d7d4", ["f3d4"], 900),
    ]:
        assert all(themes.is_known(t) for t in tag_line(fen, pre, line, cp))


def test_tagger_keys_outside_the_catalog_are_the_known_internal_ones() -> None:
    unknown = {k for k in typing.get_args(TagKind) if not themes.is_known(k)}
    assert unknown == {"coercion", "collinearMove", "overloading", "simplification"}
