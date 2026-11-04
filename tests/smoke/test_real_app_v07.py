"""v0.7 in the real app (WebView2 over CDP), on the fixture DB and a temp data folder: Settings → AI
explanations opens with nothing pre-selected, the price table is seeded from the defaults module, and
without a key there's no spend indicator and no Explain button. No key is ever saved here: the real app
would write it to Credential Manager (its per-folder test entry), and smoke tests never touch secrets."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke


def test_ai_settings_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            assert page.get_by_test_id("spend-indicator").count() == 0  # FR-1.10: only with a provider and key
            page.get_by_test_id("gear").click()
            section = page.get_by_test_id("settings-ai")
            section.scroll_into_view_if_needed()
            assert section.get_by_test_id("ai-provider").input_value() == "None"
            assert section.get_by_test_id("price-row").count() == 8  # seeded from core/llm/defaults.py
            section.get_by_test_id("ai-provider").click()
            page.get_by_role("option", name="Anthropic").click()
            model = section.get_by_test_id("ai-model")
            model.wait_for()
            assert model.input_value() == ""  # nothing pre-selected (Adam, v0.7 planning)
            assert section.get_by_test_id("ai-key-test").is_disabled()  # no key saved
            settings = page.evaluate("window.pywebview.api.get_llm_settings()")
            assert settings["ok"] and settings["data"]["provider"] == "anthropic"
            assert settings["data"]["spend"]["configured"] is False
            page.keyboard.press("Escape")
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=30_000)
            assert page.get_by_test_id("explain-button").count() == 0  # FR-8.1: no key, no button
    finally:
        app.close()
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM llm_prices").fetchone() == (8,)
        assert conn.execute("SELECT value FROM settings WHERE key = 'llm.provider'").fetchone() == ('"anthropic"',)
        assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone() == (0,)
    finally:
        conn.close()
