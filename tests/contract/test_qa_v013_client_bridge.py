"""QA v0.13: the real client's calls against the bridge's real `_check` and `bridge_call` (FR-12, ARCHITECTURE §3 decision 13).

The UI tests use the mock client, so nothing there proves `pywebviewClient.ts` sends what `Api` accepts. This reads the
client's source for every call it makes, and sends the same shapes through the real wrappers."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api
from weaksquare.bridge.api import Api
from weaksquare.bridge.errors import BRIDGE_MARK

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "web" / "src" / "api" / "pywebviewClient.ts"
CALL = re.compile(r"this\.call<[^(]*?>\(\s*\"(\w+)\"((?:,[^;]*?)?)\)\s*;", re.S)
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
START_KEY = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
FAMILY = "Italian Game"
E4 = "e2e4"


def _calls() -> list[tuple[str, int]]:
    out = []
    for name, args in CALL.findall(CLIENT.read_text(encoding="utf-8")):
        depth, count = 0, 0
        for ch in args:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                count += 1
        out.append((name, count))
    return out


def test_the_reader_sees_the_clients_calls() -> None:
    names = dict(_calls())
    assert names["get_opening_note_quote"] == 4 and names["start_repertoire_build"] == 3 and len(names) > 100


@pytest.mark.parametrize(
    ("name", "count"), [c for c in _calls() if "opening" in c[0] or "practice" in c[0] or "repertoire" in c[0]]
)
def test_every_opening_call_binds_to_a_bridge_method(name: str, count: int) -> None:
    method = getattr(Api, name, None)
    assert method is not None and getattr(method, BRIDGE_MARK, False), name
    params = list(inspect.signature(method).parameters.values())[1:]
    required = sum(1 for p in params if p.default is inspect.Parameter.empty)
    assert required <= count <= len(params), name


@pytest.fixture
def api(paths: Any, clock: Any, fixture_puzzles_db: Any) -> Any:
    import shutil

    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    a = build_api(paths, clock)
    a._openings.import_now()
    a._opening_sources.set_use_wikibooks(False)
    yield a
    a._runner.cancel_all()


def ok(r: dict[str, Any]) -> Any:
    assert r["ok"], r
    json.dumps(r)  # what crosses the bridge is plain JSON
    return r["data"]


def test_settings_as_the_view_sends_them(api: Any) -> None:
    assert ok(api.set_opening_settings("light", None, None, True))["scope"]["preset"] == "light"
    assert ok(api.set_opening_settings("custom", 0, 4, False))["extend"] is False
    assert ok(api.set_opening_settings("custom", 99, 999, None))["scope"] == {
        "preset": "custom",
        "sub_lines": 10,
        "max_moves": 20,
    }
    assert ok(api.set_opening_sources(True, "masters", [1600]))["explorer_source"] == "masters"


@pytest.mark.parametrize(
    "args",
    [("light", "x", None, True), ("light", None, None, "yes"), ("custom", 1.5, 4, True), (3, None, None, True)],
)
def test_settings_with_a_wrong_type_are_refused_by_the_check(api: Any, args: tuple[Any, ...]) -> None:
    r = api.set_opening_settings(*args)
    assert r["ok"] is False and r["error"]["code"] == "invalid_argument"


def test_a_note_quote_with_a_null_ply_is_accepted(api: Any) -> None:
    assert ok(api.get_opening_note_quote(FAMILY, 0, None, False))["state"] == "not_configured"
    assert ok(api.get_opening_note_quote(FAMILY, 0, 2, False))["state"] == "not_configured"
    assert ok(api.get_opening_moves_note_quote([E4], False))["state"] == "not_configured"
    assert api.get_opening_note_quote(FAMILY, 0, "2", False)["ok"] is False
    assert api.get_opening_note_quote(FAMILY, None, 2, False)["ok"] is False


def test_the_prefetch_plan_takes_what_the_dialog_sends(api: Any) -> None:
    for args in ((FAMILY, "standard", None, None, True), (FAMILY, "custom", 3, 8, False)):
        plan = ok(api.get_opening_prefetch_plan(*args))
        assert plan["llm"] is False and plan["lines"] >= 1 and isinstance(plan["warnings"], list)
    assert api.get_opening_prefetch_plan(FAMILY, "standard", None, None, None)["ok"] is False


def test_a_wrong_moves_argument_is_refused(api: Any) -> None:
    assert api.get_opening_deviation("white", E4, "a6")["ok"] is False
    assert api.add_opening_deviation("green", [E4], "a6", "d2d4")["ok"] is False
    assert api.get_opening_deviation("white", [E4], 7)["ok"] is False


def test_practice_state_is_lists_of_lists_of_strings_over_the_bridge(api: Any) -> None:
    ok(api.add_opening_deviation("white", [E4], "a7a6", "d2d4"))
    s = ok(api.start_practice("white", "all", None))
    assert s["replies"] == [] and s["correct_moves"] == [] and s["state"] == "your_move"
    s = ok(api.play_practice_move(s["session_id"], E4))
    assert s["replies"] == [["a7a6", "a6"]]
    s = ok(api.show_practice_answer(s["session_id"]))
    assert s["correct_moves"] == [["d2d4", "d4"]] and s["reason_prompt"] is None
    s = ok(api.continue_practice(s["session_id"]))
    assert s["state"] == "line_end"
    s = ok(api.continue_practice(s["session_id"]))
    assert s["state"] == "finished"
    ok(api.end_practice(s["session_id"]))


def test_a_wrong_move_brings_the_prompt_and_its_reason_goes_through_the_check(api: Any) -> None:
    ok(api.add_opening_deviation("white", [E4], "a7a6", "d2d4"))
    s = ok(api.start_practice("white", "due", None))
    s = ok(api.play_practice_move(s["session_id"], "a2a3"))
    assert s["state"] == "wrong" and s["wrong_fen"] and s["reason_prompt"]["source"] == "opening"
    reason = s["reason_prompt"]["reasons"][0]["key"]
    ok(api.set_practice_reason(s["attempt_id"], reason, None))
    ok(api.set_practice_reason(s["attempt_id"], reason, "A short note"))
    assert api.set_practice_reason(str(s["attempt_id"]), reason, None)["ok"] is False


def test_the_rest_of_the_repertoire_calls_take_what_the_view_sends(api: Any) -> None:
    ok(api.set_opening_settings("custom", 1, 4, False))
    added = ok(api.add_repertoire_lines("white", FAMILY, [0, 1]))
    assert added["added"] > 0
    rep = ok(api.get_repertoire("white"))
    row = rep["rows"][0]
    assert ok(api.preview_repertoire_removal("white", row["position_key"], row["move_uci"]))
    ok(api.set_repertoire_main("white", row["position_key"], row["move_uci"]))
    ok(api.move_repertoire_move("white", row["position_key"], row["move_uci"], "down"))
    assert api.move_repertoire_move("white", row["position_key"], row["move_uci"], "left")["ok"] is False
    assert ok(api.get_practice_summary("white"))["positions"] > 0
    ok(api.start_practice("white", "new", rep["openings"][0]["id"]))
    assert ok(api.get_opening_stats("white"))[0]["name"] == FAMILY
    assert ok(api.remove_repertoire_move("white", row["position_key"], row["move_uci"]))["rows"] == []


def test_a_build_takes_the_dialogs_limits_including_a_fraction_and_a_zero(api: Any) -> None:
    for share in (0.05, 0, 0.5):
        job = ok(
            api.start_repertoire_build(
                "white", FAMILY, {"max_moves": 6, "min_share": share, "max_replies": 1, "max_positions": 5}
            )
        )
        st = api._runner.wait(job, 30)
        assert st.state == "done", st
        p = ok(api.get_repertoire_proposal(st.message))
        assert p["color"] == "white" and p["moves"]
        ok(api.discard_repertoire_proposal(p["id"]))
    assert api.start_repertoire_build("white", FAMILY, "12")["ok"] is False


def test_the_engine_and_the_analysis_call_take_a_chess_js_fen(api: Any) -> None:
    a = ok(api.analyze_opening_position(START, "panel", "white"))
    assert a["lines"] and a["fen"] == START
    assert api.analyze_opening_position(START, "elsewhere", "white")["ok"] is False


def test_a_note_lookup_takes_the_position_key_the_view_builds(api: Any) -> None:
    assert ok(api.get_opening_note(START_KEY, E4, "move")) is None
    assert ok(api.get_opening_note(START_KEY, "", "overview")) is None
    assert api.get_opening_note(START_KEY, E4, "study")["ok"] is False


def test_coach_link_matching_goes_through_the_check(api: Any) -> None:
    assert ok(api.match_opening_family("Italian Game: Giuoco Piano")) == FAMILY
    assert ok(api.match_opening_family("Nothing like this")) is None
    assert api.match_opening_family(None)["ok"] is False


def test_a_session_limited_to_one_branch_goes_through_the_check(api: Any) -> None:
    """v0.13-B17: FR-12.10's one branch reaches the bridge and limits what comes up."""
    from weaksquare.core.openings import position_key
    from weaksquare.core.repertoire import NewMove

    def line(*ucis: str) -> list[NewMove]:
        import chess

        board = chess.Board()
        out = []
        for uci in ucis:
            move = chess.Move.from_uci(uci)
            out.append(NewMove(position_key(board), uci, board.san(move), "you"))
            board.push(move)
        return out

    repo = api._repertoire._repo
    repo.add_moves("white", line("e2e4", "e7e5", "g1f3"), "2026-11-01T12:00:00+00:00")
    repo.add_moves("white", line("e2e4", "c7c5", "b1c3"), "2026-11-01T12:00:00+00:00")
    found = api.get_practice_branches("white", None)
    assert found["ok"]
    labels = {b["label"]: b["position_key"] for b in found["data"]}
    assert set(labels) == {"1. e4 e5", "1. e4 c5"}
    started = api.start_practice("white", "all", None, labels["1. e4 c5"])
    assert started["ok"] and started["data"]["remaining"] == 1
    assert api.start_practice("white", "all", None, "not a position")["ok"] is False
    assert api.get_practice_branches("white", 12345)["ok"] is False


def test_a_line_with_no_split_offers_no_branch(api: Any) -> None:
    api._openings.set_scope("custom", 0, 4)
    api._repertoire.add_lines("white", FAMILY, [0])
    assert api.get_practice_branches("white", None)["data"] == []
