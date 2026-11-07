"""Live opening explorer check (v0.13, FR-12.2; opt-in, Adam runs it, never Claude Code).

It reads, and never writes, one position from the Lichess opening explorer with the `weaksquare-test` token, and
checks the app's parser against the real answer. This is the only check that the explorer accepts a token with
the app's own scopes. Add `--record-explorer` to write a scrubbed fixture (position counts only: no games, no
players, no ids) to tests/fixtures/http/explorer/. Review the diff before committing. Skips if there's no token.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chess
import pytest

from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.opening_sources import LichessExplorer
from weaksquare.adapters.secret_store import LICHESS, SERVICE_TEST, KeyringSecretStore, SecretStoreError
from weaksquare.core.opening_sources import DEFAULT_RATINGS, parse_explorer

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "explorer"
AFTER_E4 = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")


def _scrub(body: dict[str, Any]) -> dict[str, Any]:
    """Only what the parser reads."""
    keep = ("white", "draws", "black")
    return {
        **{k: body.get(k, 0) for k in keep},
        "moves": [{"uci": m["uci"], "san": m["san"], **{k: m.get(k, 0) for k in keep}} for m in body.get("moves", [])],
    }


@pytest.mark.parametrize("source", ["lichess", "masters"])
def test_the_explorer_accepts_the_token_and_the_parser_reads_the_answer(source: str, request: Any) -> None:
    try:
        token = KeyringSecretStore(SERVICE_TEST).get(LICHESS)
    except SecretStoreError:
        token = None
    if not token:
        pytest.skip("no live-test token: run uv run python scripts/set_test_token.py in your own PowerShell window")
    http = HttpClient(retries=0)
    try:
        body = LichessExplorer(http).fetch(token, source, AFTER_E4.fen(en_passant="legal"), DEFAULT_RATINGS)
    finally:
        http.close()
    result = parse_explorer(AFTER_E4, body)
    assert result.total > 0
    assert result.moves, "the parser dropped every move"
    assert {"e7e5", "c7c5"} <= {m.uci for m in result.moves}
    assert [m.games for m in result.moves] == sorted((m.games for m in result.moves), reverse=True)
    if request.config.getoption("--record-explorer"):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / f"{source}_after_e4.json").write_text(json.dumps(_scrub(body), indent=2) + "\n", encoding="utf-8")
