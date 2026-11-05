"""The training journal against a real database (v0.12, FR-10.67–10.71)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from tests.integration.test_plan_service import _plan, _puzzle_task
from tests.integration.test_qa_v011_coach import _games
from weaksquare.adapters.db.repos.custom_puzzles import RetryRepo
from weaksquare.adapters.db.repos.stats import StatsRepo
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.stats import build_report
from weaksquare.core.themes import display_name
from weaksquare.services.journal import MAX_ENTRY, PROMPT_ENTRIES, PROMPT_ENTRY_CHARS


def _play(services: Any, n: int, mode: str = "standard") -> None:
    info = services.sessions.start(FilterSpec(queue_size=n + 5), False, mode, False)
    for _ in range(n + 1):  # moving on from an undecided puzzle records it as a loss
        services.sessions.next_puzzle(info.session_id)


# ---- FR-10.67: your notes ----


def test_add_edit_delete(services) -> None:  # type: ignore[no-untyped-def]
    eid = services.journal.add("First thought.", weakness_key="missed:fork")
    e = services.journal._repo.get(eid)
    assert (e.kind, e.text, e.weakness_key, e.entry_date) == ("note", "First thought.", "missed:fork", services.plan._today().isoformat())  # fmt: skip
    services.journal.edit(eid, "Better thought.")
    assert services.journal._repo.get(eid).text == "Better thought."
    services.journal.delete(eid)
    with pytest.raises(NotFoundError):
        services.journal.edit(eid, "again")


@pytest.mark.parametrize("bad", ["", "   ", None, 5, "x" * (MAX_ENTRY + 1)])
def test_bad_text_is_refused(services, bad: Any) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.journal.add(bad)


def test_exactly_the_limit_is_allowed(services) -> None:  # type: ignore[no-untyped-def]
    assert services.journal.add("x" * MAX_ENTRY) > 0


def test_a_chosen_date_must_be_a_date(services) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.journal.add("t", entry_date="not a date")
    eid = services.journal.add("t", entry_date="2026-10-01")
    assert services.journal._repo.get(eid).entry_date == "2026-10-01"


# ---- FR-10.69: game reflections ----


def test_a_reflection_appears_in_the_game_and_the_journal_and_links_back(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    services.journal.add("On the game.", game_id=gid)
    services.journal.add("On this move.", game_id=gid, ply=4)
    notes = services.journal.game_notes(gid)
    assert [(n.ply, n.kind) for n in notes] == [(None, "reflection"), (4, "reflection")]
    entries = [i.entry for i in services.journal.timeline({"kinds": ["reflection"]}).items]
    linked = next(e for e in entries if e.text == "On this move.")
    assert (linked.game_id, linked.ply) == (gid, 4)


def test_a_note_on_a_move_needs_a_real_game(services) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.journal.add("t", ply=4)
    with pytest.raises(NotFoundError):
        services.journal.add("t", game_id=999)


# ---- FR-10.68: the daily log ----


def test_the_daily_log_matches_stats_for_the_same_day(services, clock) -> None:  # type: ignore[no-untyped-def]
    _play(services, 3)
    clock.advance(days=1)
    _play(services, 2)
    today = services.plan._today()
    rows = [
        r for r in StatsRepo(services.db).attempt_rows() if r.finished_at and clock.local_date(r.finished_at) == today
    ]
    expected = build_report(rows, display_name)
    log = services.journal.day_logs(today, today)[today.isoformat()]
    assert log.overall == expected.overall
    assert list(log.by_mode) == expected.by_mode
    assert log.overall.attempts == 2


def test_the_daily_log_counts_games_retries_plan_tasks_and_coach_runs(services) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.test_plan_service import _report

    gid = _games(services, 1)[0]
    services.review.mark_visited(gid, 0)
    RetryRepo(services.db).add(gid, 4, "e2e4", True, 0, services.plan._now())
    RetryRepo(services.db).add(gid, 4, "e2e4", False, 90, services.plan._now())
    view = _plan(services, [_puzzle_task(1)])
    services.plan.lesson_opened(view.days[0].tasks[0].task.id)
    _report(services)
    wide = services.journal.day_logs(date(2025, 1, 1), date(2027, 1, 1))
    assert sum(x.facts.retries for x in wide.values()) == 2
    assert sum(x.facts.retries_found for x in wide.values()) == 1
    assert sum(x.facts.plan_tasks_done for x in wide.values()) == 1
    assert [r for x in wide.values() for r in x.facts.coach_runs] == ["missed:fork"]


def test_a_day_with_nothing_has_no_log(services) -> None:  # type: ignore[no-untyped-def]
    today = services.plan._today()
    assert services.journal.day_logs(today, today) == {}


# ---- FR-10.70: the timeline ----


def test_newest_first_your_words_above_the_log(services, clock) -> None:  # type: ignore[no-untyped-def]
    services.journal.add("Yesterday's note.")
    clock.advance(days=1)
    _play(services, 1)
    services.journal.add("Today's note.")
    items = services.journal.timeline().items
    kinds = [("log" if i.log else i.entry.text) for i in items]
    assert kinds == ["Today's note.", "log", "Yesterday's note."]


def test_filters_and_search(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    services.journal.add("Forks again 100%", weakness_key="missed:fork")
    services.journal.add("Clock trouble")
    services.journal.add("On the game", game_id=gid)
    _play(services, 1)

    def texts(f: dict[str, Any]) -> list[str]:
        return [i.entry.text for i in services.journal.timeline(f).items if i.entry]

    assert texts({"query": "fork"}) == ["Forks again 100%"]
    assert texts({"query": "100%"}) == ["Forks again 100%"]
    assert texts({"query": "1%"}) == []  # % is a plain character, not a wildcard
    assert texts({"weakness_key": "missed:fork"}) == ["Forks again 100%"]
    assert texts({"game_id": gid}) == ["On the game"]
    assert set(texts({"kinds": ["note"]})) == {"Forks again 100%", "Clock trouble"}
    assert texts({"kinds": ["log"]}) == []
    assert all(i.log for i in services.journal.timeline({"kinds": ["log"]}).items)
    assert not any(i.log for i in services.journal.timeline({"query": "fork"}).items)
    assert texts({"date_from": "2030-01-01", "date_to": "2030-01-02"}) == []


def test_paging_reaches_older_entries(services) -> None:  # type: ignore[no-untyped-def]
    services.journal.add("Long ago.", entry_date="2025-01-01")
    page = services.journal.timeline()
    assert page.items == () and page.older is True
    found = services.journal.timeline({"date_to": "2025-01-05"})
    assert [i.entry.text for i in found.items] == ["Long ago."]
    assert services.journal.timeline({"before": page.window_start}).window_start < page.window_start


@pytest.mark.parametrize("bad", [{"other": 1}, {"kinds": ["x"]}, {"query": 5}, {"date_from": "x"}, {"game_id": "1"}])
def test_bad_filters_are_refused(services, bad: Any) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.journal.timeline(bad)


# ---- FR-10.71: what the AI would get ----


def test_prompt_items_label_games_strip_urls_and_cut(services) -> None:  # type: ignore[no-untyped-def]
    ids = _games(services, 2)
    services.journal.add("See https://lichess.org/AbCd1234 for it", game_id=ids[0], ply=4)
    services.journal.add("x" * 3000, game_id=ids[1])
    labels = {ids[0]: "G1"}
    items = services.journal.prompt_items(labels, "2020-01-01")
    by_game = {i.game: i for i in items}
    assert by_game["G1"].ply == 5 and "lichess.org" not in by_game["G1"].text
    outside = by_game[None]  # a game outside the report goes with no reference
    assert len(outside.text) == PROMPT_ENTRY_CHARS and outside.ply is None


def test_prompt_items_cover_the_reports_games_and_entries_since_its_first_game(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    services.journal.add("Old but on this game.", entry_date="2020-01-01", game_id=gid)
    services.journal.add("Old and unrelated.", entry_date="2020-01-01")
    services.journal.add("Recent.", entry_date="2026-11-04")
    texts = {i.text for i in services.journal.prompt_items({gid: "G1"}, "2026-11-01T10:00:00+00:00")}
    assert texts == {"Old but on this game.", "Recent."}


def test_prompt_items_keep_the_newest_entries(services) -> None:  # type: ignore[no-untyped-def]
    for n in range(PROMPT_ENTRIES + 5):
        services.journal.add(f"note {n}", entry_date="2026-11-04")
    items = services.journal.prompt_items({}, "2026-01-01")
    assert len(items) == PROMPT_ENTRIES
    assert items[0].text == f"note {PROMPT_ENTRIES + 4}"
