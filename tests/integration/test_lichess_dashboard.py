"""v0.10 puzzle-history source (FR-10.15): `GET /api/puzzle/dashboard/{days}` through http.py, with the
token, parsed defensively."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.fakes.lichess import FAKE_TOKEN, FIXTURES
from weaksquare.adapters.http import HttpClient, HttpError
from weaksquare.adapters.lichess import LichessHttp
from weaksquare.core.lichess import parse_dashboard


def _client(handler: object) -> LichessHttp:
    return LichessHttp(HttpClient(transport=httpx.MockTransport(handler), retries=0))  # type: ignore[arg-type]


def test_the_dashboard_is_fetched_with_the_token_and_parsed() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=(FIXTURES / "dashboard.json").read_bytes())

    d = _client(handler).dashboard(FAKE_TOKEN, 30)
    assert seen[0].url.path == "/api/puzzle/dashboard/30"
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert d.days == 30 and d.overall is not None and d.overall.nb == 120
    assert d.themes["fork"].first_wins == 22 and d.themes["fork"].performance == 1640


def test_bad_days_never_reach_lichess() -> None:
    with pytest.raises(ValueError):
        _client(lambda r: httpx.Response(500)).dashboard(FAKE_TOKEN, 0)


def test_an_unexpected_body_is_an_error() -> None:
    with pytest.raises(HttpError):
        _client(lambda r: httpx.Response(200, json=[1, 2])).dashboard(FAKE_TOKEN, 30)


def test_malformed_themes_are_skipped() -> None:
    data = json.loads((FIXTURES / "dashboard.json").read_text(encoding="utf-8"))
    data["themes"]["bad key!"] = {"results": {"nb": 3}}
    data["themes"]["pin"] = {"results": {"nb": "x"}}
    d = parse_dashboard(data)
    assert "bad key!" not in d.themes and "pin" not in d.themes and "fork" in d.themes
