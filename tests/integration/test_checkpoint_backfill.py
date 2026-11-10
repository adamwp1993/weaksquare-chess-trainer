"""v1.0 backfill (v1.0 planning, REQUIREMENTS FR-10.34): your analyzed games replayed once into reconstructed
checkpoints with statuses, from stored analysis only. It saves no reports, makes no notices, resumes when cut short,
runs once, and comes before any live checkpoint."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_checkpoints import CLEAN, SMALL, _games, _wait
from tests.integration.test_game_puzzles import Recorder, _rows
from weaksquare.core.errors import ConflictError
from weaksquare.jobs.runner import JobCancelled
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
    services.scheduler.pending.clear()
    return services.checkpoints


def _history(services) -> list[int]:  # type: ignore[no-untyped-def]
    """60 analyzed and tagged games: 50 with mistakes (the baseline), then 5 clean, then 1 with mistakes and 4 clean.
    Tagged as the analysis pipeline does (the backfill reads stored tags and never re-tags)."""
    ids = [*_games(services, 50), *_games(services, 5, CLEAN), *_games(services, 1), *_games(services, 4, CLEAN)]
    services.analysis.retag(ids)
    return ids


def _no_engine(services, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def refuse(*a: Any, **k: Any) -> None:
        raise AssertionError("the backfill must not analyze anything")

    monkeypatch.setattr(services.coach._analysis, "queue", refuse)
    monkeypatch.setattr(services.coach._analysis, "retag", refuse)
    monkeypatch.setattr(services.coach._puzzles, "process_game", refuse)


def _backfill(services) -> Any:  # type: ignore[no-untyped-def]
    services.checkpoints.start()
    return _wait(services, services.checkpoints.running_job())


def _repo(services):  # type: ignore[no-untyped-def]
    return services.checkpoints._repo


def _reports(services) -> int:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM coach_reports").fetchone()[0])


def test_the_backfill_rebuilds_points_and_statuses_from_stored_analysis(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ids = _history(services)
    _no_engine(services, monkeypatch)
    st = _backfill(services)
    assert st.message == "Rebuilt 3 checkpoints from your past games."
    cps = _repo(services).all()
    assert [c.number for c in cps] == [1, 2, 3]
    assert all(c.reconstructed and c.trigger == "backfill" and c.report_id is None for c in cps)
    assert [c.game_ids[-1] for c in cps] == [ids[49], ids[54], ids[59]]  # one per 5 games after the baseline
    assert all(len(c.game_ids) == 10 for c in cps)
    with services.db.session() as conn:
        played = conn.execute("SELECT played_at FROM games WHERE id = ?", (ids[59],)).fetchone()[0]
    assert cps[-1].created_at == played == cps[-1].newest_played_at  # dated when those games were played
    assert _reports(services) == 0  # no Coach report for a reconstructed checkpoint
    assert KEY in _repo(services).tracked()  # measured from the stored tags
    assert services.coach._settings.get(BACKFILL_KEY) == BACKFILL_VERSION


def test_statuses_follow_the_live_rules_checkpoint_by_checkpoint(services, cp) -> None:  # type: ignore[no-untyped-def]
    _history(services)
    _backfill(services)
    t = _repo(services).tracked()[KEY]
    assert t.baseline_per10 == 10.0 and t.baseline_games == 50 and t.first_checkpoint == 1
    points = [(n, m) for n, m in _repo(services).metrics() if m.key == KEY]
    assert [m.per10 for _, m in points] == [10.0, 5.0, 1.0]
    # 100% → New; 50% → Improving (streak 1); 10% → streak 2, but no puzzles solved on its themes: still Improving
    assert [m.status for _, m in points] == ["new", "improving", "improving"]
    assert t.status == "improving" and t.fixed_streak == 2


def test_the_mix_is_rebuilt_once_at_the_end(services, cp) -> None:  # type: ignore[no-untyped-def]
    _history(services)
    _backfill(services)
    sug = services.coach.suggestion()
    assert sug is not None and sug.checkpoint == 3 and sug.report_id == 0


def test_a_backfill_makes_no_notices(services, cp) -> None:  # type: ignore[no-untyped-def]
    _history(services)
    _backfill(services)
    assert services.checkpoints.take_notices() == []


def test_it_runs_once(services, cp) -> None:  # type: ignore[no-untyped-def]
    _history(services)
    _backfill(services)
    services.checkpoints.start()
    job = services.checkpoints.running_job()
    if job:
        _wait(services, job)
    assert len(_repo(services).all()) == 3


def test_a_backfill_cut_short_resumes_and_ends_the_same(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _history(services)
    real = services.coach.measure_stored
    calls = [0]

    def flaky(*a: Any, **k: Any) -> Any:
        calls[0] += 1
        if calls[0] == 3:  # the first point is baseline + window; stop during the second
            raise JobCancelled()
        return real(*a, **k)

    monkeypatch.setattr(services.coach, "measure_stored", flaky)
    services.checkpoints.start()
    st = services.checkpoints._runner.wait(services.checkpoints.running_job(), 30)
    assert st is not None and st.state == "cancelled"
    assert [c.number for c in _repo(services).all()] == [1]
    assert services.checkpoints.backfill_pending()

    monkeypatch.setattr(services.coach, "measure_stored", real)
    _backfill(services)  # the next launch
    assert [c.number for c in _repo(services).all()] == [1, 2, 3]
    points = [m for _, m in _repo(services).metrics() if m.key == KEY]
    assert [m.per10 for m in points] == [10.0, 5.0, 1.0] and _repo(services).tracked()[KEY].fixed_streak == 2


def test_fewer_than_50_games_is_skipped_and_the_first_checkpoint_sets_baselines(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 20)
    st = _backfill(services)
    assert st.message.startswith("Not enough analyzed games") and _repo(services).all() == []
    assert not services.checkpoints.backfill_pending()
    _wait(services, services.checkpoints.run_now())
    first = _repo(services).last()
    assert first.number == 1 and not first.reconstructed and _repo(services).tracked()[KEY].first_checkpoint == 1


def test_unanalyzed_games_arent_replayed(services, cp) -> None:  # type: ignore[no-untyped-def]
    ids = _history(services)
    with services.db.transaction() as conn:
        conn.execute(f"UPDATE games SET analysis_status = 'none' WHERE id IN ({','.join(map(str, ids[:20]))})")
    st = _backfill(services)
    assert st.message.startswith("Not enough analyzed games")  # 40 analyzed: under the 50 a baseline needs


def test_no_live_checkpoint_before_the_backfill(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    services.checkpoints.after_new_games(6)
    assert services.checkpoints.running_job() is None
    with pytest.raises(ConflictError):
        services.checkpoints.run_now()


def test_live_checkpoints_carry_on_after_the_backfill(services, cp) -> None:  # type: ignore[no-untyped-def]
    _history(services)
    _backfill(services)
    assert services.checkpoints.new_games() == 0
    _games(services, 5, _rows())
    services.checkpoints.after_new_games(5)
    _wait(services, services.checkpoints.running_job())
    live = _repo(services).last()
    assert live.number == 4 and not live.reconstructed and live.report_id is not None
    t = _repo(services).tracked()[KEY]
    assert t.baseline_per10 == 10.0  # frozen from the backfill's baseline
    # The window is now 6 games with mistakes out of 10: 60% of baseline, still Improving, and the Fixed streak resets.
    assert t.status == "improving" and t.fixed_streak == 0
