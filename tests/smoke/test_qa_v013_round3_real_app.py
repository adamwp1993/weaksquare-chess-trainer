"""QA v0.13 round 3 in the real app: Practice's step-through on the real board with real Stockfish, a late answer about an earlier
miss, the session limit's own wording, and the prefetch dialog with answers held back. Temp data folder, signed out, no AI key,
nothing sent. A test exposing an open bug is xfail with its ID."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import chess
import pytest

from tests.e2e.conftest import play
from tests.smoke.test_qa_v010_real_app import _call, _ok
from tests.smoke.test_qa_v013_real_app import _app, _fen, _folder, _openings, _pick, _shot, _stop_at_book
from tests.smoke.test_qa_v013_round2_real_app import _pieces

pytestmark = pytest.mark.smoke


def _practice(page: Any, family: str = "Italian Game", color: str = "white") -> None:
    _openings(page)
    _stop_at_book(page)
    _pick(page, family)
    if color == "black":
        page.get_by_test_id("opening-color").get_by_text("As Black").click()
        page.locator("[data-testid=board].orientation-black").wait_for()
    page.get_by_test_id("opening-add-0").click()
    page.get_by_test_id("opening-added").wait_for()
    page.get_by_test_id("openings-tab-practice").click()
    if color == "black":
        page.get_by_test_id("practice-color").get_by_text("Black").click()
        page.get_by_test_id("practice-summary").wait_for()
    page.get_by_test_id("practice-mode").get_by_text("All").click()
    page.get_by_test_id("practice-begin").click()
    page.get_by_test_id("practice-your-move").wait_for()


def _steps(page: Any) -> int:
    text = page.get_by_test_id("answer-step").inner_text()
    found = re.match(r"(\d+)/(\d+)", text)
    return int(found.group(2)) if found else 0


def test_qa13r3_stepping_through_stockfishs_answer_on_the_real_board(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _practice(page)
        before = _fen(page)
        play(page, "a2a3", "white")
        page.locator("[data-testid=practice-session][data-state=wrong]").wait_for()
        page.get_by_test_id("practice-refutation").wait_for(timeout=30_000)
        assert _fen(page) == before  # the piece goes back until you ask
        page.get_by_test_id("practice-refutation-step").click()
        player = page.get_by_test_id("answer-player")
        forward = player.get_by_role("button", name="Forward")
        back = player.get_by_role("button", name="Back")

        # Start: the position after what you played.
        assert page.get_by_test_id("answer-step").inner_text() == "Start"
        board = chess.Board(before)
        board.push_uci("a2a3")
        assert _fen(page).split()[:4] == board.fen().split()[:4]
        page.wait_for_timeout(350)
        assert "a3" in _pieces(page) and "a2" not in _pieces(page)

        # Every step forward is one legal move on from the last, on the board as well as in React.
        seen = [_fen(page)]
        while forward.is_enabled():
            forward.click()
            page.wait_for_timeout(300)
            now = _fen(page)
            assert any(_after(seen[-1], m) == now.split()[:4] for m in chess.Board(seen[-1]).legal_moves), now
            drawn = _pieces(page)
            assert len(drawn) == len(chess.Board(now).piece_map())
            seen.append(now)
        assert 2 <= len(seen) <= 9
        assert forward.is_disabled()
        _shot(page, "r3-step-end")

        # Back the same way, to the start.
        for expected in reversed(seen[:-1]):
            back.click()
            page.wait_for_timeout(100)
            assert _fen(page) == expected
        assert back.is_disabled()

        # A reason while you're looking at it, then Back to the position, then on.
        forward.click()
        page.locator("[data-testid^=reason-]").filter(has_text="1").first.click()
        page.get_by_test_id("reason-saved").wait_for()
        assert _fen(page) == seen[1]  # choosing a reason doesn't move the board
        page.get_by_test_id("practice-refutation-close").click()
        page.wait_for_function("(f) => document.querySelector('[data-testid=board]').dataset.fen === f", arg=before)
        assert page.get_by_test_id("answer-player").count() == 0
        page.wait_for_timeout(350)
        assert "a2" in _pieces(page) and "a3" not in _pieces(page)

        # Continue from part-way through a step-through puts the line right.
        page.get_by_test_id("practice-refutation-step").click()
        page.get_by_test_id("answer-player").get_by_role("button", name="Forward").click()
        page.get_by_test_id("practice-continue").click()
        page.get_by_test_id("practice-your-move").wait_for()
        assert page.get_by_test_id("answer-player").count() == 0
        page.wait_for_timeout(350)
        assert "e4" in _pieces(page) and "e5" in _pieces(page) and "a3" not in _pieces(page)
        assert page.errors == []


def _after(fen: str, move: chess.Move) -> list[str]:
    b = chess.Board(fen)
    b.push(move)
    return b.fen().split()[:4]


def test_qa13r3_stepping_through_as_black_keeps_your_side_of_the_board(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _practice(page, "Caro-Kann Defense", "black")
        fen = _fen(page)
        assert " b " in fen
        wrong = next(m for m in chess.Board(fen).legal_moves if m.uci() == "g7g5")
        play(page, wrong.uci(), "black")
        page.get_by_test_id("practice-refutation").wait_for(timeout=30_000)
        page.get_by_test_id("practice-refutation-step").click()
        page.get_by_test_id("answer-player").get_by_role("button", name="Forward").click()
        page.locator("[data-testid=answer-step]").filter(has_text="1/").wait_for()
        assert page.locator("[data-testid=board].orientation-black").count() == 1
        assert " b " in _fen(page)
        _shot(page, "r3-step-black")
        assert page.errors == []


@pytest.mark.xfail(
    reason="v0.13-B35: a late answer about an earlier miss is ignored on screen, but it still replaces the answer about this "
    "one, so this miss loses its refutation and its step-through (FR-12.9)",
    strict=True,
)
def test_qa13r3_a_late_answer_about_an_earlier_miss_leaves_this_ones(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _practice(page)
        page.evaluate(
            """() => {
                const api = window.pywebview.api;
                const real = api.analyze_opening_position.bind(api);
                let first = true;
                api.analyze_opening_position = (...a) => {
                    const hold = first ? 3000 : 0;
                    first = false;
                    return new Promise((ok) => setTimeout(ok, hold)).then(() => real(...a));
                };
            }"""
        )
        play(page, "a2a3", "white")  # its answer is held back
        page.locator("[data-testid=practice-session][data-state=wrong]").wait_for()
        page.get_by_test_id("practice-continue").click()
        page.get_by_test_id("practice-your-move").wait_for()
        play(page, "a2a3", "white")  # a second miss, answered first
        page.locator("[data-testid=practice-session][data-state=wrong]").wait_for()
        page.get_by_test_id("practice-refutation").wait_for(timeout=30_000)
        page.wait_for_timeout(4000)
        assert page.get_by_test_id("practice-refutation").count() == 1


def test_qa13r3_the_session_limit_says_so_in_the_real_window(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _ok(_call(page, "set_opening_settings", "deep", None, None, False))
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-add-all").click()
        page.get_by_test_id("opening-added").wait_for()
        page.get_by_test_id("openings-tab-practice").click()
        page.get_by_test_id("practice-mode").get_by_text("All").click()
        page.get_by_test_id("practice-begin").click()
        page.get_by_test_id("practice-session").wait_for()
        texts: list[str] = []
        for _ in range(120):
            if page.get_by_test_id("practice-start").count():
                break
            state = page.get_by_test_id("practice-session").get_attribute("data-state")
            if state == "your_move":
                page.get_by_test_id("practice-show").click()
            elif state == "helped":
                page.get_by_test_id("practice-continue").click()
            elif state == "line_end":
                texts.append(page.get_by_test_id("practice-line-end-text").inner_text())
                page.get_by_test_id("practice-next-line").click()
            page.wait_for_timeout(120)
        assert page.get_by_test_id("practice-start").count() == 1
        assert texts and "limit" in texts[-1], texts
        assert all("limit" not in t for t in texts[:-1])
        finished = page.get_by_test_id("practice-finished").inner_text()
        assert "0 right, 15 missed" in finished and "0 clean lines" in finished, finished
        assert page.errors == []


def test_qa13r3_the_prefetch_dialog_with_answers_out_of_order(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Italian Game")
        page.evaluate(
            """() => {
                const api = window.pywebview.api;
                const real = api.get_opening_prefetch_plan.bind(api);
                window.planHold = {};
                api.get_opening_prefetch_plan = (...a) =>
                    new Promise((ok) => setTimeout(ok, window.planHold[a[1]] ?? 0)).then(() => real(...a));
            }"""
        )
        page.get_by_test_id("opening-prefetch").click()
        page.get_by_test_id("prefetch-plan").wait_for()
        confirm = page.get_by_test_id("prefetch-confirm")
        page.wait_for_function("() => !document.querySelector('[data-testid=prefetch-confirm]').disabled")
        page.evaluate("() => { window.planHold = {deep: 2000, light: 800}; }")
        preset = page.get_by_test_id("prefetch-preset")
        preset.get_by_text("Deep").click()
        assert confirm.is_disabled()
        preset.get_by_text("Light").click()
        assert confirm.is_disabled()
        page.wait_for_function("() => !document.querySelector('[data-testid=prefetch-confirm]').disabled")
        page.get_by_test_id("prefetch-counts").filter(has_text="2 lines").wait_for()
        page.wait_for_timeout(1800)  # Deep's answer has arrived by now, and is dropped
        assert "2 lines" in page.get_by_test_id("prefetch-counts").inner_text()
        assert confirm.is_enabled()
        confirm.click()
        page.get_by_test_id("prefetch-done").wait_for(timeout=120_000)
        assert page.errors == []
