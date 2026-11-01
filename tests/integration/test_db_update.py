"""FR-2.5 update check, over the recorded and scrubbed database.lichess.org responses
(tests/fixtures/http/lichess_db, from tests/fixtures/tools/record_db_update.py), through the real
HttpClient with a mock transport. One test per Done-when case."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from weaksquare import config
from weaksquare.adapters.http import HttpClient
from weaksquare.core.clock import FixedClock
from weaksquare.core.db_update import parse_count
from weaksquare.jobs.runner import CancelToken, JobRunner
from weaksquare.services.db_update import LAST_CHECK_KEY, SKIPPED_KEY, UpdateCheckService, Urls

REC = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "lichess_db"
SUMS = (REC / "sha256sums.txt").read_text(encoding="utf-8")
HEAD = json.loads((REC / "head.json").read_text(encoding="utf-8"))
PAGE = (REC / "page.html").read_text(encoding="utf-8")
PUBLISHED_SHA = next(line.split()[0] for line in SUMS.splitlines() if line.endswith("lichess_db_puzzle.csv.zst"))
PUBLISHED_DATE = "2026-11-01"  # head.json's Last-Modified
PUBLISHED_SIZE = int(HEAD["headers"]["content-length"])
PAGE_COUNT = 6_193_530
URLS = Urls(file=config.PUZZLE_DB_URL, sums=config.PUZZLE_SUMS_URL, page=config.PUZZLE_PAGE_URL)


class Store(dict):  # type: ignore[type-arg]
    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, default)

    def set(self, key: str, value: Any) -> None:
        self[key] = value


def transport(page: str = PAGE, offline: bool = False, requests: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(f"{request.method} {request.url}")
        if offline:
            raise httpx.ConnectError("offline", request=request)
        url = str(request.url)
        if url == URLS.sums:
            return httpx.Response(200, text=SUMS)
        if url == URLS.file and request.method == "HEAD":
            return httpx.Response(200, headers=HEAD["headers"])
        if url == URLS.page:
            return httpx.Response(200, text=page)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def make(meta: dict[str, str] | None, clock: FixedClock, store: Store | None = None, **kw: Any) -> UpdateCheckService:
    http = HttpClient(transport=transport(**kw), retries=0, sleep=lambda s: None)
    return UpdateCheckService(http, clock, store if store is not None else Store(), lambda: meta, JobRunner(), URLS)


def run(service: UpdateCheckService, force: bool = False) -> str:
    return service.run(lambda f, m: None, CancelToken(), force)


MINE = {"sha256": "ab" * 32, "export_date": "2026-10-02", "row_count": "6150000"}


def test_same_hash_no_banner(clock: FixedClock) -> None:
    s = make({**MINE, "sha256": PUBLISHED_SHA}, clock)
    assert run(s) == "Your puzzle database is up to date."
    assert s.current_offer() is None


def test_new_hash_banner_with_dates_size_and_count(clock: FixedClock) -> None:
    s = make(MINE, clock)
    run(s)
    o = s.current_offer()
    assert o is not None
    assert (o.export_date, o.current_export_date, o.size) == (PUBLISHED_DATE, "2026-10-02", PUBLISHED_SIZE)
    assert (o.approx_count, o.approx_new) == (PAGE_COUNT, PAGE_COUNT - 6_150_000)


def test_no_hash_in_meta_falls_back_to_dates(clock: FixedClock) -> None:
    local = {"export_date": "2026-10-02", "row_count": "6150000", "source": "local file"}
    s = make(local, clock)
    run(s)
    assert s.current_offer() is not None  # Last-Modified 2026-11-01 is later
    same_day = make({**local, "export_date": PUBLISHED_DATE}, clock)
    run(same_day)
    assert same_day.current_offer() is None


def test_offline_is_silent(clock: FixedClock) -> None:
    store = Store()
    s = make(MINE, clock, store, offline=True)
    assert run(s) == "Couldn't reach database.lichess.org."  # no exception, so the job never "fails"
    assert s.current_offer() is None
    assert LAST_CHECK_KEY not in store  # it tries again at the next launch


def test_unreadable_count_omits_the_line(clock: FixedClock) -> None:
    s = make(MINE, clock, page="<html>The page changed</html>")
    run(s)
    o = s.current_offer()
    assert o is not None and o.approx_count is None and o.approx_new is None


def test_once_a_day_via_the_injected_clock(clock: FixedClock) -> None:
    store = Store()
    requests: list[str] = []
    s = make(MINE, clock, store, requests=requests)
    run(s)
    assert len(requests) == 3  # sums, HEAD, page: and nothing else
    assert run(s) == "Checked less than a day ago."
    clock.advance(hours=23, minutes=59)
    assert run(s) == "Checked less than a day ago."
    assert run(s, force=True) != "Checked less than a day ago."  # "Check for updates" always runs
    clock.advance(days=1)
    run(s)
    assert len(requests) == 9


def test_auto_check_off_skips_but_the_button_still_checks(clock: FixedClock) -> None:
    store = Store({"puzzle_db.auto_check": False})
    s = make(MINE, clock, store)
    assert run(s) == "The automatic check is off."
    run(s, force=True)
    assert s.current_offer() is not None


def test_skip_this_export_until_a_newer_one(clock: FixedClock) -> None:
    store = Store()
    s = make(MINE, clock, store)
    run(s)
    s.dismiss("skip")
    assert store[SKIPPED_KEY] == f"sha256:{PUBLISHED_SHA}" and s.current_offer() is None
    clock.advance(days=2)
    relaunched = make(MINE, clock, store)  # a new launch: still quiet for this export
    run(relaunched)
    assert relaunched.current_offer() is None
    newer = make(MINE, clock, store)
    newer._urls = Urls(URLS.file, URLS.sums, URLS.page)
    newer._http = HttpClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=SUMS.replace(PUBLISHED_SHA, "cd" * 32)) if str(r.url) == URLS.sums
        else transport().handle_request(r)), retries=0)  # fmt: skip
    clock.advance(days=2)
    run(newer)
    assert newer.current_offer() is not None  # a newer export than the skipped one


def test_not_now_hides_until_the_next_launch(clock: FixedClock) -> None:
    store = Store()
    s = make(MINE, clock, store)
    run(s)
    s.dismiss("not_now")
    assert s.current_offer() is None and SKIPPED_KEY not in store
    clock.advance(days=1)
    run(s)
    assert s.current_offer() is None  # same launch: stays hidden
    relaunched = make(MINE, clock, store)
    clock.advance(days=1)
    run(relaunched)
    assert relaunched.current_offer() is not None  # next launch: asks again


def test_offer_disappears_once_that_export_is_imported(clock: FixedClock) -> None:
    meta = dict(MINE)
    s = make(meta, clock)
    run(s)
    assert s.current_offer() is not None
    meta["sha256"] = PUBLISHED_SHA  # the import finished
    assert s.current_offer() is None


def test_no_database_no_check(clock: FixedClock) -> None:
    requests: list[str] = []
    s = make(None, clock, requests=requests)
    assert run(s) == "No puzzle database installed yet." and requests == []


@pytest.mark.parametrize(
    ("html", "count"),
    [
        (PAGE, PAGE_COUNT),
        ('<section id="puzzles"><p><strong>6 193 530</strong> chess puzzles</p>', 6_193_530),
        ('<section id="evals"><strong>5</strong> chess puzzles</section>', None),
        ("", None),
    ],
)
def test_parse_count(html: str, count: int | None) -> None:
    assert parse_count(html) == count


def test_bridge_wiring(paths, clock, services) -> None:  # type: ignore[no-untyped-def]
    """check_for_db_update runs as a job; get_update_offer and dismiss_update go through the bridge."""
    from tests.helpers import build_api

    api = build_api(paths, clock, http=HttpClient(transport=transport(), retries=0))
    job = api.check_for_db_update(False)["data"]
    api._runner.wait(job, 10)
    offer = api.get_update_offer()["data"]
    assert offer["export_date"] == PUBLISHED_DATE and offer["current_export_date"] == "2026-10-02"
    assert api.dismiss_update("skip")["ok"] and api.get_update_offer()["data"] is None
    assert api.dismiss_update("later")["error"]["code"] == "invalid_argument"
