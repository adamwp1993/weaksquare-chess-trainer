"""Done-when: the live count matches a direct SQL query for 20 random FilterSpecs.

The oracle is deliberately independent of the bitmask SQL: it matches themes as words in the raw
`themes` text and filters lengths/sides/ratings with plain comparisons.
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

import pytest

from weaksquare.core.filters import FilterSpec

THEMES_SEED = 2026


def oracle_count(conn: sqlite3.Connection, spec: FilterSpec) -> int:
    clauses, params = [], []
    if spec.rating_min is not None:
        clauses.append("rating >= ?")
        params.append(spec.rating_min)
    if spec.rating_max is not None:
        clauses.append("rating <= ?")
        params.append(spec.rating_max)
    if not spec.all_lengths:
        ors = [("length >= 4" if n == 4 else f"length = {n}") for n in spec.lengths]
        clauses.append("(" + " OR ".join(ors) + ")")
    if spec.side != "either":
        clauses.append("player_color = ?")
        params.append(0 if spec.side == "white" else 1)
    word = "(' ' || themes || ' ') LIKE ?"
    if spec.themes:
        joined = (" AND " if spec.match == "all" else " OR ").join([word] * len(spec.themes))
        clauses.append(f"({joined})")
        params += [f"% {t} %" for t in spec.themes]
    for t in spec.exclude_themes:
        clauses.append(f"NOT {word}")
        params.append(f"% {t} %")
    sql = "SELECT COUNT(*) FROM puzzles" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    return int(conn.execute(sql, params).fetchone()[0])


def all_themes(conn: sqlite3.Connection) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT theme FROM theme_bits"))


def random_spec(rng: random.Random, themes: list[str], lo: int, hi: int) -> FilterSpec:
    picked = rng.sample(themes, rng.choice([0, 1, 1, 2, 2, 3]))
    excluded = rng.sample([t for t in themes if t not in picked], rng.choice([0, 0, 1, 2]))
    rmin = rng.choice([None, rng.randint(lo, hi)])
    rmax = rng.choice([None, rng.randint(rmin or lo, hi)])
    lengths = tuple(sorted(rng.sample([1, 2, 3, 4], rng.choice([0, 1, 2, 3]))))
    return FilterSpec(themes=tuple(picked), match=rng.choice(["any", "all"]), exclude_themes=tuple(excluded),
                      rating_min=rmin, rating_max=rmax, lengths=lengths,
                      side=rng.choice(["either", "white", "black"]))  # fmt: skip


def random_specs(conn: sqlite3.Connection, n: int, seed: int) -> list[FilterSpec]:
    rng = random.Random(seed)
    themes = all_themes(conn)
    lo, hi = conn.execute("SELECT MIN(rating), MAX(rating) FROM puzzles").fetchone()
    return [random_spec(rng, themes, lo, hi) for _ in range(n)]


@pytest.fixture
def raw(fixture_puzzles_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{fixture_puzzles_db.as_posix()}?mode=ro", uri=True)
    yield conn
    conn.close()


@pytest.mark.parametrize("i", range(20))
def test_count_matches_oracle(services, raw: sqlite3.Connection, i: int) -> None:  # type: ignore[no-untyped-def]
    spec = random_specs(raw, 20, THEMES_SEED)[i]
    assert services.mixer.count(spec) == oracle_count(raw, spec), spec


EDGE_SPECS = {
    "everything": FilterSpec(),
    "zero matches": FilterSpec(rating_min=3999, rating_max=4000),
    "all with never-co-occurring themes": FilterSpec(themes=("oneMove", "veryLong"), match="all"),
    "unknown theme any": FilterSpec(themes=("noSuchTheme",)),
    "unknown theme all": FilterSpec(themes=("fork", "noSuchTheme"), match="all"),
    "exclude unknown theme": FilterSpec(exclude_themes=("noSuchTheme",)),
    "exclude overlaps include": FilterSpec(themes=("fork",), exclude_themes=("fork",)),
    "rating at both bounds": FilterSpec(rating_min=0, rating_max=4000),
    "4+ only": FilterSpec(lengths=(4,)),
    "fork AND long 1200-1600": FilterSpec(themes=("fork", "long"), match="all", rating_min=1200, rating_max=1600),
}


@pytest.mark.parametrize("name", EDGE_SPECS)
def test_edge_specs(services, raw: sqlite3.Connection, name: str) -> None:  # type: ignore[no-untyped-def]
    spec = EDGE_SPECS[name]
    assert services.mixer.count(spec) == oracle_count(raw, spec)


def test_edge_expectations(services) -> None:  # type: ignore[no-untyped-def]
    count = services.mixer.count
    assert count(EDGE_SPECS["zero matches"]) == 0
    assert count(EDGE_SPECS["all with never-co-occurring themes"]) == 0
    assert count(EDGE_SPECS["exclude overlaps include"]) == 0
    assert count(EDGE_SPECS["exclude unknown theme"]) == count(EDGE_SPECS["everything"])
