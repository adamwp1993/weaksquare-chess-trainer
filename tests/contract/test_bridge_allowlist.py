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
    "get_job",
    "cancel_job",
    "get_settings",
    "set_setting",
    "get_theme_catalog",
    "count_matches",
    "start_session",
    "next_puzzle",
    "submit_move",
    "get_session_stats",
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
