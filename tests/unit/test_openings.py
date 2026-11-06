"""The opening book (v0.13, FR-12.1, 12.2, 12.7a, 12.13): parsing, position keys, ranking and line selection.
The tests on the real bundled book are in `test_openings_bundled_book`, below."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import chess
import pytest

from weaksquare import config
from weaksquare.core.openings import (
    SOURCE_ENGINE,
    Line,
    OpeningDataError,
    build_index,
    extend_line,
    families,
    parse_line,
    position_key,
    ranked_moves,
    root_of,
    rows_of_tsv,
    select_lines,
)

ITALIAN = "1. e4 e5 2. Nf3 Nc6 3. Bc4"


def small_book() -> list:  # type: ignore[type-arg]
    rows = [
        ("C50", "Italian Game", ITALIAN),
        ("C50", "Italian Game: Giuoco Piano", ITALIAN + " Bc5"),
        ("C53", "Italian Game: Classical", ITALIAN + " Bc5 4. c3"),
        ("C53", "Italian Game: Classical, Main", ITALIAN + " Bc5 4. c3 Nf6 5. d4"),
        ("C51", "Italian Game: Evans Gambit", ITALIAN + " Bc5 4. b4"),
        ("C55", "Italian Game: Two Knights", ITALIAN + " Nf6"),
        ("C50", "Italian Game: Rousseau Gambit", ITALIAN + " f5"),
    ]
    return [parse_line(*r, i + 1) for i, r in enumerate(rows)]


# ---- parsing ---------------------------------------------------------------------------------------


def test_a_line_is_parsed_into_moves_and_positions() -> None:
    line = parse_line("C50", "Italian Game", ITALIAN)
    assert line.moves == ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4")
    assert line.sans[-1] == "Bc4"
    assert len(line.keys) == 6 and line.family == "Italian Game"


@pytest.mark.parametrize("pgn", ["1. e5", "1. e4 e5 2. Ke3", "1. e4 banana", ""])
def test_an_illegal_line_is_rejected(pgn: str) -> None:
    with pytest.raises(OpeningDataError):
        parse_line("A00", "Bad", pgn)


def test_rows_are_read_by_header_name() -> None:
    assert list(rows_of_tsv("pgn\tname\teco\n1. e4\tKing\tB00\n")) == [("B00", "King", "1. e4")]
    with pytest.raises(OpeningDataError):
        list(rows_of_tsv("eco\tname\n"))


def test_position_keys_ignore_move_order_and_counters() -> None:
    a = parse_line("A", "One", "1. Nf3 d5 2. d4 Nf6")
    b = parse_line("A", "Two", "1. d4 d5 2. Nf3 Nf6")
    assert a.final_key == b.final_key
    assert a.moves != b.moves


def test_en_passant_is_in_the_key_only_when_the_capture_is_legal() -> None:
    quiet = chess.Board()
    quiet.push_san("e4")  # no black pawn can take: the same position whichever way it's reached
    assert position_key(quiet).split()[3] == "-"
    can_take = chess.Board("rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 3")
    assert position_key(can_take).split()[3] == "e3"


# ---- browse and ranking ----------------------------------------------------------------------------


def test_a_family_has_one_entry_and_its_own_root() -> None:
    book = small_book()
    found = families(book)
    assert [f.name for f in found] == ["Italian Game"]
    assert found[0].lines == 7 and found[0].root.name == "Italian Game"


def test_a_family_without_an_exact_name_uses_its_shortest_line() -> None:
    book = [parse_line("B", "X: Long", "1. e4 c5 2. Nf3"), parse_line("B", "X: Short", "1. e4 c5")]
    root = root_of(book, "X")
    assert root is not None and root.name == "X: Short"


def test_moves_rank_by_book_lines_then_popularity_wins() -> None:
    book = small_book()
    ix = build_index(book)
    key = book[0].final_key
    assert ranked_moves(ix, key)[0] == "f8c5"  # four lines go through 3...Bc5
    assert ranked_moves(ix, key, {"g8f6": 900, "f8c5": 100})[0] == "g8f6"


def test_ranking_does_not_depend_on_input_order() -> None:
    book = small_book()
    key = book[0].final_key
    assert ranked_moves(build_index(book), key) == ranked_moves(build_index(list(reversed(book))), key)


def test_transposed_lines_merge_their_moves() -> None:
    a = parse_line("A", "One", "1. Nf3 d5 2. d4 Nf6 3. c4")
    b = parse_line("A", "Two", "1. d4 d5 2. Nf3 Nf6 3. Bf4")
    ix = build_index([a, b])
    assert set(ix.moves[a.keys[4]]) == {"c2c4", "c1f4"}


# ---- lines -----------------------------------------------------------------------------------------


def sans(line: Line) -> list[str]:
    return [m.san for m in line.moves]


def test_the_main_line_follows_the_top_move_to_the_end_of_the_book() -> None:
    book = small_book()
    main = select_lines(build_index(book), book[0], 0, 12)
    assert len(main) == 1
    assert sans(main[0])[5:] == ["Bc5", "c3", "Nf6", "d4"]
    assert main[0].name == "Italian Game: Classical, Main"
    assert {m.source for m in main[0].moves} == {"book"}


def test_sub_lines_are_the_next_branches_and_never_repeat() -> None:
    book = small_book()
    lines = select_lines(build_index(book), book[0], 3, 12)
    assert len(lines) == 4
    assert len({tuple(sans(ln)) for ln in lines}) == 4
    assert {ln.name for ln in lines[1:]} == {
        "Italian Game: Evans Gambit", "Italian Game: Two Knights", "Italian Game: Rousseau Gambit",
    }  # fmt: skip


def test_asking_for_more_sub_lines_than_exist_gives_what_there_is() -> None:
    book = small_book()
    assert len(select_lines(build_index(book), book[0], 10, 12)) == 4


def test_moves_per_line_is_an_upper_limit() -> None:
    book = small_book()
    lines = select_lines(build_index(book), book[0], 3, 4)
    assert all(len(ln.moves) <= 8 for ln in lines)
    assert sans(lines[0]) == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6"]


def test_popularity_changes_which_line_is_main() -> None:
    book = small_book()
    root = book[0]

    def pop(key: str) -> dict[str, int] | None:
        return {"g8f6": 500} if key == root.final_key else None

    main = select_lines(build_index(book), root, 0, 12, pop)[0]
    assert sans(main)[5] == "Nf6"


def test_extending_adds_labelled_moves_up_to_the_limit() -> None:
    book = small_book()
    line = select_lines(build_index(book), book[0], 0, 12)[0]

    def engine(board: chess.Board) -> tuple[str, str]:
        return next(iter(board.legal_moves)).uci(), SOURCE_ENGINE

    longer = extend_line(line, 12, engine)
    assert len(longer.moves) == 24
    assert longer.moves[len(line.moves) - 1].source == "book"
    assert longer.moves[len(line.moves)].source == "engine"


def test_extending_stops_at_an_illegal_or_missing_move() -> None:
    book = small_book()
    line = select_lines(build_index(book), book[0], 0, 12)[0]
    assert extend_line(line, 12, lambda _b: ("a1a8", "engine")).moves == line.moves
    assert extend_line(line, 12, lambda _b: ("not a move", "engine")).moves == line.moves
    assert extend_line(line, 12, lambda _b: None).moves == line.moves


# ---- the real bundled book -------------------------------------------------------------------------


PIN = {
    "a.tsv": "3282e4c9155289a29224f9a85fba0decb46efa35c2fa5e39662d2ac48fb0f793",
    "b.tsv": "2744a3890879bd9dce79093147fe5b6c3a9d9d42a3388af698e67b6829be1c48",
    "c.tsv": "447bbd4b15d68067b150faf12bf66aa14b18582cf80d736aaa7c0081131806ef",
    "d.tsv": "1cf4057a8aece94f27bb3f278ad410ee2844831a642364eeceaafa091dbcceda",
    "e.tsv": "48c6f6645b031a5937c8386839debab0e2e48837251687ba1afb6369677f8546",
}


def bundled() -> list:  # type: ignore[type-arg]
    folder = Path(config.OPENING_BOOK_DIR)
    return [
        parse_line(*row, 0) for name in sorted(PIN) for row in rows_of_tsv((folder / name).read_text(encoding="utf-8"))
    ]


def test_the_bundled_files_match_their_pin() -> None:
    folder = Path(config.OPENING_BOOK_DIR)
    for name, digest in PIN.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest


def test_every_bundled_line_is_legal() -> None:
    assert len(bundled()) == 3865


def test_the_bundled_italian_main_line_is_a_real_main_line() -> None:
    book = bundled()
    root = root_of(book, "Italian Game")
    assert root is not None
    lines = select_lines(build_index(book), root, 3, 12)
    assert sans(lines[0])[:6] == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]
    assert len(lines) == 4


def test_the_bundled_files_are_not_git_ignored() -> None:
    """A `data/` ignore rule once kept them out of the repo, so a fresh clone would have had no book."""
    folder = Path(config.OPENING_BOOK_DIR)
    for name in PIN:
        done = subprocess.run(["git", "check-ignore", "-q", str(folder / name)], cwd=folder, check=False)
        assert done.returncode == 1, f"{name} is ignored"
