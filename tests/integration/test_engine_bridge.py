"""The v0.4 bridge methods: envelopes, argument checks, and FR-7.3 as the UI sees it."""

from __future__ import annotations

import shutil

import chess

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api


def _api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    return build_api(paths, clock)


def _puzzle(api):  # type: ignore[no-untyped-def]
    sid = api.start_session({"queue_size": 3})["data"]["session_id"]
    view = api.next_puzzle(sid)["data"]
    board = chess.Board(view["fen"])
    board.push_uci(view["opponent_move"])
    return sid, view, board


def test_status_and_settings_envelopes(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    api = _api(paths, clock, fixture_puzzles_db)
    st = api.get_engine_status()
    assert st["ok"] and st["data"]["state"] == "not_installed" and st["data"]["tag"] == "sf_19"
    assert st["data"]["install_job_id"] is None
    s = api.get_engine_settings()["data"]
    assert (s["think_s"], s["hash_mb"], s["max_threads"]) == (1.0, 256, 8)
    bad = api.set_engine_settings(think_s=50)
    assert not bad["ok"] and bad["error"]["code"] == "invalid_argument"
    wrong_type = api.set_engine_settings(threads="4")
    assert not wrong_type["ok"] and wrong_type["error"]["code"] == "invalid_argument"
    good = api.set_engine_settings(threads=2)
    assert good["ok"] and good["data"]["threads"] == 2
    assert not api.start_custom_engine_check("a\x00b.exe")["ok"]


def test_no_engine_output_over_the_bridge_while_solving(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    FakeEngine.instances.clear()
    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, _view, board = _puzzle(api)
    r = api.analyze_position(sid, board.fen(), "panel")
    assert not r["ok"] and r["error"]["code"] == "conflict"
    assert not api.get_refutation(sid)["ok"]
    bad_purpose = api.analyze_position(sid, board.fen(), "sneaky")
    assert not bad_purpose["ok"] and bad_purpose["error"]["code"] == "invalid_argument"
    assert FakeEngine.instances == []


def test_refutation_and_analysis_after_show_answer(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    FakeEngine.instances.clear()
    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, _view, board = _puzzle(api)
    with api._sessions._session(sid).lock:  # the expected first move, to pick a different one
        expected = api._sessions._session(sid).current.state.puzzle.moves[1]
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != expected and not board.gives_check(m))
    assert api.submit_move(sid, wrong)["data"]["kind"] == "wrong"
    help_ = api.request_help(sid, "answer")["data"]
    assert help_["refute"] is True
    ref = api.get_refutation(sid)
    assert ref["ok"] and ref["data"]["wrong_move"] == wrong and ref["data"]["line"]
    a = api.analyze_position(sid, board.fen(), "start")
    assert a["ok"] and len(a["data"]["lines"]) == 3 and not a["data"]["superseded"]
    assert all(isinstance(x["pv"], list) and x["score"] for x in a["data"]["lines"])


def test_not_installed_is_reported_not_crashed(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    api = _api(paths, clock, fixture_puzzles_db)
    sid, _view, board = _puzzle(api)
    with api._sessions._session(sid).lock:
        expected = api._sessions._session(sid).current.state.puzzle.moves[1]
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != expected and not board.gives_check(m))
    api.submit_move(sid, wrong)
    api.request_help(sid, "answer")
    r = api.get_refutation(sid)
    assert not r["ok"] and r["error"]["code"] == "engine_not_installed"
