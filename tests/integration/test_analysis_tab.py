"""v0.15, the Analysis tab through the bridge (REQUIREMENTS §20): positions are checked before the engine, a PGN's
text never reaches it, popular replies are skipped cleanly, and nothing counts (FR-14.5)."""

from __future__ import annotations

import ast
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api
from tests.integration.test_opening_sources import Net, Tokens
from weaksquare.adapters.db.repos.openings import ExplorerCacheRepo, WikibooksPagesRepo
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.opening_sources import LichessExplorer, WikibooksClient
from weaksquare.services.analysis_tab import AnalysisTabService
from weaksquare.services.opening_sources import OpeningSources

SRC = Path(__file__).resolve().parents[2] / "src" / "weaksquare"
AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
PGN = """[Event "Invented Open"]
[White "Player A"]
[Black "Player B"]

1. e4 {[%clk 0:05:00] [%eval 0.3] A comment} e5 (1... c5) 2. Nf3 *
"""


def ok(result: dict[str, Any]) -> Any:
    assert result["ok"], result
    return result["data"]


@pytest.fixture
def net() -> Net:
    return Net()


@pytest.fixture
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def api(services: Any, paths: Any, clock: Any, net: Net, tokens: Tokens) -> Any:
    a = build_api(paths, clock)
    http = HttpClient(transport=httpx.MockTransport(net), retries=0, sleep=lambda _s: None)
    sources = OpeningSources(
        LichessExplorer(http), WikibooksClient(http), ExplorerCacheRepo(services.db), WikibooksPagesRepo(services.db),
        SettingsRepo(services.db), tokens, clock,
    )  # fmt: skip
    a._analysis_tab = AnalysisTabService(services.engine, sources)
    return a


def engine_calls() -> list[str]:
    return [fen for e in FakeEngine.instances for fen, _t, _m in e.calls]


# ---- FR-14.2: set up a position ---------------------------------------------------------------------------------


def test_check_board_position_lists_problems_and_returns_the_fen_when_legal(api: Any) -> None:
    good = ok(api.check_board_position("4k3/8/8/8/8/8/8/4K3 w - - 0 1"))
    assert good == {"ok": True, "fen": "4k3/8/8/8/8/8/8/4K3 w - - 0 1", "problems": []}
    bad = ok(api.check_board_position("4k3/8/8/8/8/8/8/8 w - - 0 1"))
    assert bad["ok"] is False and bad["fen"] is None and "White has no king." in bad["problems"]


@pytest.mark.parametrize("fen", ["4k3/8/8/8/8/8/8/8 w - - 0 1", "not a fen", "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"])
def test_an_illegal_position_never_reaches_stockfish(api: Any, paths: Any, fen: str) -> None:
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    r = api.analyze_board_position(fen, "board")
    assert not r["ok"] and r["error"]["message"]
    assert api.get_popular_replies(fen)["ok"] is False
    assert engine_calls() == []


def test_a_legal_position_is_analyzed_on_the_interactive_engine(api: Any, paths: Any) -> None:
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    a = ok(api.analyze_board_position(AFTER_E4, "board"))
    assert len(a["lines"]) == 3 and a["fen"] == AFTER_E4
    used = [e for e in FakeEngine.instances if e.calls]
    assert used and all(e.options[0] == 7 for e in used)  # the interactive engine only, never the background one


def test_without_stockfish_it_says_install(api: Any) -> None:
    r = api.analyze_board_position(AFTER_E4, "board")
    assert not r["ok"] and "Install Stockfish" in r["error"]["message"]


# ---- FR-14.3: import a PGN -------------------------------------------------------------------------------------


def test_a_pasted_pgn_lists_its_games_and_sends_one_tree(api: Any) -> None:
    listed = ok(api.import_analysis_pgn(PGN))
    assert (
        listed["games"] == [{"index": 0, "label": "Player A – Player B", "move_count": 4}] and listed["skipped"] == []
    )
    g = ok(api.get_analysis_pgn_game(PGN, 0))
    moves = g["moves"]
    assert moves[0]["parent"] is None and moves[0]["fen"] == g["start_fen"]
    e4 = moves[moves[0]["children"][0]]
    assert e4["san"] == "e4" and e4["comment"] == "A comment"
    assert [moves[c]["san"] for c in e4["children"]] == ["e5", "c5"]


