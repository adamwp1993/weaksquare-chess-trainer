"""v0.11 through the bridge: the report's measures, the AI runs with evidence and lesson pointers, the
notes preview, and lesson links built and opened only by the backend (FR-10.53–10.60)."""

from __future__ import annotations

import json

import pytest

from tests.fakes.desktop import FakeBrowser
from tests.integration.test_coach_ai import _answer, _finding, _report, _wait
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_v010_bridge import api, ok  # noqa: F401  (fixture)


@pytest.fixture
def browser(api) -> FakeBrowser:  # type: ignore[no-untyped-def]  # noqa: F811
    b = FakeBrowser()
    api._desktop = b
    return b


def test_the_report_carries_the_measures(services, paths, api) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    rid = _report(services, paths)
    rep = ok(api.get_coach_report(rid))
    assert rep["measures"]["games"] == 1 and rep["measures"]["min_games"] == 5
    assert rep["measures"]["conversion"]["enough"] is False
    assert rep["whole_game"] == []


def test_an_ai_run_shows_evidence_from_your_analysis_and_lessons_without_urls(services, paths, api) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_answer(_finding(explanation="See https://evil.example now")))
    job = ok(api.start_coach_ai(rid, None))
    _wait(services, job)
    run_id = ok(api.get_coach_ai_job_run(job))
    (summary,) = ok(api.list_coach_ai_runs(rid))
    assert summary["id"] == run_id and summary["format"] == "diagnosis" and summary["findings"] == 1
    run = ok(api.get_coach_ai_run(rid, run_id))
    (f,) = run["findings"]
    gid = services.coach.report(rid)[0].game_ids[0]
    assert f["evidence"] == [{"label": "G1", "game_id": gid, "ply": 12, "move": "1. Kf1"}]
    assert f["label"] == "Missed: Mate in 1" and f["tentative"] and not f["observation"]
    assert "evil.example" not in json.dumps(run)
    lesson = f["lesson"]
    assert lesson["topic"] == "theme:mateIn1" and lesson["curated"][0].startswith("Lichess Practice: Checkmate")
    assert lesson["sites"] == ["youtube", "chesscom"]
    assert lesson["drill"]["spec"]["themes"] == ["mateIn1"]
    assert "http" not in json.dumps(lesson)  # the screen never gets a URL


def test_open_lesson_builds_the_url_in_the_backend(services, paths, api, browser) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    rid = _report(services, paths)
    ok(api.open_lesson(rid, "theme:fork", "curated:0"))
    ok(api.open_lesson(rid, "theme:fork", "youtube"))
    assert browser.opened == [
        "https://lichess.org/practice/fundamental-tactics/the-fork/Qj281y1p",
        "https://www.youtube.com/results?search_query=chess+fork",
    ]
    for topic, target in (
        ("theme:fork", "curated:9"),
        ("theme:fork", "custom"),  # no custom site set
        ("theme:fork", "https://evil.example"),
        ("https://evil.example", "youtube"),
        ("opening:Not In This Report", "youtube"),
    ):
        assert not api.open_lesson(rid, topic, target)["ok"], (topic, target)
    assert len(browser.opened) == 2


def test_search_sites_follow_settings(services, paths, api, browser) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    rid = _report(services, paths)
    ok(api.set_setting("coach.lesson_sites", ["custom"]))
    assert not api.set_setting("coach.lesson_custom_url", "http://example.org/?q={q}")["ok"]
    ok(api.set_setting("coach.lesson_custom_url", "https://example.org/find?q={q}"))
    s = ok(api.get_settings())
    assert s["lesson_sites"] == ["custom"] and s["lesson_custom_url"] == "https://example.org/find?q={q}"
    assert not api.open_lesson(rid, "theme:fork", "youtube")["ok"]  # turned off
    ok(api.open_lesson(rid, "theme:fork", "custom"))
    assert browser.opened == ["https://example.org/find?q=chess+fork"]


def test_the_notes_preview_through_the_bridge(services, paths, api) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    rid = _report(services, paths)
    gid = services.coach.report(rid)[0].game_ids[0]
    services.review.set_game_reason(gid, 12, "didntLook", "missed it, see www.foo.com")
    (n,) = ok(api.get_coach_notes_preview(rid))
    assert n == {"game": "G1", "ply": 13, "move": "1. Kf1", "reason": "didntLook",
                 "text": "missed it, see [link removed]", "source": "game"}  # fmt: skip


def test_the_quote_takes_options(services, paths, api) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    rid = _report(services, paths)
    configure(services)
    q = ok(api.get_coach_ai_quote(rid, {"advanced": True, "game_cap": 20}))
    assert q["quote"]["state"] == "ok" and q["compare"]["games_with_moves"] == 1 and q["cached_run"] is None
    assert not api.get_coach_ai_quote(rid, {"advanced": True, "game_cap": 5})["ok"]
