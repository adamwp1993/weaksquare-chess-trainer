"""FR-2.2: the CSV is read by header name, extra columns are ignored, bad rows are skipped."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from weaksquare.core.csv_rows import HeaderError, header_index, parse_row

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "puzzles_sample.csv"
ROW = {
    "PuzzleId": "001KR",
    "FEN": "6Qk/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K b - - 0 28",
    "Moves": "h8g8 f1f8",
    "Rating": "563",
    "RatingDeviation": "81",
    "Popularity": "100",
    "NbPlays": "185",
    "Themes": "mate mateIn1 middlegame oneMove",
    "GameUrl": "https://lichess.org/GAMEID01",
    "OpeningTags": "",
}


def _parse(header: list[str]) -> object:
    return parse_row(header_index(header), [ROW.get(h, "x") for h in header])


def test_column_order_and_extra_columns_do_not_matter() -> None:
    normal = list(ROW)
    shuffled = ["DailyDate", *reversed(normal), "SomethingNew"]
    a, b = _parse(normal), _parse(shuffled)
    assert a == b
    assert a is not None and a.id == "001KR" and a.length == 1 and a.player_color == "white"  # type: ignore[attr-defined]
    assert a.themes == ("mate", "mateIn1", "middlegame", "oneMove")  # type: ignore[attr-defined]


def test_opening_tags_optional() -> None:
    header = [h for h in ROW if h != "OpeningTags"]
    row = _parse(header)
    assert row is not None and row.opening_tags == ""  # type: ignore[attr-defined]


def test_missing_required_column() -> None:
    with pytest.raises(HeaderError, match="Moves"):
        header_index([h for h in ROW if h != "Moves"])


@pytest.mark.parametrize(
    "field,value",
    [("Moves", "h8g8"), ("Moves", "h8g8 zz99"), ("Rating", "abc"), ("FEN", "8/8/8 w"), ("PuzzleId", "")],
)
def test_bad_rows_are_skipped(field: str, value: str) -> None:
    header = list(ROW)
    idx = header_index(header)
    row = [value if h == field else ROW[h] for h in header]
    assert parse_row(idx, row) is None


def test_whole_fixture_parses() -> None:
    with FIXTURE.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        idx = header_index(next(reader))
        assert "DailyDate" in idx  # the fixture keeps the export's extra column
        rows = [parse_row(idx, r) for r in reader]
    assert len(rows) >= 300 and all(r is not None for r in rows)
