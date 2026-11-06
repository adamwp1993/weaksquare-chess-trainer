"""QA v0.13 in the real app (WebView2 over CDP), real bridge, real Stockfish from the dev install, real book import, temp data
folder, signed out, no AI key. Nothing goes off the PC: the Wikibooks panel is never opened and no line is sent anywhere.

This is the first time the Openings page runs against the real client rather than the mock. A test exposing an open bug is
xfail with its ID."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v010_real_app import _call, _ok, _wait_job
from tests.smoke.test_qa_v012_round2_real_app import _engine, _ready, _source

pytestmark = pytest.mark.smoke
ART = Path("tests/e2e/artifacts")
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w"


def _shot(page: Any, name: str) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v013-real-{name}.png"), full_page=True)


@contextmanager
def _app(pw: Any, data_dir: Path) -> Iterator[Any]:
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            page.errors = []
            page.on("pageerror", lambda e: page.errors.append(str(e)))
            yield page
    finally:
        app.close()


def _folder(tmp_path: Path, fixture_puzzles_db: Path) -> Path:
    src = _source()
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    _engine(src, data_dir)
    return data_dir


def _openings(page: Any) -> None:
    for _ in range(100):
        if _ok(_call(page, "get_engine_status"))["state"] == "ready":
            break
        page.wait_for_timeout(200)
    _ok(_call(page, "set_engine_settings", 0.2, None, None))
    page.get_by_test_id("nav-openings").click()
    page.get_by_test_id("openings-view").wait_for(timeout=120_000)


def _pick(page: Any, name: str) -> None:
    page.get_by_test_id("openings-search").fill(name)
    page.locator(f"[data-testid=opening-family][data-name='{name}']").click()
    page.get_by_test_id("opening-lines").wait_for()
    page.get_by_test_id("learn-board").wait_for()


def _fen(page: Any) -> str:
    return page.get_by_test_id("board").get_attribute("data-fen") or ""


def _stop_at_book(page: Any) -> None:
    """On the screen when an opening is open, otherwise through the bridge, as the same call."""
    if page.get_by_test_id("opening-extend").count():
        page.get_by_test_id("opening-extend").get_by_text("Stop at the book's end").click()
        page.wait_for_timeout(300)
    else:
        _ok(_call(page, "set_opening_settings", "standard", None, None, False))


def test_qa13_the_book_imports_once_and_browses_and_real_settings_are_accepted(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        _openings(page)
        assert _ok(_call(page, "get_opening_book_status")) == {"ready": True, "lines": 3865}
        assert len(_ok(_call(page, "get_opening_families", ""))) == 149
        page.get_by_test_id("openings-search").fill("c50")
        page.locator("[data-testid=opening-family][data-name='Italian Game']").wait_for()
        page.get_by_test_id("openings-search").fill("nothing like this")
        page.get_by_text("No opening matches that.").wait_for()
        _pick(page, "Italian Game")
        _shot(page, "book")
        for label, count in (("Light", 2), ("Standard", 4), ("Deep", 7)):
            page.get_by_test_id("opening-preset").get_by_text(label).click()
            page.get_by_test_id(f"opening-line-{count - 1}").wait_for()
            page.get_by_test_id(f"opening-line-{count}").wait_for(state="detached")
        page.get_by_test_id("opening-preset").get_by_text("Custom").click()
        page.wait_for_timeout(1000)  # let the lines settle first: changing them faster is v0.13-B27
        page.get_by_test_id("opening-sub-lines").fill("0")
        page.get_by_test_id("opening-line-1").wait_for(state="detached")
        assert page.get_by_test_id("opening-error").count() == 0
        # The real client's own shapes, over the real bridge: null, float inside a dict, list of ints.
        assert _ok(_call(page, "set_opening_settings", "light", None, None, True))["scope"]["sub_lines"] == 1
        assert _ok(_call(page, "get_opening_note_quote", "Italian Game", 0, None, False))["state"] == "not_configured"
        plan = _ok(_call(page, "get_opening_prefetch_plan", "Italian Game", "standard", None, None, False))
        assert plan["llm"] is False and plan["lines"] == 4
        assert _ok(_call(page, "set_opening_sources", True, "lichess", [1600, 1800]))["explorer_ratings"] == [
            1600,
            1800,
        ]
        assert _call(page, "set_opening_settings", "custom", "x", None, None)["ok"] is False
        assert page.errors == []
    # A restart doesn't import again, and what you set is still there.
    with _app(pw, data_dir) as page:
        assert _ok(_call(page, "get_opening_book_status"))["ready"] is True
        assert _ok(_call(page, "get_opening_settings"))["scope"]["preset"] == "light"


def test_qa13_learn_what_if_repertoire_practice_and_stats_as_white(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        _openings(page)
        _pick(page, "Italian Game")
        _stop_at_book(page)
        # Step through, with the engine on the real position.
        page.get_by_test_id("learn-forward").click()
        assert " b " in _fen(page)
        page.get_by_test_id("engine-line").first.wait_for(timeout=30_000)

        # What if, on the board: real replies, the preview, Clear, then typed.
        at = _fen(page)
        play(page, "a7a6", "white")
        page.get_by_test_id("what-if-replies").filter(has_text="a6").wait_for(timeout=30_000)
        assert page.get_by_test_id("what-if-reply").count() == 3 and "/p" in _fen(page)
        _shot(page, "what-if")
        # Clear after a board move doesn't work (v0.13-B1, tests/e2e/test_qa_v013_ui.py): leave and come back.
        page.get_by_test_id("learn-back").click()
        page.get_by_test_id("what-if").wait_for(state="detached")
        page.get_by_test_id("learn-forward").click()
        page.get_by_test_id("what-if").wait_for()
        assert _fen(page) == at
        page.get_by_test_id("what-if-move").fill("Ke5")
        page.get_by_test_id("what-if-go").click()
        page.get_by_test_id("what-if-error").filter(has_text="legal").wait_for()
        page.get_by_test_id("what-if-move").fill("a6")
        page.get_by_test_id("what-if-go").click()
        page.get_by_test_id("what-if-replies").wait_for(timeout=30_000)
        page.get_by_test_id("what-if-clear").click()
        page.get_by_test_id("what-if-replies").wait_for(state="detached")
        assert _fen(page) == at
        page.get_by_test_id("what-if-move").fill("a6")
        page.get_by_test_id("what-if-go").click()
        page.get_by_test_id("what-if-replies").wait_for(timeout=30_000)
        page.get_by_test_id("what-if-add").click()
        page.get_by_test_id("what-if-saved").wait_for()

        # Add a line and look after the repertoire.
        page.get_by_test_id("opening-add-0").click()
        page.get_by_test_id("opening-added").wait_for()
        page.get_by_test_id("openings-tab-repertoire").click()
        rows = page.get_by_test_id("repertoire-rows")
        rows.locator("[data-testid=repertoire-row][data-san=a6]").filter(has_text="You").wait_for()
        rows.locator("[data-testid=repertoire-row][data-san=e4]").filter(has_text="Main").wait_for()
        _shot(page, "repertoire")
        rep = _ok(_call(page, "get_repertoire", "white"))
        assert {o["name"] for o in rep["openings"]} == {"Italian Game"}

        # Practice: real session, wrong move, real refutation, a reason, carry on to the end.
        page.get_by_test_id("openings-tab-practice").click()
        page.get_by_test_id("practice-summary").filter(has_text="0 due").wait_for()
        page.get_by_test_id("practice-mode").get_by_text("All").click()
        page.get_by_test_id("practice-begin").click()
        page.get_by_test_id("practice-session").wait_for()
        play(page, "a2a3", "white")
        page.locator("[data-testid=practice-session][data-state=wrong]").wait_for()
        assert "e4" in page.get_by_test_id("practice-correct").inner_text()
        page.get_by_test_id("practice-refutation").wait_for(timeout=30_000)
        page.get_by_test_id("reason-chips").wait_for()
        _shot(page, "practice-wrong")
        page.locator("[data-testid^=reason-]").filter(has_text="1").first.click()
        page.get_by_test_id("reason-saved").wait_for()
        page.get_by_test_id("practice-continue").click()
        done = False
        for _ in range(60):
            state = page.get_by_test_id("practice-session")
            if page.get_by_test_id("practice-start").count():
                done = True
                break
            s = state.get_attribute("data-state")
            if s == "your_move":
                page.get_by_test_id("practice-show").click()
            elif s == "helped":
                page.get_by_test_id("practice-continue").click()
            elif s == "line_end":
                page.get_by_test_id("practice-next-line").click()
            page.wait_for_timeout(250)
        assert done
        page.get_by_test_id("practice-finished").wait_for()
        _shot(page, "practice-finished")

        # Stats show it, and Coach-side and puzzle stats didn't move.
        page.get_by_test_id("openings-tab-stats").click()
        page.get_by_test_id("opening-stat").first.wait_for()
        assert "Italian Game" in page.get_by_test_id("opening-stat").first.inner_text()
        _shot(page, "stats")
        assert _ok(_call(page, "get_practice_summary", "white"))["positions"] > 0
        assert page.errors == []
    with sqlite3.connect(data_dir / "user.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM opening_attempts").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mistake_reasons WHERE source = 'opening'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mistake_reasons WHERE source <> 'opening'").fetchone()[0] == 0
    # A restart keeps the schedule, and the repertoire.
    with _app(pw, data_dir) as page:
        assert _ok(_call(page, "get_practice_summary", "white"))["due"] == 0
        assert _ok(_call(page, "get_repertoire", "white"))["rows"]


def test_qa13_play_along_castles_and_plays_as_black(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Ruy Lopez")
        lines = _ok(_call(page, "get_opening_lines", "Ruy Lopez"))["lines"]
        index, line = next(
            (i, ln)
            for i, ln in enumerate(lines)
            if any(m["san"] == "O-O" and i % 2 == 0 for i, m in enumerate(ln["moves"]))
        )
        page.get_by_test_id(f"opening-line-{index}").click()
        page.get_by_test_id("learn-mode").get_by_text("Play along").click()
        play(page, "d2d4", "white")  # not this line's: it goes back and nudges
        page.get_by_test_id("learn-nudge").wait_for()
        for i, m in enumerate(line["moves"]):
            if i % 2 == 0:
                page.wait_for_timeout(500)
                play(page, m["uci"], "white")  # castling is e1g1, here and in the book
        page.get_by_test_id("learn-play-status").filter(has_text="end of this line").wait_for()
        assert page.locator("[data-testid=learn-board][data-tries='1']").count() == 1
        _shot(page, "play-along-end")

        page.get_by_test_id("opening-color").get_by_text("As Black").click()
        page.locator("[data-testid=board].orientation-black").wait_for()
        page.get_by_test_id("learn-mode").get_by_text("Play along").click()
        page.wait_for_function("() => document.querySelector('[data-testid=board]').dataset.fen.includes(' b ')")
        assert page.errors == []


def test_qa13_extending_the_lines_labels_stockfish_and_stop_removes_them(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _ok(_call(page, "set_opening_settings", "custom", 0, 14, True))
        _pick(page, "Italian Game")
        before = len(_ok(_call(page, "get_opening_lines", "Italian Game"))["lines"][0]["moves"])
        page.get_by_test_id("opening-extend-run").click()
        page.locator("[data-testid=learn-moves] [data-source=engine]").first.wait_for(timeout=120_000)
        assert "Stockfish" in page.get_by_test_id("learn-moves").inner_text()
        moves = _ok(_call(page, "get_opening_lines", "Italian Game"))["lines"][0]["moves"]
        assert len(moves) == 28 > before and {m["source"] for m in moves} == {"book", "engine"}
        _shot(page, "extended")
        _stop_at_book(page)
        page.locator("[data-testid=learn-moves] [data-source=engine]").first.wait_for(state="detached")
        assert page.errors == []


def test_qa13_prefetch_with_no_ai_saves_engine_evals_and_cancels(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-prefetch").click()
        page.get_by_test_id("prefetch-plan").wait_for()
        blurb = page.get_by_test_id("prefetch-blurb").inner_text()
        assert "Stockfish" in blurb and page.get_by_test_id("prefetch-usage").count() == 0
        _shot(page, "prefetch-no-ai")
        page.get_by_test_id("prefetch-preset").get_by_text("Deep").click()
        page.get_by_test_id("prefetch-counts").filter(has_text="7 lines").wait_for()
        page.get_by_test_id("prefetch-confirm").click()
        page.get_by_test_id("prefetch-running").wait_for()
        page.get_by_test_id("prefetch-cancel").click()
        page.get_by_test_id("prefetch-cancelled").wait_for(timeout=30_000)
        page.get_by_test_id("prefetch-preset").get_by_text("Light").click()
        page.get_by_test_id("prefetch-counts").filter(has_text="2 lines").wait_for()
        page.get_by_test_id("prefetch-confirm").click()
        page.get_by_test_id("prefetch-done").wait_for(timeout=120_000)
        assert "no notes" in page.get_by_test_id("prefetch-done").inner_text()
        assert page.errors == []


def test_qa13_build_my_repertoire_as_black_reviews_then_saves_then_drills(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        _openings(page)
        _pick(page, "Caro-Kann Defense")
        page.get_by_test_id("opening-color").get_by_text("As Black").click()
        page.locator("[data-testid=board].orientation-black").wait_for()
        page.get_by_test_id("opening-build").click()
        page.get_by_test_id("build-moves").fill("5")
        page.get_by_test_id("build-positions").fill("12")
        page.get_by_test_id("build-start").click()
        page.get_by_test_id("build-moves-list").wait_for(timeout=180_000)
        _shot(page, "build-review")
        assert _ok(_call(page, "get_repertoire", "black"))["rows"] == []  # nothing before review
        n = page.get_by_test_id("build-move").count()
        assert n >= 3
        page.get_by_test_id("build-save").click()
        page.get_by_test_id("build-saved").wait_for()
        page.keyboard.press("Escape")
        rep = _ok(_call(page, "get_repertoire", "black"))
        assert len(rep["rows"]) >= 3 and rep["openings"][0]["name"] == "Caro-Kann Defense"
        # The eval's side, with the real engine: a real blunder as Black must not count as close.
        _ok(_call(page, "set_practice_tolerance", True))
        s = _ok(_call(page, "start_practice", "black", "all", None))
        assert s["state"] == "your_move" and s["replies"] and " b " in s["fen"]
        s = _ok(_call(page, "play_practice_move", s["session_id"], "g7g5"))
        assert s["state"] == "wrong", s
        assert page.errors == []


@pytest.mark.xfail(
    reason="v0.13-B27: each change of scope reloads the lines with nothing to drop an older answer, and a longer list comes "
    "back last: the list shows 7 lines while the setting says 1. Only the real client shows it: the mock answers in order",
    strict=False,
)
def test_qa13_a_quick_second_change_of_scope_shows_its_own_lines(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-preset").get_by_text("Deep").click()
        page.get_by_test_id("opening-line-6").wait_for()
        page.get_by_test_id("opening-preset").get_by_text("Custom").click()
        page.get_by_test_id("opening-sub-lines").fill("0")
        page.wait_for_timeout(2500)
        assert _ok(_call(page, "get_opening_settings"))["scope"]["sub_lines"] == 0
        assert page.get_by_test_id("opening-lines").locator("[data-testid^=opening-line-]").count() == 1


def _dup_lines(page: Any) -> list[int]:
    lines = _ok(_call(page, "get_opening_lines", "Caro-Kann Defense"))["lines"]
    seen: dict[tuple[str, int], int] = {}
    for i, ln in enumerate(lines):
        k = (ln["name"], len(ln["moves"]))
        if k in seen:
            return [seen[k], i]
        seen[k] = i
    return []


@pytest.mark.xfail(
    reason="v0.13-B21: the Learn board's key is the line's name and length. Two different lines can share both (Caro-Kann, "
    "Standard), so choosing the other keeps your step, mode and note",
    strict=True,
)
def test_qa13_choosing_another_line_with_the_same_name_and_length_starts_it_over(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Caro-Kann Defense")
        a, b = _dup_lines(page)
        page.get_by_test_id(f"opening-line-{a}").click()
        for _ in range(3):
            page.get_by_test_id("learn-forward").click()
        page.get_by_test_id(f"opening-line-{b}").click()
        page.wait_for_timeout(300)
        assert _fen(page).startswith(START)


@pytest.mark.xfail(
    reason="v0.13-B22: at a line's end the last note's arrows stay on the board: nothing clears them once its panel closes",
    strict=True,
)
def test_qa13_a_notes_arrows_leave_with_the_note(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Italian Game")
        line = _ok(_call(page, "get_opening_lines", "Italian Game"))["lines"][0]
        last = line["moves"][-1]
        body = json.dumps(
            {
                "sections": [["Why this move", "An invented note."]],
                "annotations": [{"kind": "arrow", "orig": "a2", "dest": "a4", "color": "green"}],
            }
        )
        with sqlite3.connect(data_dir / "user.db") as conn:
            conn.execute(
                "INSERT INTO opening_notes (position_key, move_uci, kind, provider, model, prompt_version, body_json,"
                " sources_json, input_tokens, output_tokens, cost_usd, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    last["position_key"],
                    last["uci"],
                    "move",
                    "anthropic",
                    "x",
                    1,
                    body,
                    "[]",
                    0,
                    0,
                    0.0,
                    "2026-11-06T12:00:00+00:00",
                ),
            )
        page.get_by_test_id(f"learn-move-{len(line['moves']) - 2}").click()
        board = page.get_by_test_id("board")
        for _ in range(50):
            if board.get_attribute("data-shapes"):
                break
            time.sleep(0.1)
        assert board.get_attribute("data-shapes") == "green:a2a4"
        page.get_by_test_id("learn-forward").click()
        page.wait_for_timeout(500)
        assert board.get_attribute("data-shapes") == ""


def test_qa13_a_job_message_really_is_the_proposal_id(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    """The mock's job says so. The real runner has to as well, or the review never opens."""
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        job = _ok(
            _call(
                page,
                "start_repertoire_build",
                "white",
                "Italian Game",
                {"max_moves": 5, "min_share": 0.05, "max_replies": 2, "max_positions": 5},
            )
        )
        st = _wait_job(page, job)
        assert st["state"] == "done", st
        p = _ok(_call(page, "get_repertoire_proposal", st["message"]))
        assert p["color"] == "white" and p["moves"]
        _ok(_call(page, "discard_repertoire_proposal", p["id"]))
        assert _call(page, "get_repertoire_proposal", p["id"])["ok"] is False
