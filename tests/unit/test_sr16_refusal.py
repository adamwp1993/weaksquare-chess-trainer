"""SR-16: the CDP debugging port is only allowed for dev/test-harness runs."""

from __future__ import annotations

from weaksquare.app import DEBUG_PORT_ENV, debug_port_refusal, parse_args


def test_refuses_debug_port_in_normal_run() -> None:
    assert debug_port_refusal({DEBUG_PORT_ENV: "--remote-debugging-port=9222"}, dev=False)


def test_allows_debug_port_in_dev_run() -> None:
    assert debug_port_refusal({DEBUG_PORT_ENV: "--remote-debugging-port=9222"}, dev=True) is None


def test_other_webview_args_are_fine() -> None:
    assert debug_port_refusal({DEBUG_PORT_ENV: "--disable-gpu"}, dev=False) is None
    assert debug_port_refusal({}, dev=False) is None


def test_dev_server_implies_dev() -> None:
    assert parse_args(["--dev-server"]).dev
    assert not parse_args([]).dev


def test_window_background_follows_the_saved_scheme() -> None:
    """FR-1.12: the window is painted in the saved scheme before the page loads (no flash)."""
    from weaksquare.app import window_background

    assert window_background("light", system_dark=True) == "#FFFFFF"
    assert window_background("dark", system_dark=False) == "#242424"
    assert window_background("auto", system_dark=True) == "#242424"
    assert window_background("auto", system_dark=False) == "#FFFFFF"
