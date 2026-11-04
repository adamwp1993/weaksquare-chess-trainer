"""QA v0.10 on the full puzzle DB (`uv run pytest -m fulldb`): the vendored tagger's theme names are the puzzle
DB's own (FR-10.12), and on real Lichess puzzles it agrees with the DB's tags for the deterministic themes
(mate in N, length, the solver's side). Read-only."""

from __future__ import annotations

import typing

import pytest

from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.core import themes
from weaksquare.core.tagging import MATE_CP, tag_line
from weaksquare.vendor.lichess_puzzler.model import TagKind

pytestmark = pytest.mark.fulldb

DETERMINISTIC = ("mateIn1", "mateIn2", "mateIn3", "oneMove", "short", "long", "veryLong", "mate")


def _db_themes(source: LichessDbSource) -> set[str]:
    with source._db.session() as conn:
        return {r[0] for r in conn.execute("SELECT theme FROM pz.theme_bits")}


def test_qa_every_key_the_tagger_can_keep_is_a_puzzle_db_theme(full_source: LichessDbSource) -> None:
    db = _db_themes(full_source)
    kept = {k for k in typing.get_args(TagKind) if themes.is_known(k)}
    assert kept <= db, sorted(kept - db)


def test_qa_the_tagger_agrees_with_the_db_on_real_mate_puzzles(full_source: LichessDbSource) -> None:
    with full_source._db.session() as conn:
        rows = conn.execute(
            "SELECT id, fen, moves, themes FROM pz.puzzles WHERE themes LIKE '%mateIn%' AND n % 997 = 0 LIMIT 400"
        ).fetchall()
    assert len(rows) >= 100
    db = _db_themes(full_source)
    agree = total = 0
    off: list[tuple[str, set[str], set[str]]] = []
    for pid, fen, moves, tags in rows:
        line = moves.split()
        got = set(tag_line(fen, line[0], line[1:], MATE_CP))
        assert got <= db, (pid, got - db)
        want = set(tags.split())
        for k in DETERMINISTIC:
            total += 1
            if (k in got) == (k in want):
                agree += 1
            elif len(off) < 10:
                off.append((pid, got & set(DETERMINISTIC), want & set(DETERMINISTIC)))
    assert agree / total >= 0.97, off
