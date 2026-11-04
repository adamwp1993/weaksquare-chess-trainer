"""user.db repository for your own puzzles (v0.8, FR-3.15): `custom_puzzles`, saved from Game Review
(origin manual, FR-11.16) or imported from a file (origin import, FR-10.46). Their attempts use the
`my:` puzzle source (ARCHITECTURE §3 decision 3)."""

from __future__ import annotations

import random
import sqlite3

from weaksquare.adapters.db.connection import Database
from weaksquare.core.filters import FilterSpec
from weaksquare.core.puzzle import NO_PREMOVE, NewCustomPuzzle, Puzzle, PuzzleRef
from weaksquare.core.queue import sample_random

_INSERT = (
    "INSERT INTO custom_puzzles (game_id, ply, fen, solution_uci, length, player_color, origin, set_label, name,"
    " strict, kind, severity, cp_loss, phase, time_class, game_date, created_at, themes, solve_as)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _values(p: NewCustomPuzzle, created_at: str) -> tuple[object, ...]:
    return (
        p.game_id, p.ply, p.fen, " ".join(p.solution), p.length, p.player_color, p.origin, p.set_label, p.name,
        int(p.strict), p.kind, p.severity, p.cp_loss, p.phase, p.time_class, p.game_date, created_at,
        " ".join(p.themes) or None, p.solve_as,
    )  # fmt: skip


class CustomPuzzlesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, p: NewCustomPuzzle, created_at: str) -> tuple[int, bool]:
        """(id, created). The unique indexes make a repeat (same game and ply, or the same imported set
        entry) return the existing puzzle instead of a second copy."""
        with self._db.transaction() as conn:
            try:
                cur = conn.execute(_INSERT, _values(p, created_at))
                return int(cur.lastrowid or 0), True
            except sqlite3.IntegrityError:
                if p.game_id is not None:
                    row = conn.execute(
                        "SELECT id FROM custom_puzzles WHERE game_id = ? AND ply = ?", (p.game_id, p.ply)
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT id FROM custom_puzzles WHERE origin = 'import' AND set_label IS ? AND fen = ?"
                        " AND solution_uci = ?",
                        (p.set_label, p.fen, " ".join(p.solution)),
                    ).fetchone()
                if row is None:
                    raise
                return int(row[0]), False

    def add_many(self, items: list[NewCustomPuzzle], created_at: str) -> int:
        """Insert a batch of imported puzzles in one transaction; duplicates are skipped. Returns how many
        were new."""
        added = 0
        with self._db.transaction() as conn:
            for p in items:
                cur = conn.execute(_INSERT.replace("INSERT INTO", "INSERT OR IGNORE INTO"), _values(p, created_at))
                added += cur.rowcount
        return added

    def saved_plies(self, game_id: int) -> set[int]:
        with self._db.session() as conn:
            rows = conn.execute("SELECT ply FROM custom_puzzles WHERE game_id = ?", (game_id,)).fetchall()
        return {int(r[0]) for r in rows if r[0] is not None}

    def at(self, game_id: int, ply: int) -> tuple[int, str, str] | None:
        """(id, origin, status) of the puzzle saved or made at this move, if any."""
        with self._db.session() as conn:
            r = conn.execute(
                "SELECT id, origin, status FROM custom_puzzles WHERE game_id = ? AND ply = ?", (game_id, ply)
            ).fetchone()
        return (int(r[0]), str(r[1]), str(r[2])) if r else None

    def coach_puzzles(self) -> list[tuple[int, int, int, str | None, str]]:
        """(id, game_id, ply, severity, status) of every puzzle the Coach made (FR-10.40)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT id, game_id, ply, severity, status FROM custom_puzzles WHERE origin = 'coach'"
                " AND game_id IS NOT NULL ORDER BY id"
            ).fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), r[3], str(r[4])) for r in rows]

    def set_status(self, ids: list[int], status: str) -> None:
        """active / archived (outside the severity level, FR-10.40) / hidden (you archived it, FR-10.44)."""
        with self._db.transaction() as conn:
            conn.executemany("UPDATE custom_puzzles SET status = ? WHERE id = ?", [(status, i) for i in ids])

    def untagged(self) -> list[tuple[int, str, tuple[str, ...], int | None, int | None]]:
        """(id, fen, solution, game_id, ply) of puzzles with no themes yet (the v0.10 backfill)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT id, fen, solution_uci, game_id, ply FROM custom_puzzles WHERE themes IS NULL ORDER BY id"
            ).fetchall()
        return [(int(r[0]), str(r[1]), tuple(str(r[2]).split()), r[3], r[4]) for r in rows]

    def set_themes(self, items: list[tuple[int, tuple[str, ...]]]) -> None:
        """Store themes; an empty tuple is stored as '' so the puzzle isn't tagged again."""
        with self._db.transaction() as conn:
            conn.executemany("UPDATE custom_puzzles SET themes = ? WHERE id = ?", [(" ".join(t), i) for i, t in items])

    def sets(self) -> list[tuple[str, int]]:
        """Imported set labels with their active puzzle counts, by label."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT set_label, COUNT(*) FROM custom_puzzles WHERE origin = 'import' AND status = 'active'"
                " AND set_label IS NOT NULL GROUP BY set_label ORDER BY set_label"
            ).fetchall()
        return [(str(r[0]), int(r[1])) for r in rows]


class RetryRepo:
    """Retry-mode results (FR-11.15): local only."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, game_id: int, ply: int, played_uci: str, found: bool, cp_loss: int | None, created_at: str) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO retry_attempts (game_id, ply, played_uci, found, cp_loss, created_at) VALUES (?,?,?,?,?,?)",
                (game_id, ply, played_uci, int(found), cp_loss, created_at),
            )
            return int(cur.lastrowid or 0)

    def get(self, retry_id: int) -> tuple[int, int, bool] | None:
        with self._db.session() as conn:
            r = conn.execute("SELECT game_id, ply, found FROM retry_attempts WHERE id = ?", (retry_id,)).fetchone()
        return (int(r[0]), int(r[1]), bool(r[2])) if r else None

    def totals(self) -> tuple[int, int]:
        """(found, tried) over every retry."""
        with self._db.session() as conn:
            r = conn.execute("SELECT COALESCE(SUM(found), 0), COUNT(*) FROM retry_attempts").fetchone()
        return int(r[0]), int(r[1])


