"""user.db repositories for the opening trainer (v0.13, REQUIREMENTS §18): the book, your repertoire and the
engine cache. Notes, sources and attempts arrive with the steps that use them."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.engine import EngineLine
from weaksquare.core.opening_sources import WikiPage
from weaksquare.core.openings import MOVE_NUMBER, BookLine
from weaksquare.core.repertoire import Edge, NewMove


class OpeningBookRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def count(self) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM opening_book").fetchone()[0])

    def replace(self, lines: Sequence[BookLine]) -> None:
        """Swap the whole book in one transaction, so a failed import leaves the old one working."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM opening_book_positions")
            conn.execute("DELETE FROM opening_book")
            for ln in lines:
                cur = conn.execute(
                    "INSERT INTO opening_book (eco, name, family, pgn, moves_uci, final_key) VALUES (?,?,?,?,?,?)",
                    (ln.eco, ln.name, ln.family, ln.pgn, " ".join(ln.moves), ln.final_key),
                )
                line_id = int(cur.lastrowid or 0)
                conn.executemany(
                    "INSERT INTO opening_book_positions (line_id, ply, position_key, move_uci) VALUES (?,?,?,?)",
                    [(line_id, i, key, ln.moves[i] if i < len(ln.moves) else "") for i, key in enumerate(ln.keys)],
                )

    def lines(self) -> list[BookLine]:
        with self._db.session() as conn:
            positions: dict[int, list[str]] = {}
            for line_id, key in conn.execute(
                "SELECT line_id, position_key FROM opening_book_positions ORDER BY line_id, ply"
            ):
                positions.setdefault(int(line_id), []).append(str(key))
            rows = conn.execute("SELECT id, eco, name, pgn, moves_uci FROM opening_book ORDER BY id").fetchall()
        out: list[BookLine] = []
        for r in rows:
            sans = tuple(t for t in str(r[3]).split() if not MOVE_NUMBER.match(t))
            out.append(
                BookLine(str(r[1]), str(r[2]), str(r[3]), tuple(str(r[4]).split()), sans, tuple(positions[int(r[0])]), int(r[0]))
            )  # fmt: skip
        return out


@dataclass(frozen=True)
class RepertoireOpening:
    id: int
    color: str
    name: str
    eco: str
    root_key: str
    root_moves: tuple[str, ...]
    created_at: str


class RepertoireRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def edges(self, color: str) -> list[Edge]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT position_key, move_uci, san, source, is_main, sort_order, id FROM repertoire_nodes"
                " WHERE color = ? ORDER BY sort_order, id",
                (color,),
            ).fetchall()
        return [Edge(str(r[0]), str(r[1]), str(r[2]), str(r[3]), bool(r[4]), int(r[5]), int(r[6])) for r in rows]

    def add_moves(self, color: str, moves: Iterable[NewMove], created_at: str) -> int:
        """Add moves you don't have yet. A stored move keeps its source and place. The first move stored at a
        position becomes its main one. Returns how many were new."""
        added = 0
        with self._db.transaction() as conn:
            for m in moves:
                has_main = conn.execute(
                    "SELECT 1 FROM repertoire_nodes WHERE color = ? AND position_key = ? AND is_main = 1",
                    (color, m.position_key),
                ).fetchone()
                order = conn.execute(
                    "SELECT COALESCE(MAX(sort_order) + 1, 0) FROM repertoire_nodes WHERE color = ? AND position_key = ?",
                    (color, m.position_key),
                ).fetchone()[0]
                cur = conn.execute(
                    "INSERT OR IGNORE INTO repertoire_nodes"
                    " (color, position_key, move_uci, san, source, is_main, sort_order, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (color, m.position_key, m.move_uci, m.san, m.source, 0 if has_main else 1, order, created_at),
                )
                added += cur.rowcount
        return added

    def delete(self, color: str, edges: Iterable[Edge]) -> None:
        with self._db.transaction() as conn:
            conn.executemany(
                "DELETE FROM repertoire_nodes WHERE color = ? AND position_key = ? AND move_uci = ?",
                [(color, e.position_key, e.move_uci) for e in edges],
            )

    def set_main(self, color: str, position_key: str, move_uci: str) -> bool:
        with self._db.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM repertoire_nodes WHERE color = ? AND position_key = ? AND move_uci = ?",
                (color, position_key, move_uci),
            ).fetchone()
            if not found:
                return False
            conn.execute(
                "UPDATE repertoire_nodes SET is_main = (move_uci = ?) WHERE color = ? AND position_key = ?",
                (move_uci, color, position_key),
            )
            return True

    def set_order(self, color: str, position_key: str, order: Sequence[str]) -> None:
        with self._db.transaction() as conn:
            conn.executemany(
                "UPDATE repertoire_nodes SET sort_order = ? WHERE color = ? AND position_key = ? AND move_uci = ?",
                [(i, color, position_key, uci) for i, uci in enumerate(order)],
            )

    def openings(self, color: str | None = None) -> list[RepertoireOpening]:
        sql = "SELECT id, color, name, eco, root_key, root_moves, created_at FROM repertoire_openings"
        args: tuple[str, ...] = ()
        if color is not None:
            sql += " WHERE color = ?"
            args = (color,)
        with self._db.session() as conn:
            rows = conn.execute(sql + " ORDER BY name, id", args).fetchall()
        return [
            RepertoireOpening(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), tuple(str(r[5]).split()), str(r[6]))
            for r in rows
        ]  # fmt: skip

    def add_opening(
        self, color: str, name: str, eco: str, root_key: str, root_moves: Sequence[str], created_at: str
    ) -> None:
        with self._db.session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO repertoire_openings (color, name, eco, root_key, root_moves, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (color, name, eco, root_key, " ".join(root_moves), created_at),
            )

    def delete_opening(self, opening_id: int) -> None:
        with self._db.session() as conn:
            conn.execute("DELETE FROM repertoire_openings WHERE id = ?", (opening_id,))


