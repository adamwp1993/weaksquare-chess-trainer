"""StudiesService (v0.14, REQUIREMENTS §19) on a real user.db with the fake Lichess studies client.

Invented studies only (tests/fixtures/http/lichess_studies). Covers FR-13.5, 13.5a, 13.7, 13.9 and 13.10, and the
ROADMAP v0.14 *Done when* items that the service decides: no request for a non-study address, the token only after a
403, an old sign-in told to sign in again, illegal chapters rejected and the rest kept, text chapters kept, a saved study
opening offline and after its author deletes it, Check for updates never changing your copy without asking, and your
place surviving restarts and updates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from tests.fakes.lichess import FAKE_TOKEN
from tests.fakes.studies import FakeLichessStudies, fixture_pgn, rate_limited
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.studies import StudiesRepo
from weaksquare.adapters.http import HttpError
from weaksquare.adapters.lichess import is_network_error, is_rate_limited
from weaksquare.config import MIGRATIONS_DIR, Paths
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import AppError, NotFoundError, ValidationError
from weaksquare.core.study_links import StudyRef
from weaksquare.jobs.runner import JobRunner, JobStatus
from weaksquare.services.studies import StudiesService, StudyErrors, load_starter


class Tokens:
    def __init__(self) -> None:
        self.value: str | None = None
        self.scopes: set[str] = set()

    def token(self) -> str | None:
        return self.value

    def has_scope(self, scope: str) -> bool:
        return self.value is not None and scope in self.scopes


@dataclass
class Rig:
    svc: StudiesService
    client: FakeLichessStudies
    tokens: Tokens
    runner: JobRunner
    clock: FixedClock
    repo: StudiesRepo
    paths: Paths

    def run(self, job: str) -> JobStatus:
        st = self.runner.wait(job, 10)
        assert st is not None
        return st

    def add(self, text: str) -> JobStatus:
        return self.run(self.svc.add_text(text))


ERRORS = StudyErrors(
    status_of=lambda e: e.status if isinstance(e, HttpError) else None,
    is_network_error=is_network_error,
    is_rate_limited=is_rate_limited,
)


@pytest.fixture
def rig(paths: Paths) -> Rig:
    clock = FixedClock(datetime(2026, 11, 7, 12, 0, tzinfo=UTC))
    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    db = Database(paths.user_db, paths.puzzles_db)
    repo = StudiesRepo(db)
    client, tokens, runner = FakeLichessStudies(), Tokens(), JobRunner()
    svc = StudiesService(repo, client, tokens, runner, clock, ERRORS)
    return Rig(svc, client, tokens, runner, clock, repo, paths)


# ---- adding ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "https://lichess.org/abcdefgh", "https://evil.com/study/TestGb01", "hello world"])
def test_anything_but_a_study_address_makes_no_request(rig: Rig, text: str) -> None:
    with pytest.raises(ValidationError) as e:
        rig.svc.add_text(text)
    assert e.value.code == "not_a_study"
    assert rig.client.calls == []


def test_add_downloads_checks_and_stores_a_public_study_without_the_token(rig: Rig) -> None:
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    job = rig.svc.add_text("https://lichess.org/study/TestGb01")
    st = rig.run(job)
    assert st.state == "done" and st.message == "Added “Invented gamebook” (2 chapters)"
    assert rig.client.calls == [("TestGb01", None)]  # signed in, but a public study never sends the token
    res = rig.svc.add_result(job)
    assert res is not None and (res.study_id, res.chapter_key, res.already_saved) == ("TestGb01", None, False)
    row, chapters = rig.svc.get("TestGb01")
    assert (row.title, row.author, row.private, row.chapters, row.playable) == (
        "Invented gamebook", "player_author", False, 2, 2,
    )  # fmt: skip
    assert [(c.key, c.mode, c.orientation) for c in chapters] == [
        ("Chap0001", "gamebook", "black"), ("Chap0002", "gamebook", "black"),
    ]  # fmt: skip


def test_an_illegal_chapter_is_rejected_and_the_rest_kept_with_a_text_chapter(rig: Rig) -> None:
    st = rig.add("TestNm02")
    assert st.state == "done" and st.message == "Added “Invented analysis” (3 chapters); 1 couldn't be used"
    _, chapters = rig.svc.get("TestNm02")
    assert [(c.title, c.rejected is None, c.text_only) for c in chapters] == [
        ("Main line", True, False), ("Broken", False, False), ("Thanks", True, True),
    ]  # fmt: skip
    assert chapters[1].rejected and "illegal" in chapters[1].rejected
    with pytest.raises(ValidationError):
        rig.svc.chapter("TestNm02", "Chap0002")
    text_row, text_tree = rig.svc.chapter("TestNm02", "Chap0003")
    assert text_row.text_only and text_tree.comment == "Thanks for studying! This board is empty on purpose."


def test_a_chapter_link_opens_that_chapter(rig: Rig) -> None:
    job = rig.svc.add_text("https://lichess.org/study/TestGb01/Chap0002")
    rig.run(job)
    res = rig.svc.add_result(job)
    assert res is not None and res.chapter_key == "Chap0002"
    again = rig.svc.add_text("lichess.org/study/TestGb01/Chap0001")
    assert rig.run(again).message == "Already in My studies"
    res2 = rig.svc.add_result(again)
    assert res2 is not None and res2.already_saved and res2.chapter_key == "Chap0001"
    assert rig.client.calls == [("TestGb01", None)]  # already saved: not downloaded again


def test_add_from_ids_checks_each_id(rig: Rig) -> None:
    with pytest.raises(ValidationError):
        rig.svc.add_ids("TestGb01?x")
    with pytest.raises(ValidationError):
        rig.svc.add_ids("TestGb01", "../../x")
    assert rig.run(rig.svc.add_ids("TestGb01", "Chap0001")).state == "done"


# ---- private studies (FR-6.1, FR-13.7) -----------------------------------------------------------------------------
def _make_private(rig: Rig, sid: str = "TestGb01") -> None:
    rig.client.private[sid] = rig.client.public.pop(sid)


def test_private_study_signed_out_says_to_sign_in(rig: Rig) -> None:
    _make_private(rig)
    st = rig.add("TestGb01")
    assert (st.state, st.error_code) == ("failed", "study_private")
    assert rig.client.calls == [("TestGb01", None)]


def test_private_study_with_a_pre_v014_sign_in_says_sign_in_again(rig: Rig) -> None:
    _make_private(rig)
    rig.tokens.value = FAKE_TOKEN  # signed in, but no study:read recorded
    st = rig.add("TestGb01")
    assert (st.state, st.error_code) == ("failed", "study_scope")
    assert "Sign in again" in (st.message or "")
    assert rig.client.calls == [("TestGb01", None)]  # the token was never sent


def test_private_study_with_study_read_retries_with_the_token(rig: Rig) -> None:
    _make_private(rig)
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    st = rig.add("TestGb01")
    assert st.state == "done"
    assert rig.client.calls == [("TestGb01", None), ("TestGb01", FAKE_TOKEN)]
    row, _ = rig.svc.get("TestGb01")
    assert row.private
    assert FAKE_TOKEN not in repr(st)


def test_someone_elses_private_study(rig: Rig) -> None:
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    rig.client.errors["TestGb01"] = HttpError("x returned HTTP 403", status=403, retryable=False)
    st = rig.add("TestGb01")
    assert (st.state, st.error_code) == ("failed", "study_forbidden")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (HttpError("x returned HTTP 404", status=404, retryable=False), "study_not_found"),
        (HttpError("Network error while fetching x: ConnectError"), "offline"),
        (rate_limited(), "rate_limited"),
        (HttpError("x returned HTTP 500", status=500), "lichess_trouble"),
        (HttpError("x returned HTTP 400", status=400, retryable=False), "study_download_failed"),
    ],
)
def test_download_errors(rig: Rig, error: HttpError, code: str) -> None:
    rig.client.errors["TestGb01"] = error
    st = rig.add("TestGb01")
    assert (st.state, st.error_code) == ("failed", code)
    assert rig.svc.list_studies() == []


def test_a_study_with_no_usable_chapter_is_not_saved(rig: Rig) -> None:
    rig.client.public["Broken01"] = fixture_pgn("TestNm02").split("\n\n\n")[1]
    st = rig.add("Broken01")
    assert (st.state, st.error_code) == ("failed", "study_unusable")
    assert rig.svc.list_studies() == []


# ---- offline, deleted by its author, your place (FR-13.7, 13.10) ---------------------------------------------------
def test_a_saved_study_opens_offline_and_after_its_author_deletes_it(rig: Rig) -> None:
    rig.add("TestNm02")
    rig.client.public.clear()
    rig.client.errors["TestNm02"] = HttpError("Network error while fetching x: ConnectError")
    calls = len(rig.client.calls)
    row, tree = rig.svc.chapter("TestNm02", "Chap0001")
    assert row.title == "Main line" and tree.children[0].san == "e4"
    assert len(rig.client.calls) == calls  # opening a saved study makes no request


def test_place_is_saved_checked_and_survives_a_restart(rig: Rig) -> None:
    rig.add("TestNm02")
    rig.svc.set_place("TestNm02", "Chap0001", "e2e4 e7e5 b1c3 b8c6 f2f4")  # a side line
    with pytest.raises(ValidationError):
        rig.svc.set_place("TestNm02", "Chap0001", "e2e4 e7e5 d2d4")  # not in the chapter
    with pytest.raises(ValidationError):
        rig.svc.set_place("TestNm02", "Chap0001", "e2e4; DROP TABLE studies")
    # A fresh service on the same database (a restart).
    db = Database(rig.paths.user_db, rig.paths.puzzles_db)
    again = StudiesService(StudiesRepo(db), FakeLichessStudies(), Tokens(), JobRunner(), rig.clock, ERRORS)
    assert again.continue_target("TestNm02") == ("Chap0001", "e2e4 e7e5 b1c3 b8c6 f2f4")
    assert [r.id for r in again.list_studies("in_progress")] == ["TestNm02"]


def test_continue_without_a_place_goes_to_the_first_unfinished_chapter(rig: Rig) -> None:
    rig.add("TestGb01")
    assert rig.svc.continue_target("TestGb01") == ("Chap0001", "")
    rig.svc.set_done("TestGb01", "Chap0001", True)
    assert rig.svc.continue_target("TestGb01") == ("Chap0002", "")
    rig.svc.set_done("TestGb01", "Chap0002", True)
    assert [r.id for r in rig.svc.list_studies("finished")] == ["TestGb01"]
    assert rig.svc.list_studies("in_progress") == []
    rig.svc.restart("TestGb01")
    row, _ = rig.svc.get("TestGb01")
    assert (row.done, row.place_key) == (0, None)


def test_hearts_are_local_and_filter(rig: Rig) -> None:
    rig.add("TestGb01")
    rig.add("TestNm02")
    calls = len(rig.client.calls)
    rig.svc.heart("TestNm02", True)
    assert [r.id for r in rig.svc.list_studies("favorites")] == ["TestNm02"]
    assert len(rig.client.calls) == calls  # nothing is sent to Lichess
    rig.svc.heart("TestNm02", False)
    assert rig.svc.list_studies("favorites") == []


def test_delete(rig: Rig) -> None:
    rig.add("TestGb01")
    rig.svc.set_place("TestGb01", "Chap0001", "e2e4")
    rig.svc.delete("TestGb01")
    assert rig.svc.list_studies() == []
    with pytest.raises(NotFoundError):
        rig.svc.get("TestGb01")
    with sqlite3.connect(rig.paths.user_db) as conn:
        for table in ("study_chapters", "study_progress", "study_chapters_done"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_a_damaged_row_never_reaches_the_board(rig: Rig) -> None:
    rig.add("TestGb01")
    with sqlite3.connect(rig.paths.user_db) as conn:
        conn.execute(
            "UPDATE study_chapters SET tree = ? WHERE chapter_key = 'Chap0001'",
            ('{"v":2,"nodes":[{},{"p":0,"uci":"e2e5","san":"e5"}]}',),
        )
    with pytest.raises(AppError) as e:
        rig.svc.chapter("TestGb01", "Chap0001")
    assert e.value.code == "chapter_damaged"


# ---- Check for updates (FR-13.7) ----------------------------------------------------------------------------------
def test_check_for_updates_with_no_change(rig: Rig) -> None:
    rig.add("TestGb01")
    st = rig.run(rig.svc.check_updates("TestGb01"))
    assert st.message == "No changes: your copy is up to date"
    assert rig.svc.pending_update("TestGb01") is None


def test_check_for_updates_never_changes_your_copy_without_asking(rig: Rig) -> None:
    rig.add("TestNm02")
    rig.svc.set_place("TestNm02", "Chap0001", "e2e4 e7e5")
    rig.svc.set_done("TestNm02", "Chap0003", True)
    old = fixture_pgn("TestNm02")
    chapters = old.split("\n\n\n")
    # The author edits chapter 1's comment, deletes the text chapter and adds a new one.
    edited = chapters[0].replace("The quiet move.", "The quiet move, edited.")
    new_ch = chapters[1].replace("Chap0002", "Chap0004").replace('"Broken"', '"New one"').replace("2. Ke3", "2. Nf3")
    rig.client.public["TestNm02"] = "\n\n\n".join([edited, chapters[1], new_ch]) + "\n"
    st = rig.run(rig.svc.check_updates("TestNm02"))
    assert st.message == "Changes found: review them before updating"
    p = rig.svc.pending_update("TestNm02")
    assert p is not None
    assert (p.diff.added, p.diff.removed, p.diff.changed, p.diff.unchanged) == (
        ["New one"],
        ["Thanks"],
        ["Main line"],
        1,
    )
    # Your copy is unchanged until you accept.
    _, before = rig.svc.chapter("TestNm02", "Chap0001")
    assert "edited" not in str(before)
    rig.svc.apply_update("TestNm02")
    _, after = rig.svc.chapter("TestNm02", "Chap0001")
    assert "edited" in str(after)
    row, chapters_now = rig.svc.get("TestNm02")
    assert [c.title for c in chapters_now] == ["Main line", "Broken", "New one"]
    assert (row.place_key, row.place_path) == ("Chap0001", "e2e4 e7e5")  # its chapter still exists
    assert row.done == 0  # the finished chapter was deleted by the author
    with pytest.raises(ValidationError):
        rig.svc.apply_update("TestNm02")  # nothing pending any more


def test_an_update_that_removes_your_chapter_drops_your_place(rig: Rig) -> None:
    rig.add("TestGb01")
    rig.svc.set_place("TestGb01", "Chap0002", "e2e4")
    rig.client.public["TestGb01"] = fixture_pgn("TestGb01").split("\n\n\n")[0] + "\n"
    rig.run(rig.svc.check_updates("TestGb01"))
    rig.svc.discard_update("TestGb01")
    assert rig.svc.continue_target("TestGb01") == ("Chap0002", "e2e4")  # discarded: unchanged
    rig.run(rig.svc.check_updates("TestGb01"))
    rig.svc.apply_update("TestGb01")
    assert rig.svc.continue_target("TestGb01") == ("Chap0001", "")


# ---- Studies by author (FR-13.5a) -------------------------------------------------------------------------------
def test_studies_by_author(rig: Rig) -> None:
    rig.add("TestGb01")
    found = rig.svc.studies_by("https://lichess.org/@/player_author")
    assert [(s["study_id"], s["name"], s["saved"]) for s in found] == [
        ("TestGb01", "Invented gamebook", True), ("TestNm02", "Invented analysis", False),
    ]  # fmt: skip
    assert rig.client.calls[-1] == ("by:player_author", None)


def test_studies_by_author_errors(rig: Rig) -> None:
    with pytest.raises(ValidationError):
        rig.svc.studies_by("not a name!")
    assert rig.client.calls == []
    with pytest.raises(NotFoundError):
        rig.svc.studies_by("player_nobody")
    rig.client.errors["by:player_author"] = HttpError("Network error while fetching x: ConnectError")
    with pytest.raises(AppError) as e:
        rig.svc.studies_by("player_author")
    assert e.value.code == "offline"


# ---- starter list (FR-13.6) --------------------------------------------------------------------------------------
def test_starter_list_is_strict() -> None:
    ok = '[{"study_id": "TestGb01", "title": "A study", "author": "player_author", "opening": "Caro-Kann"}]'
    assert load_starter(ok)[0].study_id == "TestGb01"
    for bad in (
        '[{"study_id": "TestGb01", "title": "A", "author": "player_a", "opening": "x", "pgn": "1. e4"}]',
        '[{"study_id": "bad", "title": "A", "author": "player_a", "opening": "x"}]',
        '[{"study_id": "TestGb01", "title": "A", "author": "not a name", "opening": "x"}]',
        '[{"study_id": "TestGb01", "title": "", "author": "player_a", "opening": "x"}]',
        '{"study_id": "TestGb01"}',
    ):
        with pytest.raises(ValueError):
            load_starter(bad)


def test_ref_url_is_built_by_the_app() -> None:
    assert StudyRef("TestGb01", "Chap0001").url == "https://lichess.org/study/TestGb01/Chap0001"