# FR-3.9 for your own puzzles (v0.8): the same rules as Lichess puzzles, on the `my` source. Danger
# spotting never serves them, and "played on Lichess" doesn't apply.
MY_SOLVED = (
    "SELECT CAST(a.puzzle_id AS INTEGER) FROM attempts a WHERE a.puzzle_source = 'my' AND a.win = 1"
    " AND a.mode != 'danger_spotting'"
)
MY_MISSED = (
    "SELECT CAST(a.puzzle_id AS INTEGER) FROM attempts a WHERE a.puzzle_source = 'my' AND a.win = 0"
    " AND a.id = (SELECT MAX(b.id) FROM attempts b WHERE b.puzzle_source = 'my' AND b.puzzle_id = a.puzzle_id"
    " AND b.mode != 'danger_spotting')"
)


class CustomPuzzleSource:
    """`PuzzleSource` for the My-puzzles pool (FR-3.15). Keys are `custom_puzzles.id`; only active
    puzzles are served. The pool is small (your own puzzles), so sampling reads the matching ids."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def where(spec: FilterSpec) -> tuple[str, list[object]]:
        parts = ["c.status = 'active'"]
        params: list[object] = []
        if spec.lengths and not spec.all_lengths:
            short = [n for n in spec.lengths if n < 4]
            ors = []
            if short:
                ors.append(f"c.length IN ({','.join('?' * len(short))})")
                params.extend(short)
            if 4 in spec.lengths:
                ors.append("c.length >= 4")
            parts.append("(" + " OR ".join(ors) + ")")
        if spec.side != "either":
            parts.append("c.player_color = ?")
            params.append(spec.side)
        for col, values in (
            ("origin", spec.my_origins),
            ("set_label", spec.my_sets),
            ("kind", spec.my_kinds),
            ("phase", spec.my_phases),
            ("time_class", spec.my_time_classes),
        ):
            if values:
                parts.append(f"c.{col} IN ({','.join('?' * len(values))})")
                params.extend(values)
        if spec.excludes_solved:
            parts.append(f"c.id NOT IN ({MY_SOLVED})")
        if spec.only_my_misses:
            parts.append(f"c.id IN ({MY_MISSED})")
        return " AND ".join(parts), params

    def count(self, spec: FilterSpec) -> int:
        sql, params = self.where(spec)
        with self._db.session() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM custom_puzzles c WHERE {sql}", params).fetchone()[0])

    def sample_keys(self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int]) -> list[int]:
        if k <= 0:
            return []
        sql, params = self.where(spec)
        with self._db.session() as conn:
            ids = [
                int(r[0]) for r in conn.execute(f"SELECT c.id FROM custom_puzzles c WHERE {sql} ORDER BY c.id", params)
            ]
        return sample_random(ids, k, rng, exclude)

    def get(self, pid: int) -> Puzzle | None:
        with self._db.session() as conn:
            r = conn.execute(
                "SELECT id, fen, solution_uci, themes, strict, solve_as, game_id, ply FROM custom_puzzles"
                " WHERE id = ? AND status = 'active'",
                (pid,),
            ).fetchone()
        if r is None:
            return None
        return Puzzle(
            ref=PuzzleRef("my", str(r[0])),
            fen=r[1],
            moves=(NO_PREMOVE, *r[2].split()),
            rating=0,
            themes=tuple((r[3] or "").split()),
            game_url="",
            opening_tags=(),
            tolerance=not bool(r[4]),
            solve_as_opponent=r[5] == "opponent",
            game_id=r[6],
            game_ply=r[7],
        )

    def active(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        out: set[int] = set()
        with self._db.session() as conn:
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                rows = conn.execute(
                    f"SELECT id FROM custom_puzzles WHERE status = 'active' AND id IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
                out.update(int(r[0]) for r in rows)
        return out
