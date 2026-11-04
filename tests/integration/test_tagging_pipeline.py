"""v0.10 tags in the analysis pipeline: themes on Missed / Allowed mistakes (FR-10.12), habits on errors
(FR-10.27), re-tagging after a threshold change, and themes on puzzles saved from Game Review."""

from __future__ import annotations

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_game_analysis import MATE, _wait
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _analyzed(services, paths) -> int:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    gid = services.games.import_pgn(MATE).game_id
    assert _wait(services, services.analysis.queue([gid])) == "done"
    return int(gid)


def test_an_allowed_mate_is_tagged_with_lichess_themes(services, paths) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed(services, paths)
    rows = GameAnalysisRepo(services.db).rows(gid)
    nf6 = rows[5]  # 3...Nf6?? allows Qxf7#
    assert nf6.classification == "blunder" and nf6.kind == "allowed"
    assert {"mateIn1", "mate"} <= set(nf6.themes)
    assert all(not r.themes for r in rows if r.kind is None)  # only Missed / Allowed lines get themes


def test_retag_after_a_threshold_change_follows_the_new_grades(services, paths) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed(services, paths)
    repo = GameAnalysisRepo(services.db)
    before = {r.ply for r in repo.rows(gid) if r.habits or r.themes}
    services.analysis.set_settings(thresholds={"inaccuracy": 1500, "mistake": 1600, "blunder": 1700})
    rows = repo.rows(gid)
    assert all(
        not r.themes and not r.habits for r in rows if r.classification not in ("inaccuracy", "mistake", "blunder")
    )
    assert rows[5].classification == "blunder"  # a mate swing stays a blunder at any threshold
    assert {r.ply for r in rows if r.habits or r.themes} <= before
    services.analysis.set_settings(thresholds={"inaccuracy": 50, "mistake": 100, "blunder": 200})
    assert "mateIn1" in repo.rows(gid)[5].themes


def test_retag_is_idempotent(services, paths) -> None:  # type: ignore[no-untyped-def]
    _analyzed(services, paths)
    assert services.analysis.retag() == 0  # the analysis already stored the tags


def test_a_saved_puzzle_gets_its_themes(services, paths) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed(services, paths)
    pid, created = services.review.save_as_puzzle(gid, 6)  # 4. Qxf7#: the position before the mate
    assert created
    with services.db.session() as conn:
        themes = conn.execute("SELECT themes FROM custom_puzzles WHERE id = ?", (pid,)).fetchone()[0]
    assert "mateIn1" in themes.split()
