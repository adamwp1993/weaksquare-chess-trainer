"""LichessDbSource: counts, samples and loads puzzles from the attached puzzles.db (`pz` schema).

Owns the FilterSpec -> SQL translation. Theme filters use the bitmask columns t0..t2 (see
puzzle_import.py); only mask columns that are non-zero are tested, so most filters touch one column.
Openings use the integer ids in `openings`; the history filters (FR-3.9) look up `attempts` in
user.db, which is the main schema of every connection (puzzles.db is attached as `pz`).
"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.repos.puzzle_import import BITS_PER_COLUMN, THEME_COLUMNS
from weaksquare.core.errors import StaleKeyError
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
# FR-3.9 (v0.3): your Lichess puzzle history, plus what this app has synced (the sync adds those).
PLAYED_IDS = "SELECT h.puzzle_id FROM lichess_history h"


def hidden_ids_sql(spec: FilterSpec) -> str | None:
    """The IDs the history filters hide (solved here and/or played on Lichess), as one subquery, or
    None. Counting and small-pool sampling subtract these instead of testing `id NOT IN (...)` per row:
    `id` isn't in the covering index, so a per-row test reads the whole table (4 s instead of 0.3 s)."""
    parts = []
    if spec.excludes_solved:
        parts.append(SOLVED_IDS)
    if spec.excludes_played:
        parts.append(PLAYED_IDS)
    return " UNION ".join(parts) if parts else None


def unhidden(spec: FilterSpec) -> FilterSpec:
    """The same filters without the hiding history filters (only my misses is kept)."""
    return dataclasses.replace(spec, exclude_solved_here=False, exclude_played_on_lichess=False)


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


