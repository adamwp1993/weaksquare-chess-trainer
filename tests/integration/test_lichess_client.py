"""adapters/lichess.py against the recorded fixtures through the real HttpClient (MockTransport),
plus the parsers' tolerance of missing fields (FR-6.8–6.12, 6.17)."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.fakes.lichess import FAKE_TOKEN, FIXTURES
from weaksquare.adapters.http import HttpClient, HttpError
from weaksquare.adapters.lichess import LichessHttp
from weaksquare.core.lichess import Solution, batch_body, parse_account, parse_activity, parse_batch


def _client(handler) -> LichessHttp:  # type: ignore[no-untyped-def]
    return LichessHttp(HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None))


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_account_reads_the_puzzle_rating() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/account"
        assert req.headers["authorization"] == f"Bearer {FAKE_TOKEN}"
        return httpx.Response(200, content=_fixture("account.json"))

    a = _client(handler).account(FAKE_TOKEN)
    assert (a.id, a.username, a.rating, a.provisional) == ("player_a", "player_a", 1834, False)


def test_solve_batch_request_and_response() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=_fixture("batch_solve.json"))

    sols = [Solution("001KR", True, True), Solution("008o6", False, True)]
    r = _client(handler).solve_batch(FAKE_TOKEN, "fork", sols)
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/api/puzzle/batch/fork"
    assert req.url.params["nb"] == "0"  # no new puzzles wanted
    assert json.loads(req.content) == {
        "solutions": [{"id": "001KR", "win": True, "rated": True}, {"id": "008o6", "win": False, "rated": True}]
    }
    assert [(x.id, x.win, x.rating_diff) for x in r.rounds] == [("001KR", True, 8), ("008o6", False, -13)]
    assert (r.rating, r.provisional) == (1829, False)


def test_batch_limits_and_bad_angle() -> None:
    with pytest.raises(ValueError):
        batch_body([Solution(f"P{i}", True, True) for i in range(100)])  # FR-6.9
    with pytest.raises(ValueError):
        batch_body([])
    with pytest.raises(ValueError):
        _client(lambda r: httpx.Response(200)).solve_batch(FAKE_TOKEN, "../account", [Solution("A", True, True)])


def test_activity_streams_entries_since() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["since"] == "123"
        return httpx.Response(200, content=_fixture("activity.ndjson"))

    got = list(_client(handler).activity(FAKE_TOKEN, 123))
    assert [(e.puzzle_id, e.win) for e in got] == [("00DPQ", True), ("001KR", False)]
    assert got[0].date_ms > got[1].date_ms  # newest first, as Lichess sends it


def test_token_exchange_and_revoke() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            assert req.url.path == "/api/token"
            assert b"grant_type=authorization_code" in req.content
            return httpx.Response(
                200, json={"token_type": "Bearer", "access_token": FAKE_TOKEN, "expires_in": 31536000}
            )
        assert req.method == "DELETE" and req.headers["authorization"] == f"Bearer {FAKE_TOKEN}"
        return httpx.Response(204)

    c = _client(handler)
    assert c.exchange_code({"grant_type": "authorization_code"}) == FAKE_TOKEN
    c.revoke(FAKE_TOKEN)


def test_exchange_without_a_token_fails_cleanly() -> None:
    with pytest.raises(HttpError):
        _client(lambda r: httpx.Response(200, json={"error": "x"})).exchange_code({})


def test_parsers_tolerate_missing_fields() -> None:
    a = parse_account({"username": "Player_A"})
    assert (a.id, a.rating, a.provisional) == ("player_a", None, False)
    assert parse_account({"username": "p", "perfs": {"puzzle": {"rating": 1500, "prov": True}}}).provisional
    b = parse_batch({"rounds": [{"id": "X1", "win": True}, {"nope": 1}]})
    assert [(r.id, r.rating_diff) for r in b.rounds] == [("X1", None)]
    assert b.rating is None
    assert parse_activity({"date": 1, "puzzle": {"id": "bad id!"}}) is None
    assert parse_activity({"win": True, "puzzle": {"id": "A1"}}) is None
    with pytest.raises(ValueError):
        parse_account([])
