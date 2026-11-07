"""v0.13 in the real app: a slower answer to an earlier question mustn't replace a newer one. Found as an intermittent failure
of the search step in the smoke suite. Temp data folder, signed out, no AI key, nothing sent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.smoke.test_qa_v013_real_app import _app, _folder, _openings, _pick, _stop_at_book

pytestmark = pytest.mark.smoke


def _hold_the_next_answer(page: Any, method: str) -> None:
    page.evaluate(
        """(method) => {
            const api = window.pywebview.api;
            const real = api[method].bind(api);
            let first = true;
            api[method] = (...a) => {
                const hold = first ? 1500 : 0;
                first = false;
                return real(...a).then((answer) => new Promise((ok) => setTimeout(() => ok(answer), hold)));
            };
        }""",
        method,
    )


def test_a_slow_search_answer_doesnt_replace_a_newer_one(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _hold_the_next_answer(page, "get_opening_families")
        search = page.get_by_test_id("openings-search")
        search.fill("c50")
        search.fill("nothing like this")
        page.get_by_text("No opening matches that.").wait_for()
        page.wait_for_timeout(2500)
        assert page.get_by_text("No opening matches that.").count() == 1


def test_a_slow_answer_about_the_other_side_doesnt_replace_your_repertoire(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    with _app(pw, _folder(tmp_path, fixture_puzzles_db)) as page:
        _openings(page)
        _stop_at_book(page)
        _pick(page, "Italian Game")
        page.get_by_test_id("opening-add-0").click()
        page.get_by_test_id("opening-added").wait_for()
        page.get_by_test_id("openings-tab-repertoire").click()
        rows = page.get_by_test_id("repertoire-row")
        rows.first.wait_for()
        _hold_the_next_answer(page, "get_repertoire")
        color = page.get_by_test_id("repertoire-color")
        color.get_by_text("Black").click()  # this answer is held back, and it's empty
        color.get_by_text("White").click()
        rows.first.wait_for()
        page.wait_for_timeout(2500)
        assert rows.count() > 0
