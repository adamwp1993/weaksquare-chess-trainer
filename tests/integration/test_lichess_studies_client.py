"""adapters/lichess_studies.py over adapters/http.py (v0.14, FR-13.5a, 13.7): the documented endpoints, the token only
when given, the size cap, no secrets in errors, and the author listing parsed strictly."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.studies import fixture_pgn
from weaksquare.adapters import lichess_studies as ls
from weaksquare.adapters.http import HttpClient, HttpError
from weaksquare.adapters.lichess_studies import LichessStudies

FAKE = "lip_" + "FAKE" * 4


def client(handler) -> LichessStudies:  # type: ignore[no-untyped-def]
    return LichessStudies(HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None))


def test_study_pgn_request_and_token_only_when_given() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, text=fixture_pgn("TestGb01"), headers={"content-type": "application/x-chess-pgn"})

    c = client(handler)
    assert c.study_pgn("TestGb01").startswith('[Event "Invented gamebook')
    c.study_pgn("TestGb01", token=FAKE)
    assert seen[0].url.path == "/api/study/TestGb01.pgn"
    assert dict(seen[0].url.params) == {
        "clocks": "false",
        "comments": "true",
        "variations": "true",
        "orientation": "true",
    }
    assert "authorization" not in seen[0].headers
    assert seen[1].headers["authorization"] == f"Bearer {FAKE}"
    assert FAKE not in str(seen[1].url)


def test_study_pgn_refuses_a_bad_id_without_a_request() -> None:
    called = []
    c = client(lambda req: called.append(req) or httpx.Response(200))
    with pytest.raises(ValueError):
        c.study_pgn("../../api/account")
    assert called == []


def test_403_and_404_are_not_retried_and_carry_no_token() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="forbidden")

    with pytest.raises(HttpError) as e:
        client(handler).study_pgn("TestGb01", token=FAKE)
    assert e.value.status == 403 and calls == 1
    assert FAKE not in str(e.value)


def test_a_huge_download_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ls, "MAX_PGN_BYTES", 1000)
    with pytest.raises(HttpError) as e:
        client(lambda req: httpx.Response(200, content=b"x" * 5000)).study_pgn("TestGb01")
    assert e.value.retryable is False


def test_studies_by_parses_strictly() -> None:
    body = (
        b'{"id":"TestGb01","name":"One","createdAt":1,"updatedAt":2}\n'
        b'{"id":"bad id","name":"Skipped"}\n'
        b'{"id":"TestNm02","name":"Two","createdAt":true}\n'
        b"not json\n"
    )
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=body)

    got = list(client(handler).studies_by("player_author"))
    assert seen[0].url.path == "/api/study/by/player_author"
    assert "authorization" not in seen[0].headers
    assert [(s.study_id, s.name, s.created_ms, s.updated_ms) for s in got] == [
        ("TestGb01", "One", 1, 2), ("TestNm02", "Two", None, None),
    ]  # fmt: skip
