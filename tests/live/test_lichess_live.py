"""Live Lichess test (SR-13): opt-in with `uv run pytest -m live`; Adam runs it, never Claude Code.

It uses the separate `weaksquare-test` token (scripts/set_test_token.py), sends exactly 3 solves with
`rated: false`, and checks the real response shapes the app's parsers rely on (FR-6.11). With
`--record-lichess` it writes scrubbed, anonymized copies to tests/fixtures/http/lichess/ for the fake
client (SR-12, SR-12a): no headers or tokens, the username becomes `player_a`, numbers that could
identify you are replaced, and puzzle IDs and dates are swapped for fixture ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "lichess"
CSV = Path(__file__).resolve().parents[1] / "fixtures" / "puzzles_sample.csv"
MAX_SOLVES = 3  # SR-13


def _token() -> str:
    from weaksquare.adapters.secret_store import LICHESS, SERVICE_TEST, KeyringSecretStore, SecretStoreError

    try:
        token = KeyringSecretStore(SERVICE_TEST).get(LICHESS)
    except SecretStoreError:
        token = None
    if not token:
        pytest.skip("no live-test token: run uv run python scripts/set_test_token.py in your own PowerShell window")
    return token


def _puzzle_ids(n: int) -> list[str]:
    lines = CSV.read_text(encoding="utf-8").splitlines()[1 : n + 1]
    return [line.split(",", 1)[0] for line in lines]


@pytest.fixture(scope="module")
def raw():  # type: ignore[no-untyped-def]
    """The real responses, fetched once: account, one unrated batch of 3, and 3 activity entries."""
    from weaksquare.adapters.http import HttpClient

    token = _token()
    http = HttpClient()
    try:
        ids = _puzzle_ids(MAX_SOLVES)
        body = {"solutions": [{"id": pid, "win": i % 2 == 0, "rated": False} for i, pid in enumerate(ids)]}
        assert len(body["solutions"]) <= MAX_SOLVES and not any(s["rated"] for s in body["solutions"])
        account = http.get_json("https://lichess.org/api/account", token=token)
        batch = http.post_json("https://lichess.org/api/puzzle/batch/mix", body, token=token, params={"nb": 0})
        activity = []
        for obj in http.stream_ndjson("https://lichess.org/api/puzzle/activity", token=token, params={"max": 3}):
            activity.append(obj)
        yield {"account": account, "batch": batch, "activity": activity, "ids": ids}
    finally:
        http.close()


def test_account_shape(raw) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.lichess import parse_account

    a = raw["account"]
    assert isinstance(a.get("username"), str) and isinstance(a.get("id"), str)
    puzzle = a.get("perfs", {}).get("puzzle")
    assert puzzle is None or isinstance(puzzle.get("rating"), int)
    parse_account(a)


def test_batch_shape(raw) -> None:  # type: ignore[no-untyped-def]
    """FR-6.11: confirm the field names (rounds[].ratingDiff, glicko.rating) on a real response."""
    from weaksquare.core.lichess import parse_batch

    b = raw["batch"]
    assert isinstance(b.get("rounds"), list) and isinstance(b.get("glicko"), dict)
    for r in b["rounds"]:
        assert set(r) >= {"id", "win", "ratingDiff"}, r
        assert r["ratingDiff"] == 0  # unrated solves never change the rating
    assert isinstance(b["glicko"].get("rating"), int | float)
    result = parse_batch(b)
    assert {r.id for r in result.rounds} <= set(raw["ids"])


def test_activity_shape(raw) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.lichess import parse_activity

    for obj in raw["activity"]:
        assert isinstance(obj.get("date"), int) and isinstance(obj.get("puzzle", {}).get("id"), str)
        assert parse_activity(obj) is not None


def test_record(raw, request: pytest.FixtureRequest) -> None:  # type: ignore[no-untyped-def]
    if not request.config.getoption("--record-lichess"):
        pytest.skip("pass --record-lichess to update the fixtures")
    files = scrub(raw)
    for name, text in files.items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
    readme = FIXTURES / "README.md"
    lines = readme.read_text(encoding="utf-8").splitlines()
    lines = [x for x in lines if not x.startswith("Status:")] + [
        "Status: recorded from live responses (scrubbed and anonymized)."
    ]
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- scrubbing (SR-12, SR-12a) ------------------------------------------------------------------
PUZZLE_RATING = {"games": 412, "rating": 1834, "rd": 62, "prog": 15}
GLICKO = {"rating": 1829.4, "deviation": 61.8}
FIXED_DATES = [1793520000000, 1793433600000, 1793347200000]
PLACEHOLDER_PUZZLE = {"fen": "8/8/8/8/8/8/8/8 w - - 0 1", "lastMove": "e2e4", "plays": 1000, "rating": 1500,
                      "solution": ["e7e5"], "themes": ["fork", "short"]}  # fmt: skip


def _blank(v: Any) -> Any:
    """Keep the type, drop the value."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int | float):
        return 0
    if isinstance(v, str):
        return "x"
    if isinstance(v, list):
        return []
    if isinstance(v, dict):
        return {k: _blank(x) for k, x in v.items()}
    return None


def scrub(raw: dict[str, Any]) -> dict[str, str]:
    """Only the shapes survive: every key is kept, every value that could identify you is replaced."""
    a = raw["account"]
    puzzle = (a.get("perfs") or {}).get("puzzle") or {}
    account = {k: _blank(v) for k, v in a.items() if k not in ("perfs",)}
    account.update({"id": "player_a", "username": "player_a"})
    for k in ("url",):
        if k in account:
            account[k] = "https://lichess.org/@/player_a"
    account["perfs"] = {"puzzle": {k: PUZZLE_RATING.get(k, _blank(v)) for k, v in puzzle.items()}}

    fixture_ids = _puzzle_ids(MAX_SOLVES)
    b = raw["batch"]
    batch = {k: _blank(v) for k, v in b.items() if k not in ("rounds", "glicko", "puzzles")}
    batch["puzzles"] = []
    batch["glicko"] = {k: GLICKO.get(k, v if isinstance(v, bool) else _blank(v)) for k, v in b["glicko"].items()}
    batch["rounds"] = [
        {
            **{k: _blank(v) for k, v in r.items()},
            "id": fixture_ids[i % len(fixture_ids)],
            "win": r["win"],
            "ratingDiff": r["ratingDiff"],
        }
        for i, r in enumerate(b["rounds"])
    ]

    activity = []
    for i, obj in enumerate(raw["activity"][:3]):
        p = obj.get("puzzle", {})
        puzzle_obj = {k: PLACEHOLDER_PUZZLE.get(k, _blank(v)) for k, v in p.items()}
        puzzle_obj["id"] = fixture_ids[i % len(fixture_ids)]
        entry = {k: _blank(v) for k, v in obj.items() if k not in ("puzzle", "date", "win")}
        entry.update({"date": FIXED_DATES[i], "win": bool(obj.get("win")), "puzzle": puzzle_obj})
        activity.append(entry)

    return {
        "account.json": json.dumps(account, indent=2) + "\n",
        "batch_solve.json": json.dumps(batch, indent=2) + "\n",
        "activity.ndjson": "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in activity),
    }
