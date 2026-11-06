"""user.db schema v6 (v0.7): the llm_prices, llm_usage and llm_cache tables."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from weaksquare.adapters.db.migrate import load_migrations, migrate
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

USER = MIGRATIONS_DIR / "user"


def test_v5_database_gains_empty_llm_tables_and_keeps_its_data(tmp_path: Path, clock: FixedClock) -> None:
    folder = tmp_path / "v5"
    folder.mkdir()
    for m in load_migrations(USER)[:5]:
        shutil.copy(m.path, folder / m.path.name)
    db = tmp_path / "user.db"
    migrate(db, folder, clock)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('ui.coordinates', 'false')")
    conn.commit()
    conn.close()

    result = migrate(db, USER, clock, tmp_path / "backups")
    assert result.from_version == 5 and result.to_version >= 6  # later versions add migrations on top
    assert result.backup is not None  # NFR-3

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT value FROM settings WHERE key = 'ui.coordinates'").fetchone() == ("false",)
    cols = {
        t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in ("llm_prices", "llm_usage", "llm_cache")
    }
    assert cols["llm_prices"] == [
        "provider", "model", "input_per_m", "output_per_m", "long_ctx_threshold", "long_input_per_m",
        "long_output_per_m", "as_of",
    ]  # fmt: skip
    assert cols["llm_usage"] == [
        "id",
        "ts",
        "local_month",
        "feature",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "status",
        "duration_ms",  # v0.13, FR-12.7b
    ]
    assert cols["llm_cache"] == [
        "key",
        "provider",
        "model",
        "response_json",
        "input_tokens",
        "output_tokens",
        "created_at",
    ]
    for t in cols:  # the migration seeds nothing: the app seeds prices from core/llm/defaults.py
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone() == (0,)
    conn.close()


def test_the_migration_file_names_no_model() -> None:
    """Model names live only in core/llm/defaults.py (CLAUDE.md, FR-1.3)."""
    sql = (USER / "0006_llm.sql").read_text(encoding="utf-8").lower()
    assert "claude-" not in sql and "gpt-" not in sql
