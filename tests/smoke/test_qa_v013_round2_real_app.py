"""QA v0.13 round 2 in the real app: slow answers arriving late, the same move twice, a refused move, the Branch menu, and
quick changes in the prefetch dialog. The bridge's answers are delayed from the page, around the real client's own calls.
Temp data folder, signed out, no AI key, nothing sent. A test exposing an open bug is xfail with its ID."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.smoke.test_qa_v010_real_app import _call, _ok
from tests.smoke.test_qa_v013_real_app import _app, _fen, _folder, _openings, _pick, _shot, _stop_at_book

pytestmark = pytest.mark.smoke


def _delay_what_if(page: Any) -> None:
    """`window.whatIfDelay[move]` holds back the answer to one move, in the page, ahead of the real bridge."""
    page.evaluate(
        """() => {
            const api = window.pywebview.api;
            const real = api.get_opening_deviation.bind(api);
            window.whatIfDelay = {};
            api.get_opening_deviation = (color, moves, move) =>
                new Promise((ok) => setTimeout(ok, window.whatIfDelay[move] ?? 0)).then(() => real(color, moves, move));
        }"""
    )


def _set_delay(page: Any, move: str, ms: int) -> None:
    page.evaluate("([m, ms]) => { window.whatIfDelay[m] = ms; }", [move, ms])


def _pieces(page: Any) -> dict[str, str]:
    return page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('[data-testid=board] cg-board piece')]
            .filter((p) => !p.classList.contains('ghost')).map((p) => [p.cgKey, p.className]))"""
    )


def _learn(page: Any) -> None:
    _openings(page)
    _stop_at_book(page)
    _pick(page, "Italian Game")
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("what-if").wait_for()
    _delay_what_if(page)


def _ask(page: Any, move: str) -> None:
    page.get_by_test_id("what-if-move").fill(move)
    page.get_by_test_id("what-if-go").click()


