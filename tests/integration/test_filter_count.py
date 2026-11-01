"""Done-when: the live count matches a direct SQL query for random FilterSpecs (20 in v0.1, 40 since v0.2).

The oracle is deliberately independent of the bitmask SQL: it matches themes and openings as words
in the raw `themes` / `opening_tags` text, filters lengths/sides/ratings/quality with plain
comparisons, and takes the history sets (FR-3.9) computed in Python from the attempts.
"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from weaksquare.core.filters import FilterSpec

THEMES_SEED = 2026


def oracle_count(
    conn: sqlite3.Connection,
    spec: FilterSpec,
    solved: frozenset[str] = frozenset(),
    missed: frozenset[str] = frozenset(),
) -> int:
    clauses: list[str] = []
    params: list[object] = []
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
    if spec.min_popularity is not None:
        clauses.append("popularity >= ?")
        params.append(spec.min_popularity)
    if spec.min_plays is not None:
        clauses.append("nb_plays >= ?")
        params.append(spec.min_plays)
    if spec.openings:
        tag = "(' ' || opening_tags || ' ') LIKE ?"
        clauses.append("(" + " OR ".join([tag] * len(spec.openings)) + ")")
        params += [f"% {o} %" for o in spec.openings]
    if spec.only_my_misses or spec.excludes_solved:
        ids = sorted(missed if spec.only_my_misses else solved)
        op = "IN" if spec.only_my_misses else "NOT IN"
        if ids:
            clauses.append(f"id {op} ({', '.join('?' * len(ids))})")
            params += ids
        elif op == "IN":
            clauses.append("0")
    sql = "SELECT COUNT(*) FROM puzzles" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    return int(conn.execute(sql, params).fetchone()[0])


def all_themes(conn: sqlite3.Connection) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT theme FROM theme_bits"))


def all_openings(conn: sqlite3.Connection) -> list[str]:
    try:
        return sorted(r[0] for r in conn.execute("SELECT tag FROM openings"))
    except sqlite3.OperationalError:  # a v1 puzzles.db (a fulldb run before the upgrade)
        return []


def random_spec(rng: random.Random, themes: list[str], lo: int, hi: int, openings: Sequence[str] = ()) -> FilterSpec:
    picked = rng.sample(themes, rng.choice([0, 1, 1, 2, 2, 3]))
    excluded = rng.sample([t for t in themes if t not in picked], rng.choice([0, 0, 1, 2]))
    rmin = rng.choice([None, rng.randint(lo, hi)])
    rmax = rng.choice([None, rng.randint(rmin or lo, hi)])
    lengths = tuple(sorted(rng.sample([1, 2, 3, 4], rng.choice([0, 1, 2, 3]))))
    chosen_openings = tuple(rng.sample(list(openings), rng.choice([0, 0, 0, 1, 2]))) if openings else ()
    return FilterSpec(themes=tuple(picked), match=rng.choice(["any", "all"]), exclude_themes=tuple(excluded),
                      rating_min=rmin, rating_max=rmax, lengths=lengths,
                      side=rng.choice(["either", "white", "black"]), openings=chosen_openings,
                      min_popularity=rng.choice([None, 50, rng.randint(-100, 100)]),
                      min_plays=rng.choice([None, 100, rng.randint(0, 5000)]),
                      exclude_solved_here=rng.choice([True, False]),
                      only_my_misses=rng.random() < 0.2)  # fmt: skip


def random_specs(conn: sqlite3.Connection, n: int, seed: int) -> list[FilterSpec]:
    rng = random.Random(seed)
    themes = all_themes(conn)
    lo, hi = conn.execute("SELECT MIN(rating), MAX(rating) FROM puzzles").fetchone()
    openings = all_openings(conn)
    return [random_spec(rng, themes, lo, hi, openings) for _ in range(n)]


@pytest.fixture
def raw(fixture_puzzles_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{fixture_puzzles_db.as_posix()}?mode=ro", uri=True)
    yield conn
    conn.close()


def seed_history(services, raw: sqlite3.Connection) -> tuple[frozenset[str], frozenset[str]]:  # type: ignore[no-untyped-def]
    """Give a third of the puzzles a history (won; lost; won then lost; lost then won; lost twice)
    and return the (solved, missed) sets: solved = ever won, missed = latest attempt lost."""
    ids = [r[0] for r in raw.execute("SELECT id FROM puzzles ORDER BY id")]
    rng = random.Random(7)
    patterns = [[1], [0], [1, 0], [0, 1], [0, 0]]
    history = {pid: rng.choice(patterns) for pid in rng.sample(ids, len(ids) // 3)}
    with services.db.session() as conn:
        sid = conn.execute(
            "INSERT INTO sessions (started_at, mode, filters_json) VALUES ('2026-10-01', 'standard', '{}')"
        ).lastrowid
        for pid, results in history.items():
            for win in results:
                conn.execute(
                    "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at,"
                    " win, first_move_correct, line_correct, time_ms)"
                    " VALUES ('lichess', ?, ?, 'standard', 't', 't', ?, 0, 0, 1)",
                    (pid, sid, win),
                )
    solved = frozenset(p for p, r in history.items() if 1 in r)
    missed = frozenset(p for p, r in history.items() if r[-1] == 0)
    return solved, missed


@pytest.mark.parametrize("i", range(40))
def test_count_matches_oracle(services, raw: sqlite3.Connection, i: int) -> None:  # type: ignore[no-untyped-def]
    solved, missed = seed_history(services, raw)
    spec = random_specs(raw, 40, THEMES_SEED)[i]
    assert services.mixer.count(spec) == oracle_count(raw, spec, solved, missed), spec


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
    "no quality threshold": FilterSpec(min_popularity=None, min_plays=None),
    "strict quality": FilterSpec(min_popularity=95, min_plays=1000),
    "an opening family": FilterSpec(openings=("Sicilian_Defense",), min_popularity=None, min_plays=None),
    "an opening variation": FilterSpec(openings=("Italian_Game_Evans_Gambit",), min_popularity=None, min_plays=None),
    "an unknown opening": FilterSpec(openings=("No_Such_Opening",)),
    "only my misses": FilterSpec(only_my_misses=True),
    "include solved": FilterSpec(exclude_solved_here=False),
}


@pytest.mark.parametrize("name", EDGE_SPECS)
def test_edge_specs(services, raw: sqlite3.Connection, name: str) -> None:  # type: ignore[no-untyped-def]
    solved, missed = seed_history(services, raw)
    spec = EDGE_SPECS[name]
    assert services.mixer.count(spec) == oracle_count(raw, spec, solved, missed)


def test_edge_expectations(services) -> None:  # type: ignore[no-untyped-def]
    count = services.mixer.count
    assert count(EDGE_SPECS["zero matches"]) == 0
    assert count(EDGE_SPECS["all with never-co-occurring themes"]) == 0
    assert count(EDGE_SPECS["exclude overlaps include"]) == 0
    assert count(EDGE_SPECS["exclude unknown theme"]) == count(EDGE_SPECS["everything"])


def test_v02_edge_expectations(services, raw: sqlite3.Connection) -> None:  # type: ignore[no-untyped-def]
    count = services.mixer.count
    assert count(EDGE_SPECS["an unknown opening"]) == 0
    assert count(EDGE_SPECS["an opening family"]) > 0 and count(EDGE_SPECS["an opening variation"]) > 0
    assert count(EDGE_SPECS["no quality threshold"]) > count(EDGE_SPECS["everything"])  # the defaults remove some
    assert count(EDGE_SPECS["only my misses"]) == 0  # no history yet
    solved, missed = seed_history(services, raw)
    every = FilterSpec(min_popularity=None, min_plays=None, exclude_solved_here=False)
    assert count(dataclasses.replace(every, only_my_misses=True)) == len(missed)
    assert count(dataclasses.replace(every, exclude_solved_here=True)) == count(every) - len(solved)
    # Only my misses wins over Exclude solved: won-then-lost puzzles are misses.
    assert count(dataclasses.replace(every, exclude_solved_here=True, only_my_misses=True)) == len(missed)
