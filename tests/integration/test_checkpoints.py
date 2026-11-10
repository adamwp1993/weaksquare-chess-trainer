"""v1.0 checkpoints end to end (REQUIREMENTS §10.8, FR-10.32–10.38): a checkpoint saves a normal Coach report and
its metrics, statuses move across checkpoints, the triggers (count, schedule, Run now), the Suggested mix's banner
rule, notices, and what a checkpoint must never touch (your plan, another player's games)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import api_for
from tests.integration.test_game_puzzles import Recorder, _filler, _rows
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.services.checkpoints import BACKFILL_KEY, BACKFILL_VERSION, NOTICES_SEEN_KEY, SCHEDULE_LAST_KEY

SMALL = {"every_games": 5, "window": 10}  # the smallest settings, so the tests stay quick
CLEAN = [_filler(p) for p in range(16)]  # a game with no mistakes


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def cp(services, paths):  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.game_puzzles._engine = Recorder()
    services.checkpoints.set_settings(SMALL)
    services.coach._settings.set(BACKFILL_KEY, BACKFILL_VERSION)  # these tests are about live checkpoints
    services.scheduler.pending.clear()
    return services.checkpoints


_day = [0]


def _pgn(i: int) -> str:
    """A distinct short legal game per number (the library keeps one copy of identical move lists)."""
    board = chess.Board()
    sans = []
    for k in range(3):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())
        move = moves[(i // 20**k) % len(moves)]
        sans.append(board.san(move))
        board.push(move)
    return " ".join(sans) + " *"


def _game(services, rows: list[Any]) -> int:  # type: ignore[no-untyped-def]
    _day[0] += 1
    gid = int(services.games.import_pgn(_pgn(_day[0])).game_id)
    services.games.set_user_color(gid, "white")
    GameAnalysisRepo(services.db).replace(gid, rows, "analyzed", 0.3, "Stockfish 19")
    return gid


def _games(services, n: int, rows: Any = None) -> list[int]:  # type: ignore[no-untyped-def]
    """n eligible games of yours (Lichess, rated rapid), each played a day after the last."""
    ids = []
    for _ in range(n):
        gid = _game(services, list(rows) if rows is not None else _rows())
        _day[0] += 1
        played = (services.coach._clock.now() - timedelta(days=400) + timedelta(days=_day[0])).isoformat()
        with services.db.transaction() as conn:
            conn.execute("UPDATE games SET source = 'lichess', rated = 1, time_class = 'rapid', played_at = ? WHERE id = ?",
                         (played, gid))  # fmt: skip
        ids.append(gid)
    return ids


def _wait(services, job: str | None) -> Any:  # type: ignore[no-untyped-def]
    assert job is not None
    st = services.checkpoints._runner.wait(job, 30)
    assert st is not None and st.state == "done", (st.state, st.message) if st else None
    return st


def _run(services) -> Any:  # type: ignore[no-untyped-def]
    return _wait(services, services.checkpoints.run_now())


def _repo(services):  # type: ignore[no-untyped-def]
    return services.checkpoints._repo


def test_run_now_saves_a_checkpoint_with_a_normal_coach_report(services, cp) -> None:  # type: ignore[no-untyped-def]
    ids = _games(services, 6)
    st = _run(services)
    assert st.message.startswith("Checkpoint #1 saved: 6 games")
    last = _repo(services).last()
    assert last.number == 1 and last.trigger == "manual" and not last.reconstructed
    assert sorted(last.game_ids) == sorted(ids) and last.report_id is not None
    row, _ = services.coach.report(last.report_id)
    assert row.subject == "me" and row.report["checkpoint"] == 1 and sorted(row.game_ids) == sorted(ids)
    assert last.health["per10"]["blunders"] > 0 and last.health["games"] == 6
    tracked = _repo(services).tracked()
    assert "allowed:mateIn1" in tracked and tracked["allowed:mateIn1"].first_checkpoint == 1
    assert tracked["allowed:mateIn1"].status == "training"  # it's in the new Suggested mix
    sug = services.coach.suggestion()
    assert sug is not None and sug.checkpoint == 1 and not sug.pending


def test_the_report_shows_under_since_last_report(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    _run(services)
    _games(services, 6, CLEAN)
    _run(services)
    second = _repo(services).last()
    cmp = services.coach.comparison(second.report_id)
    assert cmp is not None  # compared with the first checkpoint's report like any other


def test_statuses_move_across_checkpoints_and_make_notices(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 10)
    _run(services)
    assert services.checkpoints.take_notices() == []  # newly detected isn't a notice
    _games(services, 10, CLEAN)  # the window is now all clean games
    _run(services)
    t = _repo(services).tracked()["allowed:mateIn1"]
    assert t.status == "improving" and t.fixed_streak == 1 and t.baseline_per10 == 10.0
    notices = services.checkpoints.take_notices()
    assert any(n.change.key == "allowed:mateIn1" and n.change.new == "improving" for n in notices)
    assert services.checkpoints.take_notices() == []  # once
    _games(services, 10, CLEAN)
    _run(services)
    t = _repo(services).tracked()["allowed:mateIn1"]
    assert t.fixed_streak == 2 and t.status == "improving"  # no puzzles solved on its themes: not Fixed yet


def test_points_are_saved_per_checkpoint_for_the_charts(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 10)
    _run(services)
    _games(services, 10, CLEAN)
    _run(services)
    view = services.checkpoints.progress()
    card = next(c for c in view.weaknesses if c.key == "allowed:mateIn1")
    assert [p.number for p in card.points] == [1, 2] and [p.per10 for p in card.points] == [10.0, 0.0]
    assert card.baseline_per10 == 10.0 and card.current_per10 == 0.0
    assert [c.number for c in view.checkpoints] == [1, 2]


def test_filters_you_changed_get_the_banner_not_replaced(services, cp) -> None:  # type: ignore[no-untyped-def]
    mine = FilterSpec(themes=("pin",)).to_json()
    services.coach._settings.set("mixer.filters", mine)
    _games(services, 6)
    _run(services)
    sug = services.coach.suggestion()
    assert sug is not None and sug.pending and sug.checkpoint == 1
    assert services.coach._settings.get("mixer.filters") == mine


def test_a_checkpoint_never_touches_your_plan(services, cp) -> None:  # type: ignore[no-untyped-def]
    def plan_tables() -> list[list[tuple]]:  # type: ignore[type-arg]
        with services.db.session() as conn:
            return [conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                    for t in ("training_plans", "plan_days", "plan_tasks")]  # fmt: skip

    _games(services, 6)
    services.coach.start_run({"source": "games", "rated_only": False, "time_classes": []})
    services.coach._runner.wait(services.coach._runner.active("coach_run")[0].id, 30)
    services.plan.create({"weeks": 1})
    before = plan_tables()
    assert before[0]
    _games(services, 6)
    _run(services)
    assert plan_tables() == before


def test_another_players_games_never_count(services, cp) -> None:  # type: ignore[no-untyped-def]
    theirs = _games(services, 6)
    with services.db.transaction() as conn:
        for gid in theirs:
            conn.execute("UPDATE game_subjects SET subject = 'lichess:someone' WHERE game_id = ?", (gid,))
    assert services.checkpoints.new_games() == 0
    st = _run(services)
    assert st.message.startswith("No eligible games") and _repo(services).last() is None


def test_unrated_and_blitz_games_arent_eligible_by_default(services, cp) -> None:  # type: ignore[no-untyped-def]
    ids = _games(services, 6)
    with services.db.transaction() as conn:
        conn.execute(f"UPDATE games SET rated = 0 WHERE id IN ({ids[0]}, {ids[1]})")
        conn.execute(f"UPDATE games SET time_class = 'blitz' WHERE id = {ids[2]}")
    assert services.checkpoints.new_games() == 3


# ---- triggers (FR-10.32) ---------------------------------------------------------------------------------------


def test_the_count_trigger_fires_at_n_new_games_not_before(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 4)
    services.checkpoints.after_new_games(4)
    assert services.checkpoints.running_job() is None and _repo(services).last() is None
    _games(services, 1)
    services.checkpoints.after_new_games(1)
    job = services.checkpoints.running_job()
    _wait(services, job)
    assert _repo(services).last().trigger == "count"
    assert services.checkpoints.new_games() == 0


def test_the_count_starts_again_after_each_checkpoint(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    _run(services)
    _games(services, 4)
    assert services.checkpoints.new_games() == 4
    services.checkpoints.after_new_games(4)
    assert services.checkpoints.running_job() is None


def test_launch_runs_a_checkpoint_that_came_due(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 5)
    services.checkpoints.start()
    _wait(services, services.checkpoints.running_job())
    assert _repo(services).last().trigger == "count"
    assert services.scheduler.delays[-1] == 3600.0  # and it looks again hourly


def test_a_due_schedule_runs_while_the_app_is_open(services, cp, clock) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    _run(services)
    services.checkpoints.set_settings({**SMALL, "schedule": {"kind": "days", "days": 2, "weekday": 6}})
    _games(services, 2)  # fewer than every_games: only the schedule can run it
    services.scheduler.run_next()  # the check after the settings change: not due yet
    assert services.checkpoints.running_job() is None
    clock.advance(days=2)
    services.scheduler.run_next()
    _wait(services, services.checkpoints.running_job())
    assert _repo(services).last().trigger == "schedule" and _repo(services).last().number == 2


def test_a_due_schedule_with_no_new_games_does_nothing(services, cp, clock) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    _run(services)
    services.checkpoints.set_settings({**SMALL, "schedule": {"kind": "days", "days": 1, "weekday": 6}})
    clock.advance(days=1)
    services.checkpoints.start()
    st = _wait(services, services.checkpoints.running_job())
    assert st.message == "No new games since the last checkpoint." and _repo(services).last().number == 1
    assert services.coach._settings.get(SCHEDULE_LAST_KEY) is not None
    assert not services.checkpoints.schedule_is_due()  # served: not due again until next time


def test_one_checkpoint_at_a_time(services, cp) -> None:  # type: ignore[no-untyped-def]
    _games(services, 6)
    job = services.checkpoints.run_now()
    with pytest.raises(ConflictError):
        services.checkpoints.run_now()
    _wait(services, job)


def test_a_coach_run_going_puts_the_checkpoint_off(services, cp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runner = services.checkpoints._runner
    real = runner.active
    monkeypatch.setattr(runner, "active", lambda kind=None: ["busy"] if kind == "coach_run" else real(kind))
    _games(services, 6)
    with pytest.raises(ConflictError):
        services.checkpoints.run_now()
    assert 60.0 in services.scheduler.delays  # looked at again in a minute


# ---- settings and the bridge -----------------------------------------------------------------------------------


def test_settings_round_trip_through_the_bridge(services, cp, paths, clock) -> None:  # type: ignore[no-untyped-def]
    api = api_for(services, paths, clock, services.checkpoints._runner)
    s = api.get_checkpoint_settings()["data"]
    assert s["every_games"] == 5 and s["auto_ai"] is True and s["notices"] is True
    out = api.set_checkpoint_settings(
        {**SMALL, "every_games": 50, "schedule": {"kind": "weekday", "days": 7, "weekday": 0}}
    )["data"]
    assert out["every_games"] == 50 and out["schedule"]["kind"] == "weekday"
    assert api.get_checkpoint_settings()["data"]["every_games"] == 50
    bad = api.set_checkpoint_settings({"every_games": 1})
    assert bad["ok"] is False and bad["error"]["code"] == "invalid_argument"


def test_progress_and_notices_through_the_bridge(services, cp, paths, clock) -> None:  # type: ignore[no-untyped-def]
    api = api_for(services, paths, clock, services.checkpoints._runner)
    empty = api.get_progress()["data"]
    assert empty["weaknesses"] == [] and empty["checkpoints"] == [] and empty["new_games"] == 0
    _games(services, 10)
    _wait(services, api.run_checkpoint_now()["data"])
    _games(services, 10, CLEAN)
    _wait(services, api.run_checkpoint_now()["data"])
    view = api.get_progress()["data"]
    card = next(c for c in view["weaknesses"] if c["key"] == "allowed:mateIn1")
    assert card["status"] == "improving" and len(card["points"]) == 2 and card["examples"] == []
    notices = api.take_status_notices()["data"]
    assert any(n["change"]["new"] == "improving" for n in notices)
    assert api.take_status_notices()["data"] == []
    # The second window is all clean games: nothing to build a mix from, so checkpoint #1's mix stays.
    label = api.get_suggestion()["data"]["label"]
    assert label.startswith("Suggested — from checkpoint #1")


def test_notices_off_shows_none_and_marks_them_seen(services, cp) -> None:  # type: ignore[no-untyped-def]
    services.checkpoints.set_settings({**SMALL, "notices": False})
    _games(services, 10)
    _run(services)
    _games(services, 10, CLEAN)
    _run(services)
    assert services.checkpoints.take_notices() == []
    assert services.coach._settings.get(NOTICES_SEEN_KEY) == 2


def test_bad_settings_change_nothing(services, cp) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.checkpoints.set_settings({"window": 5})
    assert services.checkpoints.settings().window == 10
