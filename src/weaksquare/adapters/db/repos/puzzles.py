"""LichessDbSource: counts, samples and loads puzzles from the attached puzzles.db (`pz` schema).

Owns the FilterSpec -> SQL translation. Theme filters use the bitmask columns t0..t2 (see
puzzle_import.py); only mask columns that are non-zero are tested, so most filters touch one column.
Openings use the integer ids in `openings`; the history filters (FR-3.9) look up `attempts` in
user.db, which is the main schema of every connection (puzzles.db is attached as `pz`).
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.repos.puzzle_import import BITS_PER_COLUMN, THEME_COLUMNS
from weaksquare.core.filters import FilterSpec
from weaksquare.core.puzzle import Puzzle, PuzzleRef
from weaksquare.core.queue import SMALL_POOL, draw_batch_size, random_draws, sample_random

COLS = ("t0", "t1", "t2")


@dataclass(frozen=True)
class Where:
    sql: str
    params: tuple[int, ...]


# FR-3.9. Only Lichess puzzles live in puzzles.db; the `win` index makes both lookups cheap.
SOLVED_IDS = "SELECT a.puzzle_id FROM attempts a WHERE a.puzzle_source = 'lichess' AND a.win = 1"
MISSED_IDS = (
    "SELECT a.puzzle_id FROM attempts a WHERE a.puzzle_source = 'lichess' AND a.win = 0"
    " AND a.id = (SELECT MAX(b.id) FROM attempts b WHERE b.puzzle_source = 'lichess' AND b.puzzle_id = a.puzzle_id)"
)


def _masks(themes: Sequence[str], bits: dict[str, int]) -> tuple[list[int], list[str]]:
    masks = [0] * THEME_COLUMNS
    unknown = []
    for t in themes:
        b = bits.get(t)
        if b is None:
            unknown.append(t)
        else:
            masks[b // BITS_PER_COLUMN] |= 1 << (b % BITS_PER_COLUMN)
    return masks, unknown


def build_where(spec: FilterSpec, bits: dict[str, int], openings: dict[str, int] | None = None) -> Where:
    """SQL condition over `p` (pz.puzzles) for a validated FilterSpec. With ratios, pass one
    bucket's spec (`spec.bucket(i)`): the buckets' themes aren't combined here."""
    parts: list[str] = []
    params: list[int] = []

    parts.append("p.rating BETWEEN ? AND ?")
    params += [
        spec.rating_min if spec.rating_min is not None else 0,
        spec.rating_max if spec.rating_max is not None else 10_000,
    ]

    if not spec.all_lengths:
        exact = sorted(n for n in spec.lengths if n < 4)
        terms = []
        if exact:
            terms.append(f"p.length IN ({', '.join('?' * len(exact))})")
            params += exact
        if 4 in spec.lengths:
            terms.append("p.length >= 4")
        parts.append("(" + " OR ".join(terms) + ")")

    if spec.side != "either":
        parts.append("p.player_color = ?")
        params.append(0 if spec.side == "white" else 1)

    if spec.themes:
        masks, unknown = _masks(spec.themes, bits)
        if spec.match == "all":
            if unknown:
                parts.append("0")  # a theme no puzzle has: nothing can have all of them
            for col, m in zip(COLS, masks, strict=True):
                if m:
                    parts.append(f"(p.{col} & ?) = ?")
                    params += [m, m]
        else:
            ors = [f"(p.{col} & ?)" for col, m in zip(COLS, masks, strict=True) if m]
            params += [m for m in masks if m]
            parts.append("(" + " | ".join(ors) + ") != 0" if ors else "0")

    if spec.exclude_themes:
        masks, _ = _masks(spec.exclude_themes, bits)  # excluding a theme no puzzle has excludes nothing
        for col, m in zip(COLS, masks, strict=True):
            if m:
                parts.append(f"(p.{col} & ?) = 0")
                params.append(m)

    if spec.min_popularity is not None:
        parts.append("p.popularity >= ?")
        params.append(spec.min_popularity)
    if spec.min_plays is not None:
        parts.append("p.nb_plays >= ?")
        params.append(spec.min_plays)

    if spec.openings:
        known = openings or {}
        ids = sorted({known[o] for o in spec.openings if o in known})
        if not ids:
            parts.append("0")  # openings this database doesn't have
        else:
            marks = ", ".join("?" * len(ids))
            parts.append(f"(p.opening_family IN ({marks}) OR p.opening_variation IN ({marks}))")
            params += ids + ids

    if spec.only_my_misses:
        parts.append(f"p.id IN ({MISSED_IDS})")
    elif spec.excludes_solved:
        parts.append(f"p.id NOT IN ({SOLVED_IDS})")

    return Where(" AND ".join(parts), tuple(params))


