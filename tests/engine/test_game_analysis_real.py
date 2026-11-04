"""v0.8 game analysis with the real Stockfish 19 (`uv run pytest -m engine`): a short game with an
obvious blunder is graded on the background engine, and the blunder and its refutation come out right."""

from __future__ import annotations

import chess
import pytest

from tests.helpers import fake_service_kwargs
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.adapters.stockfish import StockfishEngine

pytestmark = pytest.mark.engine

# Black's 3...Nf6?? allows 4.Qxf7#; White's 3.Bc4 is fine.
SCHOLAR = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'


@pytest.fixture
def real_services(paths, clock, rng, stockfish_path):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.app import build_services
    from weaksquare.jobs.runner import JobRunner

    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    kwargs = fake_service_kwargs()
    kwargs["make_engine"] = lambda path, threads, hash_mb: StockfishEngine(path, threads, hash_mb)
    kwargs["cpu_count"] = 4
    runner = JobRunner()
    s = build_services(paths, clock, runner, rng, **kwargs)
    s.engine._settings.set("engine.custom_path", stockfish_path)
    s.engine._settings.set("engine.custom_name", "Stockfish 19")
    yield s, runner
    s.close()


def test_the_scholars_mate_blunder_is_found_and_refuted(real_services) -> None:  # type: ignore[no-untyped-def]
    s, runner = real_services
    gid = s.games.import_pgn(SCHOLAR).game_id
    job = s.analysis.queue([gid])
    st = runner.wait(job, 60)
    assert st is not None and st.state == "done", st
    rows = GameAnalysisRepo(s.db).rows(gid)
    assert len(rows) == 7
    nf6 = rows[5]
    assert nf6.move_san == "Nf6" and nf6.classification == "blunder" and nf6.kind == "allowed"
    assert nf6.refutation[:1] == ("h5f7",)  # the mate
    assert nf6.best_move and nf6.best_move != "g8f6"
    assert len(nf6.lines) == 3  # MultiPV 3
    for r in rows:  # every stored line replays legally from its position
        for line in r.lines:
            b = chess.Board(r.fen_before)
            for uci in line.pv:
                b.push_uci(uci)
    assert rows[6].classification == "best"
