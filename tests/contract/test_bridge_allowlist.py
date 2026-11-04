"""ARCHITECTURE §3 decision 13: the bridge exposes exactly the allowlisted methods.

pywebview exposes every public method AND every public attribute that is an object, recursively.
Adding a bridge method means adding it here in the same commit.
"""

from __future__ import annotations

import inspect

from weaksquare.bridge.api import Api
from weaksquare.bridge.errors import BRIDGE_MARK

ALLOWLIST = {
    "get_app_info",
    "open_folder",
    "log_frontend_error",
    "get_puzzle_db_status",
    "choose_puzzle_file",
    "start_puzzle_import",
    "start_puzzle_db_upgrade",
    "check_for_db_update",
    "get_update_offer",
    "dismiss_update",
    "get_job",
    "cancel_job",
    "get_settings",
    "set_setting",
    "get_theme_catalog",
    "count_matches",
    "count_buckets",
    "get_opening_catalog",
    "list_presets",
    "save_preset",
    "rename_preset",
    "delete_preset",
    "start_session",
    "next_puzzle",
    "submit_move",
    "request_help",
    "get_session_stats",
    "get_stats",
    # v0.3: Lichess account and sync (never returns a token, SR-1)
    "get_account_status",
    "start_sign_in",
    "cancel_sign_in",
    "sign_out",
    "get_sync_status",
    "get_attempt_ratings",
    "get_rating_history",
    # v0.4: Stockfish (engine output only after a puzzle ends, FR-7.3)
    "get_engine_status",
    "start_engine_install",
    "get_engine_settings",
    "set_engine_settings",
    "choose_engine_file",
    "start_custom_engine_check",
    "clear_custom_engine",
    "get_refutation",
    "analyze_position",
    # v0.7: LLM settings and the cost guardrails
    "get_llm_settings",
    "set_llm_settings",
    "set_llm_key",
    "delete_llm_key",
    "start_llm_key_test",
    "list_llm_prices",
    "save_llm_price",
    "delete_llm_price",
    "get_llm_spend",
    "get_explain_quote",
    "start_explain",
    "get_explanation",
    "retry_puzzle",  # FR-5.12 Try again (not scored)
    "submit_line",  # v0.5: Commit the line (FR-4.2)
    "get_srs_status",  # v0.5: Spaced repetition (FR-4.6)
    "get_ladder_status",  # v0.5: depth ladder (FR-4.5)
    "set_time_offset",  # v0.5: fast-forward time, --dev runs only
    "set_idea_tags",  # v0.6: Name the idea first (FR-4.3)
    "call_danger",  # v0.6: Danger spotting (FR-4.4)
    "get_reason_prompt",  # v0.6: mistake reasons (§7.3)
    "set_mistake_reason",  # v0.6: mistake reasons (FR-5.6)
    "get_reason_stats",  # v0.6: the reason breakdown (FR-9.7)
    "get_games_settings",  # v0.8: games and Review settings (§11.5)
    "set_games_settings",  # v0.8
    "verify_chesscom",  # v0.8: FR-11.24
    "set_chesscom_username",  # v0.8: FR-11.24
    "start_games_sync",  # v0.8: FR-11.27
    "list_games",  # v0.8: My games (FR-11.25, 11.26)
    "import_game_pgn",  # v0.8: FR-11.2
    "choose_game_file",  # v0.8: FR-11.2
    "pick_imported_game",  # v0.8: FR-11.2
    "start_game_url_import",  # v0.8: FR-11.3, 11.4
    "get_game_url_import",  # v0.8
    "set_game_color",  # v0.8: FR-11.5
    "open_game_online",  # v0.8: FR-11.29
    "analyze_games",  # v0.8: FR-11.30, 11.31
    "get_analysis_queue",  # v0.8: FR-11.31
    "get_review",  # v0.8: FR-11.12-11.14
    "retry_move",  # v0.8: Retry mode (FR-11.15)
    "save_game_puzzle",  # v0.8: FR-11.16
    "set_game_reason",  # v0.8: FR-5.7
    "set_retry_reason",  # v0.8: FR-5.7
    "get_game_stats",  # v0.8: Retry and per-source accuracy
    "choose_and_import_puzzles",  # v0.8: FR-10.46
    "get_puzzle_import_report",  # v0.8: FR-10.48
    "list_puzzle_sets",  # v0.8: FR-10.47
    "set_llm_feature",  # v0.9: a model per AI feature (FR-1.15)
    "get_game_move_quote",  # v0.9: Explain this move (FR-11.17)
    "start_game_move_explain",  # v0.9
    "get_game_move_explanation",  # v0.9
    "get_game_narrative_quote",  # v0.9: Explain my game (FR-11.18)
    "start_game_narrative",  # v0.9
    "get_game_narrative",  # v0.9
}


def _public_names(obj: object) -> set[str]:
    return {n for n in dir(obj) if not n.startswith("_")}


def test_class_exposes_exactly_the_allowlist() -> None:
    assert _public_names(Api) == ALLOWLIST


def test_every_public_method_is_a_bridge_call() -> None:
    for name in ALLOWLIST:
        member = inspect.getattr_static(Api, name)
        assert callable(member), name
        assert getattr(member, BRIDGE_MARK, False), f"{name} is not wrapped by @bridge_call"


def test_instance_has_no_public_attributes(api: Api) -> None:
    """Dependencies live in underscore attributes, so pywebview can't walk into them."""
    public_instance_attrs = {n for n in vars(api) if not n.startswith("_")}
    assert public_instance_attrs == set()
    assert _public_names(api) == ALLOWLIST