def test_a_bad_pgn_is_a_clear_error(api: Any) -> None:
    r = api.import_analysis_pgn("1. e4 e5 2. Qxf7")
    assert not r["ok"] and "illegal or unreadable" in r["error"]["message"]
    assert not api.get_analysis_pgn_game(PGN, 5)["ok"]


def test_a_pgns_headers_comments_and_clocks_never_reach_the_engine(api: Any, paths: Any) -> None:
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    for m in ok(api.get_analysis_pgn_game(PGN, 0))["moves"]:
        ok(api.analyze_board_position(m["fen"], "board"))
    sent = " ".join(engine_calls())
    assert engine_calls() and all(" " in f and f.count("/") == 7 for f in engine_calls())  # FENs only
    for leaked in ("Player", "Invented", "clk", "eval", "comment", "0:05:00"):
        assert leaked not in sent


# ---- FR-14.4: popular replies ----------------------------------------------------------------------------------


def test_popular_replies_when_signed_in(api: Any, net: Net) -> None:
    r = ok(api.get_popular_replies(AFTER_E4))
    assert r["state"] == "ok" and r["total"] == 1800
    assert [m["san"] for m in r["moves"]] == ["e5", "c5"]  # the illegal and broken rows are dropped
    assert r["moves"][0] == {"uci": "e7e5", "san": "e5", "games": 1000, "white": 500, "draws": 50, "black": 450}
    assert len(net.requests) == 1 and "fen=" in str(net.requests[0].url)


def test_popular_replies_are_skipped_cleanly_when_signed_out(api: Any, net: Net, tokens: Tokens) -> None:
    tokens.value = None
    r = ok(api.get_popular_replies(AFTER_E4))
    assert r == {"state": "signed_out", "total": 0, "moves": []} and net.requests == []


def test_popular_replies_are_skipped_cleanly_offline(api: Any, net: Net) -> None:
    net.fail = httpx.ConnectError
    assert ok(api.get_popular_replies(AFTER_E4)) == {"state": "unavailable", "total": 0, "moves": []}


# ---- FR-14.5: nothing counts -----------------------------------------------------------------------------------


def _snapshot(db: Path) -> dict[str, str]:
    """A hash of every table's rows. The explorer's cache is the one thing a popular-replies lookup may add to."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out = {}
        for n in names:
            if n == "explorer_cache":
                continue
            rows = sorted(repr(r) for r in conn.execute(f'SELECT * FROM "{n}"'))
            out[n] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
        return out
    finally:
        conn.close()


def test_trying_lines_changes_no_puzzle_stat_game_or_coach_data(api: Any, paths: Any) -> None:
    plant_managed_install(paths)
    ok(api.analyze_board_position(AFTER_E4, "board"))  # the first call may record the engine's identity
    before = (_snapshot(paths.user_db), _snapshot(paths.puzzles_db))
    ok(api.check_board_position(AFTER_E4))
    ok(api.import_analysis_pgn(PGN))
    for m in ok(api.get_analysis_pgn_game(PGN, 0))["moves"]:
        ok(api.analyze_board_position(m["fen"], "panel"))
        ok(api.get_popular_replies(m["fen"]))
    assert (_snapshot(paths.user_db), _snapshot(paths.puzzles_db)) == before


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


@pytest.mark.parametrize("module", ["services/analysis_tab.py", "core/analysis_pgn.py", "core/position_setup.py"])
def test_the_analysis_tab_has_no_llm_and_no_repository(module: str) -> None:
    """FR-14.5: nothing here goes to an LLM, and nothing here can write your data."""
    imps = _imports(SRC / module)
    assert not any("llm" in i or "explain" in i or "coach" in i for i in imps), imps
    assert not any(i.startswith(("weaksquare.adapters", "weaksquare.services")) for i in imps), imps
