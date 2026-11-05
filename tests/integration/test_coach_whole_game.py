"""v0.11 whole-game coaching in the Coach run (FR-10.52, 10.53, 10.57): digests are built from the stored
analysis with no engine, reused across runs, rebuilt when the analysis changes; the report carries the
measures and the whole-game weaknesses; old reports still load."""

from __future__ import annotations

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_game_puzzles import _rows
from weaksquare.adapters.db.repos.coach import DigestsRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.services import coach as coach_module


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = coach_module.build_digest

    def counting(**kw):  # type: ignore[no-untyped-def]
        calls.append(len(kw["rows"]))
        return real(**kw)

    monkeypatch.setattr(coach_module, "build_digest", counting)
    return calls


def test_a_run_builds_digests_and_reports_the_measures(services, paths, builds) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    (gid,) = set(_my_games(services, 1))
    rid = _run(services, {"source": "games", **ANY_GAME})
    assert len(builds) == 1
    assert set(DigestsRepo(services.db).get([gid])) == {(gid, "white")}
    row, _ = services.coach.report(rid)
    ms = row.report["measures"]
    assert ms["games"] == 1 and ms["min_games"] == 5
    assert all(o["enough"] is False for o in ms["openings"])  # 1 game: not enough data for any group
    assert row.report["whole_game"] == []  # so no whole-game weakness
    assert {"missed", "allowed", "habits", "weaknesses"} <= set(row.report)  # v0.10's report is unchanged


def test_digests_are_reused_and_need_no_engine(services, paths, builds) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    _run(services, {"source": "games", **ANY_GAME})
    engine_calls = [len(e.calls) for e in FakeEngine.instances]
    puzzle_calls = len(services.game_puzzles._engine.calls)
    builds.clear()
    _run(services, {"source": "games", **ANY_GAME})
    assert builds == []  # reused
    assert [len(e.calls) for e in FakeEngine.instances] == engine_calls  # no engine pass
    assert len(services.game_puzzles._engine.calls) == puzzle_calls


def test_a_changed_analysis_rebuilds_its_digest(services, paths, builds) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    (gid,) = set(_my_games(services, 1))
    _run(services, {"source": "games", **ANY_GAME})
    builds.clear()
    services.coach.digests([gid], "me")
    assert builds == []
    GameAnalysisRepo(services.db).replace(gid, _rows(), "analyzed", 0.5, "Stockfish 19")
    services.coach.digests([gid], "me")
    assert len(builds) == 1


def test_mistake_reasons_are_added_when_read(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    (gid,) = set(_my_games(services, 1))
    _run(services, {"source": "games", **ANY_GAME})
    ((_, d),) = services.coach.digests([gid], "me")
    plies = [m.ply for m in d.moments]
    assert plies and all(m.reason is None for m in d.moments)
    ((_, d2),) = services.coach.digests([gid], "me", {(gid, plies[0] - 1): "didntLook"})
    assert d2.moments[0].reason == "didntLook"
    ((_, d3),) = services.coach.digests([gid], "me")
    assert d3.moments[0].reason is None  # the stored digest has none


def test_an_unanalyzed_game_has_no_digest(services) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.test_game_analysis import MATE

    gid = int(services.games.import_pgn(MATE).game_id)
    assert services.coach.digests([gid], "me") == []


def test_an_old_report_without_measures_still_loads(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    rid = _run(services, {"source": "games", **ANY_GAME})
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE coach_reports SET report_json = json_remove(report_json, '$.measures', '$.whole_game') WHERE id = ?",
            (rid,),
        )
    rid2 = _run(services, {"source": "games", **ANY_GAME})
    _, trend = services.coach.report(rid2)
    assert isinstance(trend, dict)
    row, _ = services.coach.report(rid)
    assert "measures" not in row.report
