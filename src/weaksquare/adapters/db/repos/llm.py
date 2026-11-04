"""user.db repositories for the LLM layer (v0.7): the price table, the usage log and the Explain cache."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from weaksquare.adapters.db.connection import Database
from weaksquare.core.llm.defaults import PriceRow

_PRICE_COLS = (
    "provider, model, input_per_m, output_per_m, long_ctx_threshold, long_input_per_m, long_output_per_m, as_of"
)


@dataclass(frozen=True)
class CachedResult:
    response_json: str
    input_tokens: int
    output_tokens: int


def _price(r: sqlite3.Row) -> PriceRow:
    return PriceRow(
        r["provider"], r["model"], float(r["input_per_m"]), float(r["output_per_m"]), r["long_ctx_threshold"],
        r["long_input_per_m"], r["long_output_per_m"], r["as_of"],
    )  # fmt: skip


def _values(p: PriceRow) -> tuple[object, ...]:
    return (p.provider, p.model, p.input_per_m, p.output_per_m, p.long_ctx_threshold, p.long_input_per_m,
            p.long_output_per_m, p.as_of)  # fmt: skip


class LlmPricesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def all(self) -> list[PriceRow]:
        with self._db.session() as conn:
            rows = conn.execute(f"SELECT {_PRICE_COLS} FROM llm_prices ORDER BY provider, input_per_m, model")
            return [_price(r) for r in rows.fetchall()]

    def get(self, provider: str, model: str) -> PriceRow | None:
        with self._db.session() as conn:
            r = conn.execute(
                f"SELECT {_PRICE_COLS} FROM llm_prices WHERE provider = ? AND model = ?", (provider, model)
            ).fetchone()
        return _price(r) if r else None

    def upsert(self, p: PriceRow) -> None:
        with self._db.session() as conn:
            conn.execute(
                f"INSERT INTO llm_prices ({_PRICE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(provider, model) DO UPDATE SET input_per_m = excluded.input_per_m,"
                " output_per_m = excluded.output_per_m, long_ctx_threshold = excluded.long_ctx_threshold,"
                " long_input_per_m = excluded.long_input_per_m, long_output_per_m = excluded.long_output_per_m,"
                " as_of = excluded.as_of",
                _values(p),
            )

    def insert_missing(self, rows: tuple[PriceRow, ...]) -> int:
        """The seed: add the rows that aren't there and never change one that is. Returns how many were added."""
        added = 0
        with self._db.session() as conn:
            for p in rows:
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO llm_prices ({_PRICE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", _values(p)
                )
                added += cur.rowcount
        return added

    def delete(self, provider: str, model: str) -> bool:
        with self._db.session() as conn:
            cur = conn.execute("DELETE FROM llm_prices WHERE provider = ? AND model = ?", (provider, model))
            return cur.rowcount > 0


class LlmUsageRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(
        self, ts: str, local_month: str, feature: str, provider: str, model: str, input_tokens: int,
        output_tokens: int, cost_usd: float, status: str,
    ) -> int:  # fmt: skip
        with self._db.session() as conn:
            cur = conn.execute(
                "INSERT INTO llm_usage (ts, local_month, feature, provider, model, input_tokens, output_tokens,"
                " cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, local_month, feature, provider, model, input_tokens, output_tokens, cost_usd, status),
            )
            return int(cur.lastrowid or 0)

    def spent_in(self, local_month: str) -> float:
        """The total cost of the requests made in `local_month` (YYYY-MM)."""
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage WHERE local_month = ?", (local_month,)
            ).fetchone()
        return float(row[0])

    def spent_by_feature(self, local_month: str) -> dict[str, float]:
        """This month's spend per feature (FR-1.15): {feature: USD}, only features with requests."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT feature, SUM(cost_usd) FROM llm_usage WHERE local_month = ? GROUP BY feature", (local_month,)
            ).fetchall()
        return {str(r[0]): float(r[1]) for r in rows}

    def count(self) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0])


class LlmCacheRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str) -> CachedResult | None:
        with self._db.session() as conn:
            r = conn.execute(
                "SELECT response_json, input_tokens, output_tokens FROM llm_cache WHERE key = ?", (key,)
            ).fetchone()
        return CachedResult(r[0], int(r[1]), int(r[2])) if r else None

    def put(
        self, key: str, provider: str, model: str, response_json: str, input_tokens: int, output_tokens: int,
        created_at: str,
    ) -> None:  # fmt: skip
        with self._db.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, provider, model, response_json, input_tokens,"
                " output_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, provider, model, response_json, input_tokens, output_tokens, created_at),
            )
