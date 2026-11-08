"""QA v0.14 in the real app (WebView2 over CDP): a saved study, seeded into a temp user.db from an invented PGN, opened
from the Studies tab. Signed out, no AI key. The relaunch runs with HTTP(S)_PROXY pointing at a closed port, so the
backend can't reach Lichess ("offline"). Nothing is ever sent to lichess.org. A test exposing an open bug is xfail
(strict) with its ID."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v010_real_app import _call, _ok, _wait_job
from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.studies import StudiesRepo
from weaksquare.core.clock import FixedClock
from weaksquare.core.study_pgn import parse_study

pytestmark = pytest.mark.smoke
ART = Path("tests/e2e/artifacts")
SID = "TestSm01"
OFFLINE = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}


def _ch(n: int, name: str, body: str, extra: str = "") -> str:
    return (
        f'[Event "Invented smoke study: {name}"]\n[Site "https://lichess.org/study/{SID}/Chap000{n}"]\n'
        f'[Result "*"]\n[Annotator "https://lichess.org/@/player_author"]\n[StudyName "Invented smoke study"]\n'
        f'[ChapterName "{name}"]\n[ChapterURL "https://lichess.org/study/{SID}/Chap000{n}"]\n{extra}\n{body} *\n\n\n'
    )


PGN = (
    _ch(1, "Intro", "{ Welcome. Notes at https://example.com/notes and <b>bold</b>. }")
    + _ch(
        2,
        "Main",
        "1. e4 e5 2. Nc3 { The quiet move. [%cal Gc3d5,Bf1c4] [%csl Re5,Gz9] } 2... Nf6 "
        "(2... Nc6 3. f4 { The gambit. } 3... exf4) 3. f4 d5 4. fxe5 Nxe4",
    )
    + _ch(
        3,
        "Text",
        "{ An empty board on purpose. }",
        '[Variant "From Position"]\n[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n[SetUp "1"]',
    )
    + _ch(
        4, "Play", "1. e4 { Your move. } 1... c6 (1... e5 { Not in this study. }) 2. d4 d5", '[ChapterMode "gamebook"]'
    )
)


def _folder(tmp_path: Path, fixture_puzzles_db: Path) -> Path:
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    clock = FixedClock(datetime(2026, 11, 8, 12, 0, tzinfo=UTC))
    migrate(data_dir / "user.db", config.MIGRATIONS_DIR / "user", clock)
    db = Database(data_dir / "user.db", data_dir / "puzzles.db")
    StudiesRepo(db).save(parse_study(SID, PGN), "2026-11-08T12:00:00+00:00", private=False)
    db._close_registered()
    return data_dir


@contextmanager
def _app(pw: Any, data_dir: Path, env: dict[str, str] | None = None) -> Iterator[Any]:
    app = launch_app(data_dir, free_port(), env)
    try:
        with attach(pw, app) as page:
            page.errors = []
            page.on("pageerror", lambda e: page.errors.append(str(e)))
            page.get_by_test_id("nav-studies").click(timeout=30_000)
            page.get_by_test_id("studies-view").wait_for()
            yield page
            assert page.errors == []
    finally:
        app.close()


def _shot(page: Any, name: str) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v014-real-{name}.png"), full_page=True)


def _open(page: Any) -> None:
    page.get_by_test_id("study-continue").first.click()
    page.get_by_test_id("study-page").wait_for()
    page.get_by_test_id("study-reader").wait_for()


def _chapter(page: Any, title: str) -> None:
    page.get_by_test_id("study-chapter").filter(has_text=title).click()
    page.get_by_test_id("study-chapter-title").filter(has_text=title).wait_for()


def test_qa14_saved_study_steps_through_and_continue_survives_an_offline_restart(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        card = page.get_by_test_id("study-card")
        assert "Invented smoke study" in card.inner_text() and "player_author" in card.inner_text()
        _open(page)
        reader = page.get_by_test_id("study-reader")
        # The intro's comment: plain text, the address and markup shown literally, never a link.
        reader.get_by_text("https://example.com/notes", exact=False).wait_for()
        assert "<b>bold</b>" in reader.inner_text()
        assert page.locator("[data-testid=study-page] a[href]").count() == 0
        _shot(page, "intro")

        _chapter(page, "Main")
        for _ in range(3):
            page.get_by_test_id("study-forward").click()
        assert page.get_by_test_id("study-current-move").inner_text().strip().endswith("Nc3")
        page.get_by_text("The quiet move.").first.wait_for()
        # Into the side line 2... Nc6 3. f4, then Back to main line appears.
        page.locator("[data-move-id]").filter(has_text="Nc6").click()
        page.get_by_test_id("study-forward").click()
        page.get_by_test_id("study-main-line").wait_for()
        assert page.get_by_test_id("study-variation").count() >= 1
        page.wait_for_timeout(900)  # the place is saved a moment after you stop
        place = _ok(_call(page, "get_study_continue", SID))
        assert place == {"chapter_key": "Chap0002", "path": ["e2e4", "e7e5", "b1c3", "b8c6", "f2f4"]}
        _shot(page, "side-line")

        # The text chapter: shown, no move buttons.
        _chapter(page, "Text")
        page.get_by_text("An empty board on purpose.").wait_for()
        assert page.get_by_test_id("study-nav").count() == 0

        _chapter(page, "Main")  # leave the place in Main again
        page.get_by_test_id("study-forward").click()
        page.wait_for_timeout(900)

    # Relaunch with Lichess unreachable: the saved copy opens and Continue goes back to the place.
    with _app(pw, data_dir, OFFLINE) as page:
        card = page.get_by_test_id("study-card")
        assert "at “Main”" in card.inner_text()
        assert page.get_by_test_id("study-continue").inner_text().strip() == "Continue"
        _open(page)
        page.get_by_test_id("study-chapter-title").filter(has_text="Main").wait_for()
        assert page.get_by_test_id("study-current-move").inner_text().strip().endswith("e4")
        # Check for updates while offline: a clear message, and your copy is untouched.
        job = _ok(_call(page, "check_study_updates", SID))
        st = _wait_job(page, job, 60)
        assert st["state"] == "failed" and st["error_code"] in ("offline", "lichess_trouble"), st
        assert _ok(_call(page, "get_study_update", SID)) is None
        assert len(_ok(_call(page, "get_study", SID))["chapters"]) == 4
        _shot(page, "offline")


def test_qa14_b4_a_chapter_with_no_moves_counts_as_finished_once_read(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    """Real studies open with a no-move introduction (all three of Adam's test studies have such chapters). Reading it
    and clicking Next chapter should count it done, or the study can never reach Finished (FR-13.1)."""
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        _open(page)
        page.get_by_test_id("study-chapter-title").filter(has_text="Intro").wait_for()
        page.get_by_test_id("study-end").wait_for()  # "End of the chapter." with Next chapter
        page.get_by_test_id("study-next-chapter").click()
        page.get_by_test_id("study-chapter-title").filter(has_text="Main").wait_for()
        page.wait_for_timeout(600)
        chapters = _ok(_call(page, "get_study", SID))["chapters"]
        assert chapters[0]["done"] is True


def test_qa14_b5_hearting_a_study_mid_chapter_keeps_your_place(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        _open(page)
        _chapter(page, "Main")
        for _ in range(4):
            page.get_by_test_id("study-forward").click()
        page.wait_for_timeout(900)
        assert _ok(_call(page, "get_study_continue", SID))["path"] == ["e2e4", "e7e5", "b1c3", "g8f6"]
        page.get_by_test_id("study-heart").click()
        page.wait_for_timeout(1200)
        assert _ok(_call(page, "get_study", SID))["summary"]["hearted"] is True
        assert page.get_by_test_id("study-current-move").inner_text().strip().endswith("Nf6")
        assert _ok(_call(page, "get_study_continue", SID))["path"] == ["e2e4", "e7e5", "b1c3", "g8f6"]


def test_qa14_b6_the_play_along_board_is_a_usable_size_in_the_real_app(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    data_dir = _folder(tmp_path, fixture_puzzles_db)
    with _app(pw, data_dir) as page:
        page.set_viewport_size({"width": 1400, "height": 900})
        _open(page)
        _chapter(page, "Main")
        page.wait_for_timeout(400)
        board = "[data-testid=study-reader] [data-testid=board]"
        normal = page.locator(board).bounding_box()["width"]
        _chapter(page, "Play")
        page.get_by_test_id("study-turn").wait_for()
        page.wait_for_timeout(400)
        _shot(page, "gamebook")
        play_along = page.locator(board).bounding_box()["width"]
        assert normal >= 240, normal
        assert play_along >= 240, (normal, play_along)