def any_theme(themes: Sequence[str], bits: dict[str, int]) -> tuple[str, list[int]]:
    """SQL true when a puzzle has at least one of `themes`."""
    masks, _ = _masks(themes, bits)
    ors = [f"(p.{col} & ?)" for col, m in zip(COLS, masks, strict=True) if m]
    return ("(" + " | ".join(ors) + ") != 0" if ors else "0"), [m for m in masks if m]


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
            any_sql, any_params = any_theme(spec.themes, bits)
            parts.append(any_sql)
            params += any_params

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
    hidden = hidden_ids_sql(spec)
    if hidden:
        parts.append(f"p.id NOT IN ({hidden})")

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

    def key_map(self, ids: Sequence[str]) -> dict[str, int]:
        """Current key per puzzle ID, for Spaced repetition's queue of IDs (v0.5). Dropped IDs are missing."""
        out: dict[str, int] = {}
        ids = list(ids)
        with self._db.session() as conn:
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                q = f"SELECT id, n FROM pz.puzzles WHERE id IN ({', '.join('?' * len(chunk))})"
                out.update((r[0], r[1]) for r in conn.execute(q, chunk))
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

    def count_with_buckets(self, spec: FilterSpec) -> tuple[int, list[int]]:
        """For a ratio mix (FR-3.10): the union of the groups and each group's count, in one scan of
        the covering index (one count per group would take a scan each). Exclude solved is subtracted,
        as in `count`."""
        bits = self.theme_bits()
        conds = [any_theme(b.themes, bits) for b in spec.ratios]
        union_sql = "(" + " OR ".join(c[0] for c in conds) + ")"
        union_params = [p for c in conds for p in c[1]]
        # The union goes in WHERE, so only matching rows evaluate the per-group sums (~40% faster).
        select = ", ".join(["COUNT(*)"] + [f"SUM({c[0]})" for c in conds])
        select_params = [p for c in conds for p in c[1]]
        plain = dataclasses.replace(spec, themes=(), match="any", ratios=())
        hidden = hidden_ids_sql(spec)
        base = self.where(unhidden(plain))
        with self._db.session() as conn:
            row = conn.execute(
                f"SELECT {select} FROM pz.puzzles p WHERE {base.sql} AND {union_sql}",
                (*select_params, *base.params, *union_params),
            )
            totals = [int(x or 0) for x in row.fetchone()]
            if hidden:
                row = conn.execute(
                    f"SELECT {select} FROM pz.puzzles p WHERE p.id IN ({hidden}) AND {base.sql} AND {union_sql}",
                    (*select_params, *base.params, *union_params),
                )
                totals = [t - int(x or 0) for t, x in zip(totals, row.fetchone(), strict=True)]
        return totals[0], totals[1:]

    def count(self, spec: FilterSpec) -> int:
        """With ratios, the union of the groups (see count_with_buckets). Exclude solved (on by default) is counted by subtraction: `id NOT IN (…)` would make SQLite
        read every row of the table, because `id` isn't in the covering index (4 s instead of 0.3 s on
        the full export). So count without it, then subtract the solved puzzles that match, which the
        unique `id` index finds directly. Exclude played on Lichess (v0.3) joins the same subtraction."""
        if spec.ratios:
            return self.count_with_buckets(spec)[0]
        hidden = hidden_ids_sql(spec)
        with self._db.session() as conn:
            if hidden:
                base = self.where(unhidden(spec))
                total = conn.execute(f"SELECT COUNT(*) FROM pz.puzzles p WHERE {base.sql}", base.params).fetchone()[0]
                gone = conn.execute(
                    f"SELECT COUNT(*) FROM pz.puzzles p WHERE p.id IN ({hidden}) AND {base.sql}", base.params
                ).fetchone()[0]
                return int(total) - int(gone)
            where = self.where(spec)
            return int(conn.execute(f"SELECT COUNT(*) FROM pz.puzzles p WHERE {where.sql}", where.params).fetchone()[0])

    def has_puzzles(self, spec: FilterSpec) -> bool:
        """Does anything match? An existence check, not a count: it stops at the first match (depth
        ladder, v0.5-B2/B7). With Exclude solved/played, something matches when more rows match than the
        hidden ones that match (a short id lookup), checked with `LIMIT hidden + 1`."""
        hidden = hidden_ids_sql(spec)
        base = self.where(unhidden(spec) if hidden else spec)
        with self._db.session() as conn:
            gone = 0
            if hidden:
                gone = int(conn.execute(
                    f"SELECT COUNT(*) FROM pz.puzzles p WHERE p.id IN ({hidden}) AND {base.sql}", base.params
                ).fetchone()[0])  # fmt: skip
            found = conn.execute(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM pz.puzzles p WHERE {base.sql} LIMIT ?)", (*base.params, gone + 1)
            ).fetchone()[0]
        return int(found) > gone

    def count_level_and_above(self, spec: FilterSpec, level: int) -> tuple[int, int]:
        """Depth ladder (v0.5-B7): the count at `level` (4 = 4 or more) and how many puzzles are at higher
        levels, in one scan. With themes selected this costs about one count; a count plus an existence
        check above would scan the higher levels a second time when they're empty (e.g. Mate in 2).
        `spec.lengths` is ignored; Exclude solved/played are subtracted, as in `count`."""
        plain = dataclasses.replace(spec, lengths=(), order="random")
        hidden = hidden_ids_sql(plain)
        at = "p.length >= 4" if level >= 4 else f"p.length = {int(level)}"
        sums = f"SUM({at}), SUM(p.length > {int(level)})" if level < 4 else f"SUM({at}), 0"
        with self._db.session() as conn:
            base = self.where(unhidden(plain) if hidden else plain)
            cond = f"{base.sql} AND p.length >= {int(level)}"
            row = conn.execute(f"SELECT {sums} FROM pz.puzzles p WHERE {cond}", base.params).fetchone()
            here, above = int(row[0] or 0), int(row[1] or 0)
            if hidden:
                row = conn.execute(
                    f"SELECT {sums} FROM pz.puzzles p WHERE p.id IN ({hidden}) AND {cond}", base.params
                ).fetchone()
                here, above = here - int(row[0] or 0), above - int(row[1] or 0)
        return here, above

    def levels_with_puzzles(self, spec: FilterSpec, levels: Sequence[int]) -> list[int]:
        """Which depth-ladder levels (2, 3, 4 = 4 or more) have any puzzle under these filters."""
        return [lv for lv in levels if self.has_puzzles(dataclasses.replace(spec, lengths=(lv,), order="random"))]

    def _hidden_keys(self, conn: sqlite3.Connection, spec: FilterSpec, hidden: str) -> set[int]:
        """Keys of the hidden puzzles that would otherwise match (for sampling, like count)."""
        base = self.where(unhidden(spec))
        rows = conn.execute(f"SELECT p.n FROM pz.puzzles p WHERE p.id IN ({hidden}) AND {base.sql}", base.params)
        return {r[0] for r in rows}

    def sample_keys(
        self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int], match_count: int
    ) -> list[int]:
        """Up to `k` random matching puzzle keys not in `exclude` (plan decision 3)."""
        if k <= 0 or match_count <= 0:
            return []
        where = self.where(spec)
        with self._db.session() as conn:
            if match_count <= SMALL_POOL:
                hidden = hidden_ids_sql(spec)
                if hidden:  # the covering index, minus the hidden keys (see count)
                    base = self.where(unhidden(spec))
                    rows = conn.execute(f"SELECT p.n FROM pz.puzzles p WHERE {base.sql}", base.params)
                    skip = set(exclude) | self._hidden_keys(conn, spec, hidden)
                else:
                    rows = conn.execute(f"SELECT p.n FROM pz.puzzles p WHERE {where.sql}", where.params)
                    skip = set(exclude)
                return sample_random([r[0] for r in rows], k, rng, skip)
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

    def get(self, key: int, version: int | None = None) -> Puzzle | None:
        """The puzzle with key `key`. With `version`, raises StaleKeyError if puzzles.db was swapped
        since that version: keys don't survive a re-import (v0.2-B3). The check and the read happen
        in one session, which a swap can't interrupt, so a stale key can never return another puzzle."""
        with self._db.session() as conn:
            if version is not None and self.version() != version:
                raise StaleKeyError(version, self.version())
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
