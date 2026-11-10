"""QA v1.0: checkpoints beyond the builder's tests (REQUIREMENTS §10.8, FR-10.29, FR-10.32–10.38).

- the whole FR-10.35 life of one weakness through real checkpoints: New/Training → Improving → Fixed (two clean
  checkpoints *and* the puzzle gate) → Regressed, which goes to the top of the Suggested mix and the Progress page;
- puzzle accuracy alone never makes Fixed in a real checkpoint (games with mistakes, perfect puzzles);
- a weekday schedule that came due while the app was closed runs at the next launch; a due schedule with no new games
  does nothing; the hourly re-check keeps going;
- the count trigger is wired to a library sync (app.py's `on_new_games` hook);
- a guarded weakness keeps its status through a real checkpoint.
Temp data folders only (NFR-2); every engine and HTTP client is a fake."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_checkpoints import CLEAN, SMALL, _games, _run, _wait
from tests.integration.test_game_puzzles import Recorder
from weaksquare.core.stats import AttemptRow
from weaksquare.services.checkpoints import BACKFILL_KEY, BACKFILL_VERSION

KEY = "allowed:mateIn1"


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def cp(services, paths):  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.game_puzzles._engine = Recorder()
    services.checkpoints.set_settings(SMALL)  # every 5 games, a 10-game window
    services.coach._settings.set(BACKFILL_KEY, BACKFILL_VERSION)
    services.scheduler.pending.clear()
    return services.checkpoints


def _puzzles(services, monkeypatch, n: int, wins: int) -> None:  # type: ignore[no-untyped-def]
    """n local first tries on mateIn1, `wins` of them solved, no Lichess dashboard."""
    at = services.coach._clock.now() - timedelta(days=1)
    rows = [AttemptRow(i < wins, i < wins, i < wins, 1500, ("mateIn1",), 1, finished_at=at) for i in range(n)]
    monkeypatch.setattr(services.coach, "puzzle_sources", lambda: (rows, {}))


def _tracked(services) -> Any:  # type: ignore[no-untyped-def]
    return services.checkpoints._repo.tracked()[KEY]


def test_qa_one_weakness_goes_improving_fixed_then_regressed_and_back_to_the_top(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _puzzles(services, monkeypatch, 25, 20)  # 80% over 25: the puzzle gate passes
    _games(services, 10)
    _run(services)
    t = _tracked(services)
    assert t.status == "training" and t.baseline_per10 == 10.0 and t.themes  # trained by puzzles: the gate applies
    _games(services, 10, CLEAN)
    _run(services)
    assert _tracked(services).status == "improving" and _tracked(services).fixed_streak == 1
    _games(services, 10, CLEAN)
    _run(services)
    t = _tracked(services)
    assert t.status == "fixed" and t.status_since == 3
    notices = services.checkpoints.take_notices()
    assert any(n.number == 3 and n.change.key == KEY and (n.change.old, n.change.new) == ("improving", "fixed")
               for n in notices)  # fmt: skip
    _games(services, 10)  # the window is all mistakes again: back to 100% of the baseline
    _run(services)
    t = _tracked(services)
    assert t.status == "regressed" and t.fixed_streak == 0
    assert any((n.change.old, n.change.new) == ("fixed", "regressed") for n in services.checkpoints.take_notices())
    sug = services.coach.suggestion()
    assert sug is not None and sug.checkpoint == 4
    assert "back after improving" in sug.why[0]  # FR-10.29: Regressed is top priority
    view = services.checkpoints.progress()
    assert view.weaknesses[0].status == "regressed"  # worst first on the Progress page
    assert [p.number for p in next(c for c in view.weaknesses if c.key == KEY).points] == [1, 2, 3, 4]


def test_qa_perfect_puzzles_never_make_a_weakness_fixed_while_the_games_dont_improve(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _puzzles(services, monkeypatch, 200, 200)
    for _ in range(4):
        _games(services, 10)
        _run(services)
    t = _tracked(services)
    assert t.status in ("new", "training") and t.fixed_streak == 0


def test_qa_without_the_puzzle_gate_two_clean_checkpoints_stay_improving(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _puzzles(services, monkeypatch, 19, 19)  # 100%, but one try short of 20
    _games(services, 10)
    _run(services)
    for _ in range(2):
        _games(services, 10, CLEAN)
        _run(services)
    assert _tracked(services).status == "improving" and _tracked(services).fixed_streak == 2


def test_qa_a_weekday_schedule_that_came_due_while_closed_runs_at_the_next_launch(services, cp, clock) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    _run(services)
    weekday = (clock.now() + timedelta(days=3)).weekday()  # three days from now
    services.checkpoints.set_settings({**SMALL, "schedule": {"kind": "weekday", "days": 7, "weekday": weekday}})
    _games(services, 2)  # fewer than every_games: only the schedule can make one
    services.scheduler.pending.clear()
    services.checkpoints.start()  # launch: not that day yet
    assert services.checkpoints.running_job() is None
    clock.advance(days=4)  # "closed" past that weekday
    services.scheduler.pending.clear()
    services.checkpoints.start()  # the next launch
    _wait(services, services.checkpoints.running_job())
    last = services.checkpoints._repo.last()
    assert last.trigger == "schedule" and last.number == 2
    assert services.scheduler.delays[-1] == 3600.0  # and it keeps looking hourly
    assert not services.checkpoints.schedule_is_due()  # served for this week
    clock.advance(days=7)
    assert services.checkpoints.schedule_is_due()  # due again a week later


def test_qa_the_count_trigger_is_wired_to_a_sync_that_brought_games(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 5)
    services.games._on_new_games(5)  # what GameLibraryService calls after a sync with new games (app.py hook)
    job = services.checkpoints.running_job()
    assert job is not None
    _wait(services, job)
    assert services.checkpoints._repo.last().trigger == "count"


def test_qa_a_sync_with_no_new_games_never_starts_one(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    services.games._on_new_games(0)
    assert services.checkpoints.running_job() is None


def test_qa_a_guarded_weakness_keeps_its_status_through_a_real_checkpoint(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """FR-10.34 guard (Adam's rule): fewer than 5 seen *and* fewer than 5 expected. One game in ten with the mistake
    is a baseline of 1 per 10 (1 expected in a 10-game window); a clean window then is 0 seen, 1 expected: guarded."""
    _games(services, 1)
    _games(services, 9, CLEAN)
    _run(services)
    before = _tracked(services)
    assert before.baseline_per10 == 1.0
    _games(services, 10, CLEAN)
    _run(services)
    after = _tracked(services)
    assert after.status == before.status  # no change made from it
    metric = [m for n, m in services.checkpoints._repo.metrics() if n == 2 and m.key == KEY]
    assert metric and metric[0].guarded and metric[0].per10 == 0.0  # shown, marked "not enough data yet"
