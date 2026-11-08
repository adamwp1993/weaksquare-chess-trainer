"""v0.14 bridge methods for studies (REQUIREMENTS §19) through the real Api and services, with the fake studies client:
the flattened tree the UI walks, summaries, links built by the app, and the Lichess window's buttons."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import chess
import pytest

from tests.helpers import FakeDesktop, build_api
from weaksquare.adapters.db.migrate import migrate
from weaksquare.config import MIGRATIONS_DIR, Paths
from weaksquare.core.clock import FixedClock


def data(result: dict[str, Any]) -> Any:
    assert result["ok"], result
    return result["data"]


@pytest.fixture
def api_and_desktop(paths: Paths):  # type: ignore[no-untyped-def]
    clock = FixedClock(datetime(2026, 11, 7, 12, 0, tzinfo=UTC))
    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    desktop = FakeDesktop()
    api = build_api(paths, clock, desktop=desktop)
    return api, desktop


def _add(api, text: str) -> str:  # type: ignore[no-untyped-def]
    job = data(api.add_study(text))
    st = api._runner.wait(job, 10)
    assert st is not None and st.state == "done", st
    return str(data(api.get_study_add_result(job))["study_id"])


def test_chapter_tree_is_flattened_with_positions(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, _ = api_and_desktop
    sid = _add(api, "https://lichess.org/study/TestNm02")
    moves = data(api.get_study_chapter(sid, "Chap0001"))["moves"]
    root = moves[0]
    assert (root["parent"], root["san"], root["ply"]) == (None, None, 0)
    assert "https://example.com/notes" in root["comment"]
    assert root["shapes"] == [{"orig": "e5", "dest": None, "color": "red"}]  # the z9 highlight was dropped
    # Ids are pre-order, parents and children agree, and every FEN is the position after its move.
    for m in moves:
        for c in m["children"]:
            assert moves[c]["parent"] == m["id"]
        if m["parent"] is not None:
            board = chess.Board(moves[m["parent"]]["fen"])
            board.push_uci(m["uci"])
            assert board.fen() == m["fen"]
    # 2. Nc3 has the main line and the 2...Nc6 side line, with its own nested side line.
    nc3 = next(m for m in moves if m["san"] == "Nc3")
    assert [moves[c]["san"] for c in nc3["children"]] == ["Nf6", "Nc6"]
    nc6 = moves[nc3["children"][1]]
    assert [moves[c]["san"] for c in nc6["children"]] == ["f4", "Bc4"]


def test_text_chapter_keeps_its_board_as_given(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, _ = api_and_desktop
    sid = _add(api, "TestNm02")
    ch = data(api.get_study_chapter(sid, "Chap0003"))
    assert ch["info"]["text_only"] and len(ch["moves"]) == 1
    assert ch["moves"][0]["fen"] == "8/8/8/8/8/8/8/8 w - - 0 1"


def test_summary_and_links_built_by_the_app(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, desktop = api_and_desktop
    sid = _add(api, "TestGb01")
    s = data(api.get_study(sid))["summary"]
    assert (s["url"], s["status"], s["playable"]) == ("https://lichess.org/study/TestGb01", "new", 2)
    data(api.set_study_place(sid, "Chap0002", ["e2e4", "c7c6"]))
    s = data(api.get_study(sid))["summary"]
    assert (s["status"], s["place_chapter_title"]) == ("in_progress", "The plan")
    assert data(api.get_study_continue(sid))["path"] == ["e2e4", "c7c6"]
    assert not api.set_study_place(sid, "Chap0002", "e2e4")["ok"]  # a path must be a list
    data(api.open_study_on_lichess(sid, "Chap0002"))
    data(api.open_lichess_studies_in_browser())
    assert desktop.urls[-2:] == ["https://lichess.org/study/TestGb01/Chap0002", "https://lichess.org/study"]
    assert not api.open_study_on_lichess("../../x", None)["ok"]


def test_lichess_window_buttons_use_the_window(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, _ = api_and_desktop
    assert data(api.is_lichess_window_open()) is False
    assert data(api.open_lichess_window()) is True
    assert data(api.open_lichess_window()) is False  # brought forward, not a second window
    assert data(api.is_lichess_window_open()) is True
    data(api.close_lichess_window())
    assert data(api.is_lichess_window_open()) is False


def test_starter_list_ships_and_is_valid(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    """FR-13.6: the shipped file parses with the strict loader (only links, titles, authors and openings)."""
    api, _ = api_and_desktop
    for e in data(api.get_study_starter_list()):
        assert e["url"] == f"https://lichess.org/study/{e['study_id']}"


# ---- Add to my repertoire (FR-13.11) -----------------------------------------------------------------------------
def test_add_to_repertoire_stores_study_moves_and_practice_drills_them(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, _ = api_and_desktop
    sid = _add(api, "TestNm02")
    p = data(api.preview_study_repertoire(sid, "Chap0001", "white", False))
    assert (p["yours"], p["theirs"], p["already"], p["unreachable"], p["conflicts"]) == (4, 4, 0, 0, [])
    assert data(api.save_study_repertoire(p["id"], {})) == {"added": 8, "kept": 0}
    rows = data(api.get_repertoire("white"))["rows"]
    assert [r["san"] for r in rows] == ["e4", "e5", "Nc3", "Nf6", "f4", "d5", "fxe5", "Nxe4"]
    assert {r["source"] for r in rows} == {"study"}
    summary = data(api.get_practice_summary("white"))
    assert summary["positions"] == 4 and summary["new"] == 4  # your four decision points
    state = data(api.start_practice("white", "new"))
    assert state["state"] == "your_move"
    # A preview is used once.
    assert api.save_study_repertoire(p["id"], {})["error"]["code"] == "no_preview"


def test_side_lines_and_the_whole_study(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, _ = api_and_desktop
    sid = _add(api, "TestNm02")
    p = data(api.preview_study_repertoire(sid, None, "white", True))
    assert p["chapters"] == ["Main line"]
    assert any("Broken" in s for s in p["skipped"]) and any("Thanks" in s for s in p["skipped"])
    # Side lines add 2...Nc6 with White's 3.f4 (then 3...exf4) and 3.Bc4: White e4 Nc3 f4 fxe5 f4 Bc4, Black e5 Nf6 d5
    # Nxe4 Nc6 exf4.
    assert (p["yours"], p["theirs"]) == (6, 6)


def test_a_conflict_keeps_your_move_unless_you_choose_the_study(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    api, _ = api_and_desktop
    from weaksquare.core.repertoire import line_to_moves

    repo = api._repertoire._repo
    repo.add_moves("white", line_to_moves([("e2e4", "you"), ("e7e5", "you"), ("g1f3", "you")]), "2026-11-07")
    sid = _add(api, "TestNm02")
    p = data(api.preview_study_repertoire(sid, "Chap0001", "white", False))
    [c] = p["conflicts"]
    assert (c["path"], c["yours"], c["study"]) == (["e4", "e5"], ["Nf3"], ["Nc3"])
    assert p["already"] == 2
    # Keep mine (the default): nothing behind Nc3 is added.
    assert data(api.save_study_repertoire(p["id"], {})) == {"added": 0, "kept": 0}
    # Use the study's: Nc3 becomes main, Nf3 stays.
    p = data(api.preview_study_repertoire(sid, "Chap0001", "white", False))
    assert data(api.save_study_repertoire(p["id"], {c["position_key"]: "study"}))["added"] == 6
    rows = data(api.get_repertoire("white"))["rows"]
    at = [r for r in rows if r["san"] in ("Nf3", "Nc3")]
    assert {r["san"]: r["is_main"] for r in at} == {"Nc3": True, "Nf3": False}
    assert not api.save_study_repertoire("study-rep-x", {"bogus": "study"})["ok"]


def test_study_text_never_reaches_an_ai(api_and_desktop) -> None:  # type: ignore[no-untyped-def]
    """FR-13.12: adding, reading, updating and adding to a repertoire send nothing to an AI provider."""
    api, _ = api_and_desktop
    providers = api._llm_settings._providers  # the fake providers (tests/helpers.fake_service_kwargs)
    sid = _add(api, "TestNm02")
    data(api.get_study_chapter(sid, "Chap0001"))
    api._runner.wait(data(api.check_study_updates(sid)), 10)
    p = data(api.preview_study_repertoire(sid, "Chap0001", "white", True))
    data(api.save_study_repertoire(p["id"], {}))
    assert all(not prov.requests for prov in providers.values())
