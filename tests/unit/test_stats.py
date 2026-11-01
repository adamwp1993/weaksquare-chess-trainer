"""FR-9.1, FR-9.2: Stats grouping, pure."""

from __future__ import annotations

from weaksquare.core.stats import AttemptRow, band_label, build_report


def row(win: bool, first: bool, rating: int | None, themes: str | None, length: int | None) -> AttemptRow:
    return AttemptRow(win, first, win, rating, None if themes is None else tuple(themes.split()), length)


ROWS = [
    row(True, True, 1250, "fork short", 2),
    row(False, True, 1399, "fork pin long", 3),  # first move right, line wrong
    row(False, False, 1400, "pin", 1),
    row(True, True, 2100, "fork veryLong", 6),
    row(False, True, 900, None, None),  # puzzle gone from the database
    row(True, True, None, "mate", 1),  # an old attempt whose rating couldn't be recovered
]


def test_overall_and_line_wrong_rate() -> None:
    r = build_report(ROWS, str.upper)
    assert (r.overall.attempts, r.overall.solved) == (6, 3)
    assert r.overall.accuracy == 0.5
    assert r.overall.first_right == 5 and r.overall.first_right_line_wrong == 2
    assert r.overall.line_wrong_rate == 2 / 5
    assert r.missing == 1


def test_by_theme_counts_each_theme_once_per_attempt_most_played_first() -> None:
    r = build_report(ROWS, str.upper)
    by = {t.key: t for t in r.by_theme}
    assert r.by_theme[0].key == "fork" and by["fork"].attempts == 3 and by["fork"].solved == 2
    assert by["fork"].label == "FORK"
    assert by["pin"].attempts == 2 and by["pin"].accuracy == 0
    assert by["fork"].line_wrong_rate == 1 / 3


def test_by_length_groups_four_plus() -> None:
    r = build_report(ROWS, str)
    assert [(t.label, t.attempts) for t in r.by_length] == [
        ("1 move", 2),
        ("2 moves", 1),
        ("3 moves", 1),
        ("4+ moves", 1),
    ]


def test_by_rating_bands_of_200_with_unknown_last() -> None:
    r = build_report(ROWS, str)
    assert [(t.label, t.attempts) for t in r.by_rating] == [
        ("800–999", 1), ("1200–1399", 2), ("1400–1599", 1), ("2000–2199", 1), ("Unknown", 1)
    ]  # fmt: skip
    assert band_label(1200) == "1200–1399"


def test_empty() -> None:
    r = build_report([], str)
    assert r.overall.attempts == 0 and r.overall.accuracy is None and r.overall.line_wrong_rate is None
    assert r.by_theme == r.by_length == r.by_rating == [] and r.missing == 0
