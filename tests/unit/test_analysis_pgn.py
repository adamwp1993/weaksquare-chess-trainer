"""v0.15, FR-14.3: a pasted PGN becomes a move tree with its side lines; a bad one changes nothing.

Invented games only: no real players, events or links (SR-12a)."""

from __future__ import annotations

import pytest

from weaksquare.core.analysis_pgn import MAX_GAMES, parse_analysis_pgn
from weaksquare.core.games import GameError
from weaksquare.core.study_pgn import mainline, walk

GAME = """[Event "Invented Open"]
[White "Player A"]
[Black "Player B"]
[Date "2026.10.01"]
[Result "1-0"]

1. e4 {[%clk 0:05:00] A good start. See https://example.org} e5 (1... c5 2. Nf3 (2. c3) d6) 2. Nf3 $1 Nc6 1-0
"""


def test_a_game_keeps_its_main_line_side_lines_comments_and_glyphs() -> None:
    games, skipped = parse_analysis_pgn(GAME)
    assert skipped == [] and len(games) == 1
    g = games[0]
    assert [n.san for n in mainline(g.root)] == ["e4", "e5", "Nf3", "Nc6"]
    e4 = g.root.children[0]
    assert [c.san for c in e4.children] == ["e5", "c5"]  # the side line is kept
    assert [c.san for c in e4.children[1].children] == ["Nf3", "c3"]  # nested inside the side line
    assert e4.comment == "A good start. See https://example.org"  # plain text; the UI never makes it a link
    assert "clk" not in e4.comment
    assert mainline(g.root)[2].nags == [1]
    assert g.move_count == 4 and g.label == "Player A – Player B, 2026.10.01 (1-0)"


def test_headers_and_clocks_are_nowhere_in_the_tree() -> None:
    g = parse_analysis_pgn(GAME)[0][0]
    text = " ".join(f"{n.san} {n.uci} {n.comment}" for n in walk(g.root))
    for leaked in ("Invented Open", "Player A", "Player B", "2026.10.01", "0:05:00", "clk"):
        assert leaked not in text


def test_a_game_from_a_set_position_starts_there() -> None:
    pgn = '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]\n\n1. e4 Kd7 *'
    g = parse_analysis_pgn(pgn)[0][0]
    assert g.start_fen == "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1" and g.label == "Game 1"


def test_a_position_with_no_moves_is_a_game() -> None:
    g = parse_analysis_pgn('[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]\n\n*')[0][0]
    assert g.move_count == 0


def test_moves_without_headers_are_a_game() -> None:
    assert [n.san for n in mainline(parse_analysis_pgn("1. d4 d5 2. c4")[0][0].root)] == ["d4", "d5", "c4"]


def test_several_games_are_listed_and_a_bad_one_is_skipped_with_a_reason() -> None:
    bad = '[Event "x"]\n\n1. e4 e5 2. Ke3 Ke6 3. Qh5 Kf9 *\n\n'  # an unreadable move
    variant = '[Variant "Atomic"]\n\n1. e4 *\n\n'
    games, skipped = parse_analysis_pgn(GAME + "\n" + bad + variant + "1. c4 *")
    assert [g.index for g in games] == [0, 3]
    assert len(skipped) == 2
    assert "Game 2" in skipped[0] and "illegal or unreadable" in skipped[0]
    assert "Game 3" in skipped[1] and "Atomic" in skipped[1]


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("", "Paste a PGN"),
        ("hello world", "isn't a PGN"),
        ('[Variant "Crazyhouse"]\n\n1. e4 *', "only standard chess"),
        ('[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n\n*', "impossible position"),
        ("1. e4 e5 2. Qxf7", "illegal or unreadable"),
    ],
)
def test_a_pgn_with_nothing_usable_raises_one_clear_message(text: str, says: str) -> None:
    with pytest.raises(GameError) as e:
        parse_analysis_pgn(text)
    assert says in e.value.reason


def test_a_file_with_too_many_games_says_so() -> None:
    games, skipped = parse_analysis_pgn("1. e4 *\n\n" * (MAX_GAMES + 5))
    assert len(games) == MAX_GAMES and "more than" in skipped[-1]


def test_qa_b1_a_study_chapter_with_a_null_move_is_rejected_and_the_rest_kept() -> None:
    """QA v0.15-B1: python-chess accepts "--" even while in check; the shared converter must never pass one on."""
    from weaksquare.core.study_pgn import parse_study

    pgn = (
        '[Event "S: One"]\n[ChapterName "One"]\n\n1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- 4. Qxe8 *\n\n'
        '[Event "S: Two"]\n[ChapterName "Two"]\n\n1. d4 d5 (1... --) *\n\n'
        '[Event "S: Three"]\n[ChapterName "Three"]\n\n1. c4 *\n'
    )
    chapters = parse_study("AbCd1234", pgn).chapters
    assert [c.rejected is not None for c in chapters] == [True, True, False]
    assert "null move" in (chapters[0].rejected or "") and "null move" in (chapters[1].rejected or "")
