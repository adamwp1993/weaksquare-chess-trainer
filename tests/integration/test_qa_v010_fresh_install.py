"""QA v0.10 (qa/QA-v0.10.md, B7): on a fresh install, before the puzzle database is imported, the main page's
new theme-catalog call (App.tsx, v0.10) must not crash in the bridge and log a traceback at every launch."""

from __future__ import annotations

import logging

import pytest

from tests.helpers import build_api
from weaksquare import config
from weaksquare.adapters.db.migrate import migrate


@pytest.mark.xfail(strict=True, reason="v0.10-B7: get_theme_catalog crashes (no pz.theme_bits) before the import")
def test_qa_the_theme_catalog_before_the_puzzle_db_exists_is_not_a_crash(paths, clock, caplog) -> None:  # type: ignore[no-untyped-def]
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    assert not paths.puzzles_db.exists()
    api = build_api(paths, clock)
    with caplog.at_level(logging.ERROR, logger="weaksquare.bridge"):
        r = api.get_theme_catalog()
    assert not any("crashed" in rec.getMessage() for rec in caplog.records)
    assert r["ok"] or r["error"]["code"] != "internal", r
