"""The live recorder's scrubbing (SR-12, SR-12a) and scripts/set_test_token.py, without a real token
and without any network call. (The live tests themselves run only with `-m live`, by Adam.)"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from tests.contract.test_fixtures_clean import SECRET_PATTERNS, USERNAME_FIELD
from tests.live.test_lichess_live import scrub
from weaksquare.adapters.secret_store import MemorySecretStore

ROOT = Path(__file__).resolve().parents[2]
REAL_LOOKING = {
    "account": {
        "id": "somerealname",
        "username": "SomeRealName",
        "url": "https://lichess.org/@/SomeRealName",
        "createdAt": 1600000000000,
        "perfs": {"puzzle": {"games": 9876, "rating": 2213, "rd": 55, "prog": -7}, "blitz": {"rating": 2001}},
        "profile": {"location": "Somewhere"},
    },
    "batch": {
        "puzzles": [{"puzzle": {"id": "ZZZZZ"}}],
        "glicko": {"rating": 2210.7, "deviation": 54.3, "provisional": False},
        "rounds": [{"id": "abcde", "win": True, "ratingDiff": 0}],
    },
    "activity": [
        {
            "date": 1700000000123,
            "win": True,
            "puzzle": {
                "id": "qwert",
                "fen": "r1b/real",
                "rating": 2400,
                "plays": 77,
                "solution": ["a1a2"],
                "themes": ["pin"],
                "lastMove": "h7h8",
            },
        }
    ],
}


def test_scrub_keeps_shapes_and_drops_identity() -> None:
    files = scrub({**REAL_LOOKING, "ids": []})
    text = "".join(files.values())
    for bad in (
        "SomeRealName",
        "somerealname",
        "Somewhere",
        "2213",
        "2210.7",
        "qwert",
        "abcde",
        "r1b/real",
        "1700000000123",
    ):
        assert bad not in text, bad
    account = json.loads(files["account.json"])
    assert account["username"] == "player_a" and set(account["perfs"]) == {"puzzle"}
    assert set(account["perfs"]["puzzle"]) == {"games", "rating", "rd", "prog"}
    batch = json.loads(files["batch_solve.json"])
    assert set(batch["rounds"][0]) == {"id", "win", "ratingDiff"} and batch["puzzles"] == []
    entry = json.loads(files["activity.ndjson"].splitlines()[0])
    assert set(entry["puzzle"]) == {"id", "fen", "rating", "plays", "solution", "themes", "lastMove"}
    # What the recorder writes passes the fixture checks.
    for name, content in files.items():
        assert not any(p.search(content) for p in SECRET_PATTERNS), name
        if name.endswith(".json"):
            for m in USERNAME_FIELD.finditer(content):
                assert m.group(1) == "id" and '"rounds"' in content, m.group(0)


def _script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("set_test_token", ROOT / "scripts" / "set_test_token.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_set_test_token_stores_without_printing(capsys) -> None:  # type: ignore[no-untyped-def]
    mod = _script()
    store = MemorySecretStore()
    token = "lip_FAKE" + "abc123" * 3
    assert mod.main([], prompt=lambda _: token, store_factory=lambda service: store) == 0
    assert store.get("lichess") == token
    out = capsys.readouterr().out
    assert token not in out and "weaksquare-test" in out
    assert mod.main(["--delete"], prompt=lambda _: "", store_factory=lambda service: store) == 0
    assert store.get("lichess") is None


def test_set_test_token_refuses_junk(capsys) -> None:  # type: ignore[no-untyped-def]
    mod = _script()
    store = MemorySecretStore()
    assert mod.main([], prompt=lambda _: "not a token", store_factory=lambda service: store) == 1
    assert store.get("lichess") is None
    assert "not a token" not in capsys.readouterr().out


def test_store_factory_gets_the_test_entry() -> None:
    mod = _script()
    seen: list[str] = []

    def factory(service: str) -> MemorySecretStore:
        seen.append(service)
        return MemorySecretStore()

    mod.main(["--delete"], store_factory=factory)
    assert seen == ["weaksquare-test"]
