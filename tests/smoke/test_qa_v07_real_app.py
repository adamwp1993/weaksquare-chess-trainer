"""QA v0.7 in the real app (WebView2 over CDP), temp data folder. Never stores a key: only calls that the
backend refuses before reaching secret_store (bad shapes), plus settings, prices and the Explain gates.
Also checks the real bridge never echoes a key-shaped value and that user.db stays key-free."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke

SHORT = "sk-ant-" + "FAKE"  # too short: refused before secret_store
SPACED = "sk-ant-FAKE " + "spaced " * 4
WRONG_PREFIX = "notakey-FAKE-" + "x" * 20
OTHER = "sk-" + "FAKE" + "x" * 20


def test_qa_v07_real_bridge_gates(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    seen: list[object] = []
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)

            def call(method: str, *args: object) -> dict:  # type: ignore[type-arg]
                r = page.evaluate(f"(a) => window.pywebview.api.{method}(...a)", list(args))
                seen.append(r)
                return r  # type: ignore[no-any-return]

            assert call("set_llm_key", "anthropic", SHORT)["error"]["code"] == "invalid_argument"
            assert call("set_llm_key", "anthropic", SPACED)["ok"] is False
            assert call("set_llm_key", "openai", WRONG_PREFIX)["ok"] is False
            assert call("set_llm_key", "google", OTHER)["ok"] is False
            assert call("set_llm_settings", "anthropic", "../etc", "low", 0.5, 5)["ok"] is False
            assert call("set_llm_settings", "anthropic", "qa-model", "high", 0.5, 5)["ok"]
            assert call("save_llm_price", "anthropic", "qa-model", 1, 2)["ok"]
            assert call("save_llm_price", "anthropic", "qa-model", -1, 2)["ok"] is False
            s = call("get_llm_settings")["data"]
            assert s["reasoning"] == "high" and s["spend"]["configured"] is False
            assert any(m["model"] == "qa-model" for p in s["providers"] for m in p["models"])
            assert call("delete_llm_price", "anthropic", "qa-model")["ok"]
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=30_000)
            assert page.get_by_test_id("explain-button").count() == 0  # no key: no button (FR-8.1)
            for sid in (1, 2):  # the backend refuses too: not over yet / no such session
                assert call("start_explain", sid)["ok"] is False
    finally:
        app.close()
    blob = json.dumps(seen)
    for secret in (SPACED.strip(), WRONG_PREFIX, OTHER):
        assert secret not in blob
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert "sk-" not in dump and "llm_cache" in dump
