"""NFR-5: every bridge result is {ok, data} or {ok: false, error: {code, message, retryable}}."""

from __future__ import annotations

from typing import Literal

from tests.helpers import FakeDesktop, build_api
from weaksquare.bridge.errors import INTERNAL_MESSAGE, bridge_call
from weaksquare.core.errors import ValidationError


class Probe:
    @bridge_call
    def ok(self, n: int, kind: Literal["a", "b"] = "a", opt: str | None = None) -> dict:
        return {"n": n, "kind": kind, "opt": opt}

    @bridge_call
    def invalid(self) -> None:
        raise ValidationError("Rating min must be below max.")

    @bridge_call
    def crash(self) -> None:
        raise RuntimeError(r"boom at C:\Users\someone\secret.txt line 3")


def test_success_shape() -> None:
    assert Probe().ok(3) == {"ok": True, "data": {"n": 3, "kind": "a", "opt": None}}


def test_argument_validation() -> None:
    for args in [("3",), (True,), (3, "c"), (3, "a", 5), ()]:
        result = Probe().ok(*args)
        assert result["ok"] is False and result["error"]["code"] == "invalid_argument", args


def test_app_error_passes_message() -> None:
    assert Probe().invalid() == {
        "ok": False,
        "error": {"code": "invalid_argument", "message": "Rating min must be below max.", "retryable": False},
    }


def test_crash_hides_traceback_and_paths() -> None:
    result = Probe().crash()
    assert result["error"] == {"code": "internal", "message": INTERNAL_MESSAGE, "retryable": False}
    assert "secret" not in str(result)


def test_api_methods_return_envelopes(paths, clock) -> None:  # type: ignore[no-untyped-def]
    desktop = FakeDesktop()
    api = build_api(paths, clock, desktop)
    info = api.get_app_info()
    assert info["ok"] and info["data"]["data_dir"] == str(paths.data_dir)
    assert api.open_folder("logs") == {"ok": True, "data": None}
    assert desktop.opened == [paths.logs_dir]
    assert api.open_folder("C:/Windows")["error"]["code"] == "invalid_argument"
    assert api.log_frontend_error("TypeError: x", "app.tsx:1")["ok"]
