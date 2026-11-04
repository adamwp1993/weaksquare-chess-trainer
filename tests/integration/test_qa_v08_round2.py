"""QA v0.8 round 2 (independent): edge cases of the B1, B2 and B5 fixes. Tests marked xfail(strict=True)
document an open bug by its ID (qa/QA-v0.8.md)."""

from __future__ import annotations

import time

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_game_library import Rig, rig  # noqa: F401  (the fixture)
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.game_review import Thresholds, regrade
from weaksquare.core.puzzle_files import EntryError, parse_csv

MATE = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
LOW = Thresholds(1, 2, 3)


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def test_qa_r2_regrading_after_an_analysis_matches_the_new_thresholds(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    gid = services.games.import_pgn(MATE).game_id
    st = services.analysis._runner.wait(services.analysis.queue([gid]), 10)
    assert st is not None and st.state == "done"
    services.analysis.set_settings(thresholds={"inaccuracy": 1, "mistake": 2, "blunder": 3})
    rows = GameAnalysisRepo(services.db).rows(gid)
    assert [r.classification for r in rows] == [regrade(r, LOW).classification for r in rows]


# Regression test for v0.8-B10 (fixed in the QA fix loop).
def test_qa_r2_thresholds_changed_while_a_game_is_analyzed_reach_that_game(services, paths) -> None:  # type: ignore[no-untyped-def]
    import threading

    plant_managed_install(paths)
    gid = services.games.import_pgn(MATE).game_id
    gate = threading.Event()
    real_init = FakeEngine.__init__

    def gated(self, path="fake.exe", threads=1, hash_mb=16):  # type: ignore[no-untyped-def]
        real_init(self, path, threads, hash_mb)
        if threads == 6:  # the background engine only
            self.gate = gate

    FakeEngine.__init__ = gated  # type: ignore[method-assign]
    try:
        job = services.analysis.queue([gid])
        for _ in range(300):
            if any(e.entered.is_set() for e in FakeEngine.instances):
                break
            time.sleep(0.01)
        services.analysis.set_settings(thresholds={"inaccuracy": 1, "mistake": 2, "blunder": 3})
    finally:
        gate.set()
        FakeEngine.__init__ = real_init  # type: ignore[method-assign]
    st = services.analysis._runner.wait(job, 10)
    assert st is not None and st.state == "done"
    rows = GameAnalysisRepo(services.db).rows(gid)
    # Expected: the game is graded with the thresholds in force when you read it.
    assert [r.classification for r in rows] == [regrade(r, LOW).classification for r in rows]


# Regression test for v0.8-B11 (fixed in the QA fix loop).
def test_qa_r2_a_username_whose_game_isnt_found_is_not_linked(rig: Rig) -> None:  # noqa: F811
    job = rig.svc.start_url_import("https://www.chess.com/game/live/100000077", chesscom_username="player_typo")
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "failed"
    # Expected: a name that found nothing isn't linked (sync would then pull that account's public games).
    assert rig.svc.settings().chesscom_username is None


# Regression test for v0.8-B12 (fixed in the QA fix loop).
def test_qa_r2_a_csv_at_the_cap_with_a_trailing_blank_line_is_not_over_the_cap() -> None:
    row = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1,a1a8"
    out = parse_csv("fen,solution\n" + row + "\n" + row + "\n\n", max_entries=2)
    assert not any(isinstance(e, EntryError) for e in out), out


def test_qa_r2_a_csv_over_the_cap_says_so_once() -> None:
    row = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1,a1a8"
    out = parse_csv("fen,solution\n" + (row + "\n") * 5, max_entries=3)
    errors = [e for e in out if isinstance(e, EntryError)]
    assert len(out) == 4 and len(errors) == 1 and "more than 3" in errors[0].reason
