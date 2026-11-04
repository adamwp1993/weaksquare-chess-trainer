"""v0.9 in the real app (WebView2 over CDP), on the fixture DB and a temp data folder: Game Review's own model
(FR-1.15) is picked in Settings → AI through the real bridge and saved in user.db, Explain keeps its own,
and with no key saved there are no AI buttons in Game Review. No key is stored and no request is sent."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke

SCHOLAR = '[White "opponent_b"]\n[Black "player_x"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'


def test_game_review_model_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("gear").click()
            section = page.get_by_test_id("settings-ai")
            section.scroll_into_view_if_needed()
            section.get_by_test_id("ai-provider").click()
            page.get_by_role("option", name="Anthropic").click()
            # Choosing a provider adds Explain's model and key fields above the picker: wait for the layout to
            # settle before opening it (v0.9-B7).
            section.get_by_test_id("ai-model").wait_for()
            page.wait_for_timeout(300)
            picker = section.get_by_test_id("ai-feature-model-game_review")
            picker.scroll_into_view_if_needed()
            assert picker.input_value() == "Same as Explain"  # no Explain model picked yet
            picker.click()
            page.get_by_role("option", name="claude-sonnet-5-5  ·  about").click()
            page.wait_for_function(
                "() => document.querySelector('[data-testid=ai-feature-model-game_review]').value.startsWith('claude-sonnet')"
            )
            section.get_by_test_id("ai-feature-reasoning-game_review").get_by_text("Medium").click()
            for _ in range(50):  # the save goes through the bridge
                settings = page.evaluate("window.pywebview.api.get_llm_settings()")
                if settings["data"]["features"][1]["reasoning"] == "medium":
                    break
                page.wait_for_timeout(100)
            assert settings["ok"], settings
            explain, game_review = settings["data"]["features"][:2]  # v0.10 adds "coach" (v0.10-B8)
            assert (explain["feature"], explain["effective_model"]) == ("explain", "")
            assert (game_review["choice"], game_review["model"], game_review["reasoning"]) == (
                "anthropic", "claude-sonnet-5-5", "medium")  # fmt: skip
            assert game_review["ready"] is False  # no key saved
            page.keyboard.press("Escape")
            page.get_by_test_id("nav-games").click()
            page.get_by_test_id("games-import").click()
            page.get_by_test_id("import-pgn-text").fill(SCHOLAR)
            page.get_by_test_id("import-pgn").click()
            page.get_by_test_id("import-game-dialog").get_by_text("Black", exact=True).click()
            page.get_by_test_id("import-color-ok").click()
            page.get_by_test_id("review-not-analyzed").wait_for()
            assert page.get_by_test_id("narrative-panel").count() == 0  # FR-8.1: no key, no AI
    finally:
        app.close()
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        rows = dict(conn.execute("SELECT key, value FROM settings WHERE key LIKE 'llm.feature.%'").fetchall())
        assert rows == {
            "llm.feature.game_review.provider": '"anthropic"',
            "llm.feature.game_review.model": '"claude-sonnet-5-5"',
            "llm.feature.game_review.reasoning": '"medium"',
        }
        assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone() == (0,)
    finally:
        conn.close()
