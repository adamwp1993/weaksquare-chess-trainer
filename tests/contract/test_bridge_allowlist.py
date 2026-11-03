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
