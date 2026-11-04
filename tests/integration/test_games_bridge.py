"""v0.8 bridge: every game-library, Review and puzzle-file method end to end through `Api`, with the fake
clients, the fake engine and a fake desktop. Errors come back as {code, message} (NFR-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import FakeDesktop, build_api

MATE = '[White "opponent_b"]\n[Black "player_x"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
BACK_RANK = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def ok(r: dict):  # type: ignore[no-untyped-def]
    assert r["ok"], r
    return r["data"]


def err(r: dict) -> str:
    assert not r["ok"], r
    return str(r["error"]["code"])


def wait(api, job: str) -> dict:  # type: ignore[no-untyped-def]
    st = api._runner.wait(job, 10)
    assert st is not None
    return ok(api.get_job(job))


def test_paste_analyze_review_retry_save_and_reason(services, paths, clock) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    api = build_api(paths, clock)
    imp = ok(api.import_game_pgn(MATE))
    gid = imp["game_id"]
    assert imp["needs_color"] and imp["choices"] == []
    assert err(api.set_game_color(gid, "purple")) == "invalid_argument"
    ok(api.set_game_color(gid, "black"))
    before = ok(api.get_review(gid))
    assert not before["analyzed"] and before["moves"][0]["classification"] is None
    job = ok(api.analyze_games([gid]))
    assert wait(api, job)["state"] == "done"
    assert ok(api.analyze_games([gid])) is None  # already analyzed at these settings
    rev = ok(api.get_review(gid))
    assert rev["analyzed"] and rev["current"] and len(rev["moves"]) == 7 and len(rev["summaries"]) == 2
    assert rev["game"]["user_color"] == "black" and rev["game"]["analysis_status"] == "analyzed"
    ply = rev["moves"][5]["ply"]
    if rev["retry_plies"]:  # the fake engine's grading decides which moves are mistakes
        ply = rev["retry_plies"][0]
        res = ok(api.retry_move(gid, ply, rev["moves"][ply]["uci"], 1500))
        assert res["best_line"] and isinstance(res["found"], bool)
        if not res["found"]:
            ok(api.set_retry_reason(res["retry_id"], "rushed"))
        ok(api.set_game_reason(gid, ply, "didntLook"))
        assert ok(api.get_review(gid))["moves"][ply]["reason"] == "didntLook"
    saved = ok(api.save_game_puzzle(gid, ply))
    assert saved["created"] and not ok(api.save_game_puzzle(gid, ply))["created"]
    assert ok(api.count_matches({"source": "my", "exclude_solved_here": False})) == 1
    assert err(api.retry_move(gid, ply, "zz99")) == "invalid_argument"
    assert err(api.get_review(999)) == "not_found"
    stats = ok(api.get_game_stats())
    assert stats["retry_tried"] >= 0 and isinstance(stats["sources"], list)
    games = ok(api.get_reason_stats(None, None, "games"))
    assert games["tagged"] + games["untagged"] >= 0
    assert err(api.get_reason_stats(None, None, "everything")) == "invalid_argument"


def test_library_list_filters_and_settings(services, paths, clock) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    ok(api.import_game_pgn(MATE))
    page = ok(api.list_games({"limit": 10}))
    assert page["total"] == 1 and page["games"][0]["source"] == "paste"
    assert ok(api.list_games({"platforms": ["lichess"]}))["total"] == 0
    assert err(api.list_games({"surprise": 1})) == "invalid_argument"
    assert err(api.list_games({"date_from": "yesterday"})) == "invalid_argument"
    st = ok(api.get_games_settings())
    assert (st["sync_on_open"], st["first_sync_days"], st["think_s"], st["tolerance_cp"]) == (True, 90, 0.3, 30)
    st = ok(
        api.set_games_settings(
            sync_on_open=False, think_s=0.5, thresholds={"inaccuracy": 40, "mistake": 90, "blunder": 180}
        )
    )
    assert not st["sync_on_open"] and st["think_s"] == 0.5 and st["thresholds"]["mistake"] == 90
    assert err(api.set_games_settings(key_moments=50)) == "invalid_argument"


def test_chesscom_link_sync_and_url_import(services, paths, clock) -> None:  # type: ignore[no-untyped-def]
    desktop = FakeDesktop()
    api = build_api(paths, clock, desktop=desktop)
    assert ok(api.verify_chesscom("player_a"))["username"] == "player_a"
    assert err(api.verify_chesscom("nobody_here")) == "not_found"
    assert ok(api.set_chesscom_username("player_a"))["chesscom_username"] == "player_a"
    job = ok(api.start_games_sync())
    assert wait(api, job)["state"] == "done"
    assert ok(api.list_games({"platforms": ["chesscom"]}))["total"] >= 1
    url_job = ok(api.start_game_url_import("https://www.chess.com/game/live/100000002"))
    assert wait(api, url_job)["state"] == "done"
    got = ok(api.get_game_url_import(url_job))
    assert got["game_id"]
    ok(api.open_game_online(got["game_id"]))
    assert desktop.urls == ["https://www.chess.com/game/live/100000002"]
    assert err(api.start_game_url_import("https://example.com/x")) == "bad_url"


def test_game_and_puzzle_files_through_the_open_dialog(services, paths, clock, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    desktop = FakeDesktop()
    api = build_api(paths, clock, desktop=desktop)
    assert ok(api.choose_game_file()) is None  # cancelled
    games = tmp_path / "two.pgn"
    games.write_text(MATE + "\n" + MATE.replace("Qxf7#", "Bxf7+"), encoding="utf-8")
    desktop.next_file = str(games)
    listed = ok(api.choose_game_file())
    assert listed["token"] and len(listed["choices"]) == 2
    assert ok(api.pick_imported_game(listed["token"], 1))["game_id"]
    puzzles = tmp_path / "set.csv"
    puzzles.write_text(f"fen,solution\n{BACK_RANK},Rd8#\nbad,e4\n", encoding="utf-8")
    desktop.next_file = str(puzzles)
    job = ok(api.choose_and_import_puzzles("My book"))
    assert wait(api, job)["state"] == "done"
    rep = ok(api.get_puzzle_import_report(job))
    assert (rep["added"], rep["skipped"], rep["errors"][0]["n"]) == (1, 1, 2)
    assert ok(api.list_puzzle_sets()) == [{"label": "My book", "count": 1}]
    assert err(api.choose_and_import_puzzles("")) == "invalid_argument"


def test_a_my_puzzle_view_says_so(services, paths, clock, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    desktop = FakeDesktop()
    api = build_api(paths, clock, desktop=desktop)
    f = tmp_path / "set.csv"
    f.write_text(f"fen,solution\n{BACK_RANK},Rd8#\n", encoding="utf-8")
    desktop.next_file = str(f)
    wait(api, ok(api.choose_and_import_puzzles("Book")))
    sid = ok(api.start_session({"source": "my"}))["session_id"]
    view = ok(api.next_puzzle(sid))
    assert view["source"] == "my" and view["opponent_move"] == "" and view["fen"] == BACK_RANK
