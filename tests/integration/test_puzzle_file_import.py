"""v0.8 puzzle-file import job (FR-10.46–10.48): each format stored with its set label and strict checking,
bad entries reported and skipped, a re-import adds nothing, cancel leaves nothing behind."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from weaksquare.core.errors import NotFoundError, ValidationError

BACK_RANK = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
TWO_MATES = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1"


def _run(services, path: Path, label: str):  # type: ignore[no-untyped-def]
    job = services.puzzle_import.start_import(path, label)
    st = services.puzzle_import._runner.wait(job, 10)
    assert st is not None
    return job, st


def _rows(services, label: str) -> list[tuple]:  # type: ignore[no-untyped-def]
    with services.db.session() as c:
        return c.execute(
            "SELECT fen, solution_uci, origin, strict, set_label, name, player_color, length FROM custom_puzzles"
            " WHERE set_label = ? ORDER BY id",
            (label,),
        ).fetchall()


@pytest.mark.parametrize(
    "name, text",
    [
        (
            "set.pgn",
            f'[Event "One"]\n[FEN "{BACK_RANK}"]\n\n1. Rd8# *\n\n[Event "Two"]\n[FEN "{TWO_MATES}"]\n\n1. Ra8# *\n\n[Event "Bad"]\n\n1. e4 *\n',
        ),
        (
            "set.epd",
            f'{BACK_RANK.rsplit(" ", 2)[0]} bm Rd8#; id "One";\n{TWO_MATES.rsplit(" ", 2)[0]} bm Ra8#; id "Two";\nnot epd at all\n',
        ),
        ("set.csv", f"fen,solution,name\n{BACK_RANK},Rd8#,One\n{TWO_MATES},a1a8,Two\nbad,e4,Bad\n"),
    ],
)
def test_each_format_imports_with_a_report(services, tmp_path: Path, name: str, text: str) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    job, st = _run(services, f, "My book")
    assert st.state == "done" and st.message == "2 added, 0 already there, 1 skipped"
    report = services.puzzle_import.report(job)
    assert (report.added, report.skipped, report.format, report.file_name) == (2, 1, name[-3:], name)
    assert report.errors[0].n == 3 and report.errors[0].reason
    rows = _rows(services, "My book")
    assert [(r[1], r[2], r[3], r[5], r[6], r[7]) for r in rows] == [
        ("d1d8", "import", 1, "One", "white", 1),
        ("a1a8", "import", 1, "Two", "white", 1),
    ]
    assert services.puzzle_import.sets() == [("My book", 2)]


def test_reimporting_the_same_file_adds_nothing_but_another_label_is_another_set(services, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "set.csv"
    f.write_text(f"fen,solution\n{BACK_RANK},Rd8#\n{BACK_RANK},Rd8#\n", encoding="utf-8")  # a duplicate inside too
    _, st = _run(services, f, "Book")
    assert st.message == "1 added, 1 already there, 0 skipped"
    _, st = _run(services, f, "Book")
    assert st.message == "0 added, 2 already there, 0 skipped"  # FR-10.48
    _, st = _run(services, f, "Another book")
    assert st.message == "1 added, 1 already there, 0 skipped"
    assert sorted(services.puzzle_import.sets()) == [("Another book", 1), ("Book", 1)]


def test_cancel_leaves_nothing_behind(services, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "set.csv"
    f.write_text(f"fen,solution\n{BACK_RANK},Rd8#\n", encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    import weaksquare.services.puzzle_import as mod

    real = mod.parse_puzzle_file

    def slow(name: str, text: str):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(5)
        return real(name, text)

    monkeypatch.setattr(mod, "parse_puzzle_file", slow)
    job = services.puzzle_import.start_import(f, "Book")
    entered.wait(5)
    services.puzzle_import._runner.cancel(job)
    release.set()
    st = services.puzzle_import._runner.wait(job, 10)
    assert st.state == "cancelled" and _rows(services, "Book") == []


def test_bad_files_and_labels(services, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "set.csv"
    f.write_text("position,answer\nx,y\n", encoding="utf-8")
    _, st = _run(services, f, "Book")
    assert st.state == "failed" and "header row" in st.message
    with pytest.raises(ValidationError):
        services.puzzle_import.start_import(f, "  ")
    with pytest.raises(NotFoundError):
        services.puzzle_import.start_import(tmp_path / "missing.pgn", "Book")
    big = tmp_path / "big.pgn"
    big.write_bytes(b" " * (20 * 1024 * 1024 + 1))
    with pytest.raises(ValidationError, match="larger than 20 MB"):
        services.puzzle_import.start_import(big, "Book")