class OpeningEngineCacheRepo:
    """Engine lines by position, think time and engine (FR-12.8). Lines stay White-relative, as the engine
    gave them, so one stored result serves either side's view."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, position_key: str, think_ms: int, multipv: int, engine: str) -> list[EngineLine] | None:
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT lines_json FROM opening_engine_cache WHERE position_key = ? AND think_ms = ? AND multipv = ?"
                " AND engine = ?",
                (position_key, think_ms, multipv, engine),
            ).fetchone()
        if row is None:
            return None
        return [EngineLine(d["cp"], d["mate"], tuple(d["pv"])) for d in json.loads(row[0])]

    def put(
        self, position_key: str, think_ms: int, multipv: int, engine: str, lines: Sequence[EngineLine], created_at: str
    ) -> None:
        body = json.dumps([{"cp": x.cp, "mate": x.mate, "pv": list(x.pv)} for x in lines], separators=(",", ":"))
        with self._db.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO opening_engine_cache"
                " (position_key, think_ms, multipv, engine, lines_json, created_at) VALUES (?,?,?,?,?,?)",
                (position_key, think_ms, multipv, engine, body, created_at),
            )


class ExplorerCacheRepo:
    """Explorer answers as they came (FR-12.2). They're checked against the position each time they're read."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, position_key: str, params: str) -> tuple[Any, str] | None:
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT body_json, fetched_at FROM explorer_cache WHERE position_key = ? AND params = ?",
                (position_key, params),
            ).fetchone()
        return (json.loads(row[0]), str(row[1])) if row is not None else None

    def put(self, position_key: str, params: str, body: Any, fetched_at: str) -> None:
        with self._db.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO explorer_cache (position_key, params, body_json, fetched_at) VALUES (?,?,?,?)",
                (position_key, params, json.dumps(body, separators=(",", ":")), fetched_at),
            )


class WikibooksPagesRepo:
    """Wikibooks text kept on your PC (FR-12.15). A missing page is remembered too, so it isn't asked for again."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, title: str) -> tuple[WikiPage, str] | None:
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT title, status, revision_id, body, fetched_at FROM wikibooks_pages WHERE title = ?", (title,)
            ).fetchone()
        if row is None:
            return None
        return WikiPage(str(row[0]), str(row[1]), row[2], str(row[3])), str(row[4])

    def put(self, page: WikiPage, fetched_at: str) -> None:
        with self._db.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO wikibooks_pages (title, revision_id, body, status, fetched_at) VALUES (?,?,?,?,?)",
                (page.title, page.revision_id, page.text, page.status, fetched_at),
            )


_NOTE_COLS = (
    "position_key, move_uci, kind, provider, model, prompt_version, body_json, sources_json, input_tokens,"
    " output_tokens, cost_usd, created_at"
)


class OpeningNotesRepo:
    """Overviews and explanations (FR-12.7). `replace` is also Regenerate: other models' copies of a note go too."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _row(r: Any) -> Any:
        from weaksquare.services.opening_notes import NoteRow

        return NoteRow(
            str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), int(r[5]), str(r[6]), str(r[7]), int(r[8]), int(r[9]),
            float(r[10]), str(r[11]),
        )  # fmt: skip

    def get(self, key: str, move: str, kind: str, provider: str, model: str, version: int) -> Any | None:
        with self._db.session() as conn:
            row = conn.execute(
                f"SELECT {_NOTE_COLS} FROM opening_notes WHERE position_key = ? AND move_uci = ? AND kind = ?"
                " AND provider = ? AND model = ? AND prompt_version = ?",
                (key, move, kind, provider, model, version),
            ).fetchone()
        return self._row(row) if row is not None else None

    def latest(self, key: str, move: str, kind: str) -> Any | None:
        with self._db.session() as conn:
            row = conn.execute(
                f"SELECT {_NOTE_COLS} FROM opening_notes WHERE position_key = ? AND move_uci = ? AND kind = ?"
                " ORDER BY id DESC LIMIT 1",
                (key, move, kind),
            ).fetchone()
        return self._row(row) if row is not None else None

    def replace(self, row: Any) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM opening_notes WHERE position_key = ? AND move_uci = ? AND kind = ?",
                (row.position_key, row.move_uci, row.kind),
            )
            conn.execute(
                f"INSERT INTO opening_notes ({_NOTE_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row.position_key, row.move_uci, row.kind, row.provider, row.model, row.prompt_version, row.body_json,
                    row.sources_json, row.input_tokens, row.output_tokens, row.cost_usd, row.created_at,
                ),
            )  # fmt: skip

    def for_positions(self, keys: Sequence[str]) -> list[Any]:
        out: list[Any] = []
        with self._db.session() as conn:
            for i in range(0, len(keys), 500):
                part = keys[i : i + 500]
                marks = ",".join("?" * len(part))
                out.extend(
                    self._row(r)
                    for r in conn.execute(
                        f"SELECT {_NOTE_COLS} FROM opening_notes WHERE position_key IN ({marks}) ORDER BY id", part
                    )
                )
        return out

    def delete_positions(self, keys: Sequence[str]) -> int:
        gone = 0
        with self._db.transaction() as conn:
            for i in range(0, len(keys), 500):
                part = keys[i : i + 500]
                marks = ",".join("?" * len(part))
                gone += conn.execute(f"DELETE FROM opening_notes WHERE position_key IN ({marks})", part).rowcount
        return gone