def test_qa13r2_a_slow_answer_after_clear_is_dropped_and_the_same_move_works_twice(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _learn(page)
        at = _fen(page)
        _ask(page, "a6")
        page.get_by_test_id("what-if-replies").filter(has_text="a6").wait_for(timeout=30_000)
        _set_delay(page, "b6", 1500)
        _ask(page, "b6")
        page.get_by_test_id("what-if-clear").click()
        page.wait_for_timeout(3000)
        assert page.get_by_test_id("what-if-replies").count() == 0 and _fen(page) == at
        assert page.get_by_test_id("what-if-go").is_enabled() or page.get_by_test_id("what-if-move").input_value() == ""

        # The same move on the board, twice.
        for _ in range(2):
            play(page, "a7a6", "white")
            page.get_by_test_id("what-if-replies").filter(has_text="a6").wait_for(timeout=30_000)
            page.get_by_test_id("what-if-clear").click()
            page.get_by_test_id("what-if-replies").wait_for(state="detached")
            assert _fen(page) == at
            page.wait_for_timeout(400)
            assert "a7" in _pieces(page) and "a6" not in _pieces(page)
        assert page.errors == []


def test_qa13r2_a_slow_board_move_after_a_step_change_leaves_no_trace(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _learn(page)
        _set_delay(page, "a7a6", 1500)
        play(page, "a7a6", "white")
        page.get_by_test_id("learn-forward").click()  # your move: the panel goes
        page.get_by_test_id("what-if").wait_for(state="detached")
        at = _fen(page)
        page.wait_for_timeout(3000)
        assert _fen(page) == at and "e5" in _pieces(page) and "a6" not in _pieces(page)
        page.get_by_test_id("learn-forward").click()  # their turn again: a new panel
        page.get_by_test_id("what-if").wait_for()
        assert page.get_by_test_id("what-if-replies").count() == 0

        # And a jump straight between their turns, with an answer on its way.
        at = _fen(page)
        _set_delay(page, "a6", 1500)
        _ask(page, "a6")
        page.get_by_test_id("learn-move-4").click()
        page.wait_for_timeout(3000)
        assert page.get_by_test_id("what-if-replies").count() == 0 and _fen(page) != at
        assert " b " in _fen(page) and "/p" not in _fen(page).split()[0].split("/")[2]
        assert page.errors == []


def test_qa13r2_a_newer_question_beats_a_slower_older_one(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _learn(page)
        _set_delay(page, "a6", 2000)
        _ask(page, "a6")
        page.wait_for_timeout(100)
        # The Find replies button waits while one is out, so the newer question is played on the board.
        play(page, "h7h6", "white")
        page.get_by_test_id("what-if-replies").filter(has_text="h6").wait_for(timeout=30_000)
        page.wait_for_timeout(2500)
        assert "After h6" in page.get_by_test_id("what-if-replies").inner_text()
        assert "h6" in _pieces(page) and "a6" not in _pieces(page)


def test_qa13r2_with_no_engine_a_refused_board_move_goes_back(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    with _app(pw, data_dir) as page:
        page.get_by_test_id("nav-openings").click()
        page.get_by_test_id("openings-view").wait_for(timeout=120_000)
        _stop_at_book(page)
        _pick(page, "Italian Game")
        page.get_by_test_id("learn-forward").click()
        play(page, "a7a6", "white")
        page.get_by_test_id("what-if-error").filter(has_text="Stockfish").wait_for()
        page.wait_for_timeout(400)
        assert "a7" in _pieces(page) and "a6" not in _pieces(page)
        # Still playable: the same move refused again says so again.
        play(page, "a7a6", "white")
        page.get_by_test_id("what-if-error").wait_for()
        page.wait_for_timeout(400)
        assert "a7" in _pieces(page)
        assert page.errors == []


def test_qa13r2_a_quick_change_in_the_prefetch_dialog_shows_its_own_plan(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-prefetch").click()
        page.get_by_test_id("prefetch-plan").wait_for()
        preset = page.get_by_test_id("prefetch-preset")
        preset.get_by_text("Deep").click()
        preset.get_by_text("Light").click()
        page.wait_for_timeout(2500)
        assert "2 lines" in page.get_by_test_id("prefetch-counts").inner_text()


def test_qa13r2_the_branch_menu_limits_a_real_session(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _ok(_call(page, "set_opening_settings", "custom", 3, 6, False))
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-add-0").click()
        page.get_by_test_id("opening-added").wait_for()
        page.get_by_test_id("openings-tab-practice").click()
        select = page.get_by_test_id("practice-branch")
        select.wait_for()
        assert select.is_disabled()  # one line doesn't split

        page.get_by_test_id("openings-tab-book").click()
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-add-all").click()
        page.get_by_test_id("opening-added").wait_for()
        page.get_by_test_id("openings-tab-practice").click()
        select = page.get_by_test_id("practice-branch")
        page.wait_for_function("() => !document.querySelector('[data-testid=practice-branch]').disabled")
        wanted = _ok(_call(page, "get_practice_branches", "white", None))
        assert len(wanted) >= 2 and all(re.match(r"\d+\. ", b["label"]) for b in wanted)
        whole = _ok(_call(page, "get_practice_summary", "white"))["positions"]
        select.click()
        page.get_by_role("option", name=wanted[-1]["label"], exact=True).click()
        _shot(page, "r2-branch")
        page.get_by_test_id("practice-mode").get_by_text("All").click()
        page.get_by_test_id("practice-begin").click()
        page.get_by_test_id("practice-session").wait_for()
        left = int(re.search(r"(\d+) to go", page.get_by_test_id("practice-tally").inner_text()).group(1))  # type: ignore[union-attr]
        assert 1 <= left < whole
        # The miss's real line, in SAN.
        fen = _fen(page)
        board_turn_white = " w " in fen
        assert board_turn_white
        play(page, "a2a3", "white")
        page.locator("[data-testid=practice-session][data-state=wrong]").wait_for()
        text = page.get_by_test_id("practice-refutation")
        text.wait_for(timeout=30_000)
        assert re.search(r"for you: .*[a-hKQRBNO]", text.inner_text()), text.inner_text()
        _shot(page, "r2-refutation")
        assert page.errors == []
