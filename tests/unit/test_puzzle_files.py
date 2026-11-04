"""core/puzzle_files.py (v0.8, FR-10.46–10.49): PGN, EPD and CSV puzzle files, bad entries reported
with their number and reason, lines cut to the solver's move."""

from __future__ import annotations

import pytest

from weaksquare.core.puzzle_files import (
    EntryError,
    FileError,
    ImportedPuzzle,
    detect_format,
    parse_csv,
    parse_epd,
    parse_pgn_puzzles,
    parse_puzzle_file,
    validate_label,
)

TWO_MATES = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1"  # Ra8# and Rb8# both mate
BACK_RANK = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"


def ok(entries: list[ImportedPuzzle | EntryError]) -> list[ImportedPuzzle]:
    return [e for e in entries if isinstance(e, ImportedPuzzle)]


def errs(entries: list[ImportedPuzzle | EntryError]) -> list[EntryError]:
    return [e for e in entries if isinstance(e, EntryError)]


def test_pgn_puzzles_with_fen_tags_several_per_file() -> None:
    text = (
        f'[Event "Problem 1"]\n[SetUp "1"]\n[FEN "{BACK_RANK}"]\n\n1. Rd8# *\n\n'
        # three plies: a long line is kept whole
        '[Event "Problem 2"]\n[FEN "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"]\n\n4. Qxf7# *\n\n'
        # two plies: cut to end on the solver's move
        '[Event "Problem 3"]\n[FEN "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1"]\n\n1. Rd8+ Kh7 *\n'
    )
    good = ok(parse_pgn_puzzles(text))
    assert [p.name for p in good] == ["Problem 1", "Problem 2", "Problem 3"]
    assert good[0].solution == ("d1d8",) and good[0].player_color == "white"
    assert good[2].solution == ("d1d8",)


@pytest.mark.parametrize(
    "text, reason",
    [
        ('[Event "x"]\n\n1. e4 e5 *', "no FEN tag"),
        (f'[FEN "{BACK_RANK}"]\n\n1. Rd7 Kf8 2. Ke3 *', "isn't legal"),
        ('[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n\n1. e4 *', "isn't legal"),
        ('[FEN "not a fen"]\n\n1. e4 *', "valid FEN"),
        (f'[Variant "Atomic"]\n[FEN "{BACK_RANK}"]\n\n1. Rd8 *', "standard chess"),
        (f'[FEN "{BACK_RANK}"]\n\n*', "no solution"),
        ('[FEN "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1"]\n\n1... Kh8 *', None),  # Black to move is fine
    ],
)
def test_bad_pgn_entries_are_reported(text: str, reason: str | None) -> None:
    (entry,) = parse_pgn_puzzles(text)
    if reason is None:
        assert isinstance(entry, ImportedPuzzle) and entry.player_color == "black"
    else:
        assert isinstance(entry, EntryError) and reason in entry.reason and entry.n == 1


def test_epd_with_bm_pv_ids_comments_and_errors() -> None:
    text = "\n".join(
        [
            "# a comment line",
            f'{BACK_RANK.rsplit(" ", 2)[0]} bm Rd8#; id "BR.01";',
            f'{BACK_RANK.rsplit(" ", 2)[0]} pv Rd8+; id "BR.02";',
            "8/8/8/8/8/8/8/8 w - - bm e4;",
            f'{BACK_RANK.rsplit(" ", 2)[0]} id "no solution";',
            f"{BACK_RANK.rsplit(' ', 2)[0]} bm Qh5;",
        ]
    )
    entries = parse_epd(text)
    good, bad = ok(entries), errs(entries)
    assert [(p.n, p.name, p.solution) for p in good] == [(1, "BR.01", ("d1d8",)), (2, "BR.02", ("d1d8",))]
    assert [(e.n, e.reason) for e in bad] == [
        (3, "the line isn't valid EPD"),  # an empty board: bm e4 can't be read
        (4, "it has no bm or pv solution"),
        (5, "the line isn't valid EPD"),  # Qh5 can't be read in that position
    ]


def test_csv_by_header_name_with_uci_or_san_and_extra_columns() -> None:
    text = (
        "name,extra,FEN,solution\n"
        f"Back rank,x,{BACK_RANK},Rd8#\n"
        f"UCI,x,{BACK_RANK},d1d8\n"
        "Bad,x,not a fen,e4\n"
        f"Illegal,x,{BACK_RANK},Rd7 Ke9\n"
        "\n"
        f"Short row,x\n"
    )
    entries = parse_csv(text)
    assert [(p.n, p.name, p.solution) for p in ok(entries)] == [(1, "Back rank", ("d1d8",)), (2, "UCI", ("d1d8",))]
    assert [(e.n, e.reason) for e in errs(entries)] == [
        (3, "the position isn't a valid FEN"),
        (4, "move 2 (Ke9) isn't legal"),
        (6, "the row is missing its FEN or solution"),
    ]


def test_csv_needs_fen_and_solution_columns() -> None:
    with pytest.raises(FileError, match="header row"):
        parse_csv("position,answer\nx,y\n")
    assert ok(parse_csv(f"fen,moves\n{BACK_RANK},Rd8#\n"))  # 'moves' works too


def test_a_finished_position_is_not_a_puzzle() -> None:
    (e,) = parse_csv("fen,solution\n3R2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1,h7h6\n")  # Black is mated
    assert isinstance(e, EntryError) and "already over" in e.reason


def test_the_mate_in_one_position_with_two_mates_imports_with_the_files_answer() -> None:
    (p,) = ok(parse_csv(f"fen,solution\n{TWO_MATES},Ra8#\n"))
    assert p.solution == ("a1a8",)  # Rb8# is accepted when solving (any mate counts, §4.2)


def test_format_detection_and_label_rules() -> None:
    assert detect_format("book.PGN", "") == "pgn" and detect_format("x.epd", "") == "epd"
    assert detect_format("x.csv", "") == "csv" and detect_format("x.txt", '[Event "a"]') == "pgn"
    assert detect_format("x.txt", "fen,solution\n") == "csv" and detect_format("x.txt", "8/8 w - -") == "epd"
    assert validate_label("  My   book ") == "My book"
    for bad in ("", "   ", "x" * 61, None):
        with pytest.raises(ValueError):
            validate_label(bad)
    with pytest.raises(FileError, match="No puzzles"):
        parse_puzzle_file("x.epd", "# only a comment\n")
