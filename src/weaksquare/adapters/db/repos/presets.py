"""Named filter sets in user.db (FR-3.13). Rows are stored as JSON exactly as saved; validation is
the service's job, and a stored row is never rewritten behind your back."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database


@dataclass(frozen=True)
class PresetRow:
    name: str
    filters: Any  # parsed JSON, not yet validated (None if the stored text isn't JSON)
    created_at: str
    updated_at: str


class PresetsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _row(r: Any) -> PresetRow:
        try:
            filters = json.loads(r["filters_json"])
        except ValueError:
            filters = None
        return PresetRow(r["name"], filters, r["created_at"], r["updated_at"])

    def list(self) -> list[PresetRow]:
        with self._db.session() as conn:
            rows = conn.execute("SELECT * FROM presets ORDER BY name_key").fetchall()
        return [self._row(r) for r in rows]

    def find(self, name: str) -> PresetRow | None:
        """By name, ignoring case."""
        with self._db.session() as conn:
            r = conn.execute("SELECT * FROM presets WHERE name_key = ?", (name.casefold(),)).fetchone()
        return self._row(r) if r else None

    def upsert(self, name: str, filters: dict[str, Any], now: str) -> None:
        """Insert, or replace the preset with the same name ignoring case (taking the new spelling)."""
        with self._db.session() as conn:
            conn.execute(
                "INSERT INTO presets (name, name_key, filters_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(name_key) DO UPDATE SET name = excluded.name, filters_json = excluded.filters_json,"
                " updated_at = excluded.updated_at",
                (name, name.casefold(), json.dumps(filters), now, now),
            )

    def rename(self, old: str, new: str, now: str) -> bool:
        with self._db.session() as conn:
            cur = conn.execute(
                "UPDATE presets SET name = ?, name_key = ?, updated_at = ? WHERE name_key = ?",
                (new, new.casefold(), now, old.casefold()),
            )
            return cur.rowcount == 1

    def delete(self, name: str) -> bool:
        with self._db.session() as conn:
            return conn.execute("DELETE FROM presets WHERE name_key = ?", (name.casefold(),)).rowcount == 1