class LichessDbSource:
    """PuzzleSource for the Lichess database. Puzzle keys are the dense integer `n`."""

    source = "lichess"

    def __init__(self, db: Database) -> None:
        self._db = db

    def version(self) -> int:
        """Changes whenever puzzles.db is replaced by an import: puzzle keys don't survive that."""
        return self._db.puzzles_generation

    def keys_for_ids(self, ids: Sequence[str]) -> set[int]:
        """Current keys of these puzzle IDs (IDs a newer export dropped are simply missing)."""
        out: set[int] = set()
        ids = list(ids)
        with self._db.session() as conn:
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                q = f"SELECT n FROM pz.puzzles WHERE id IN ({', '.join('?' * len(chunk))})"
                out.update(r[0] for r in conn.execute(q, chunk))
        return out

    def theme_bits(self) -> dict[str, int]:
        with self._db.session() as conn:
            return {r["theme"]: r["bit"] for r in conn.execute("SELECT theme, bit FROM pz.theme_bits")}

    def opening_ids(self) -> dict[str, int]:
        with self._db.session() as conn:
            return {r["tag"]: r["id"] for r in conn.execute("SELECT tag, id FROM pz.openings")}

    def where(self, spec: FilterSpec) -> Where:
        return build_where(spec, self.theme_bits(), self.opening_ids() if spec.openings else None)

    def openings(self) -> list[tuple[str, str | None, int]]:
        """(tag, family tag or None, puzzle count) for every opening in the database."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT o.tag, f.tag AS family, o.count FROM pz.openings o LEFT JOIN pz.openings f ON f.id = o.family_id"
            ).fetchall()
        return [(r["tag"], r["family"], r["count"]) for r in rows]

    def count(self, spec: FilterSpec) -> int:
        where = self.where(spec)
        with self._db.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM pz.puzzles p WHERE {where.sql}", where.params).fetchone()[0])

    def sample_keys(
        self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int], match_count: int
    ) -> list[int]:
        """Up to `k` random matching puzzle keys not in `exclude` (plan decision 3)."""
        if k <= 0 or match_count <= 0:
            return []
        where = self.where(spec)
        with self._db.session() as conn:
            if match_count <= SMALL_POOL:
                keys = [r[0] for r in conn.execute(f"SELECT p.n FROM pz.puzzles p WHERE {where.sql}", where.params)]
                return sample_random(keys, k, rng, exclude)
            max_key = int(conn.execute("SELECT MAX(n) FROM pz.puzzles").fetchone()[0])
            chosen: list[int] = []
            seen = set(exclude)
            for _ in range(50):  # each round expects to finish; the cap only guards against bad luck
                draws = [
                    d
                    for d in dict.fromkeys(
                        random_draws(max_key, draw_batch_size(k - len(chosen), match_count, max_key), rng)
                    )
                    if d not in seen
                ]
                if draws:
                    placeholders = ", ".join("?" * len(draws))
                    rows = conn.execute(
                        f"SELECT p.n FROM pz.puzzles p WHERE p.n IN ({placeholders}) AND {where.sql}",
                        (*draws, *where.params),
                    )
                    hits = {r[0] for r in rows}
                    for d in draws:  # keep the rng's order, so the result is deterministic
                        seen.add(d)
                        if d in hits:
                            chosen.append(d)
                            if len(chosen) == k:
                                return chosen
            return chosen

    def get(self, key: int) -> Puzzle | None:
        with self._db.session() as conn:
            r = conn.execute(
                "SELECT id, fen, moves, rating, themes, game_url, opening_tags FROM pz.puzzles WHERE n = ?", (key,)
            ).fetchone()
        if r is None:
            return None
        return Puzzle(
            ref=PuzzleRef("lichess", r["id"]),
            fen=r["fen"],
            moves=tuple(r["moves"].split()),
            rating=r["rating"],
            themes=tuple(r["themes"].split()),
            game_url=r["game_url"],
            opening_tags=tuple(r["opening_tags"].split()),
        )

    def describe(self, keys: Sequence[int]) -> dict[int, tuple[int, tuple[str, ...]]]:
        """(rating, themes) per key, for ordering a queue (FR-3.11)."""
        out: dict[int, tuple[int, tuple[str, ...]]] = {}
        keys = list(keys)
        with self._db.session() as conn:
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                rows = conn.execute(
                    f"SELECT n, rating, themes FROM pz.puzzles WHERE n IN ({', '.join('?' * len(chunk))})", chunk
                )
                out.update((r["n"], (r["rating"], tuple(r["themes"].split()))) for r in rows)
        return out

    def theme_counts(self) -> dict[str, int]:
        with self._db.session() as conn:
            return {r["theme"]: r["count"] for r in conn.execute("SELECT theme, count FROM pz.theme_bits")}
