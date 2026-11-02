"""QA v0.4 against the real Stockfish 19 (`uv run pytest -m engine`): the refutation length (§7.2:
3-5 plies), awkward analysis-board positions, idle CPU, and close() during a search (NFR-6)."""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import chess
import pytest

from tests.helpers import fake_service_kwargs
from weaksquare.adapters.stockfish import StockfishEngine
from weaksquare.core.engine import validate_fen
from weaksquare.core.filters import FilterSpec

pytestmark = pytest.mark.engine


@pytest.fixture
def real_services(paths, clock, rng, fixture_puzzles_db, stockfish_path):  # type: ignore[no-untyped-def]
    import shutil

    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.app import build_services
    from weaksquare.jobs.runner import JobRunner

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    kwargs = fake_service_kwargs()
    kwargs["make_engine"] = lambda path, threads, hash_mb: StockfishEngine(path, threads, hash_mb)
    kwargs["cpu_count"] = 4
    s = build_services(paths, clock, JobRunner(), rng, **kwargs)
    # use the real exe as a "custom engine" (as if it had passed the self-test), read-only
    s.engine._settings.set("engine.custom_path", stockfish_path)
    s.engine._settings.set("engine.custom_name", "Stockfish 19")
    yield s
    s.close()


def test_qa_refutations_are_3_to_5_plies_unless_the_game_ends(real_services) -> None:  # type: ignore[no-untyped-def]
    """§7.2 step 2 with the default think time (1 s): the reply line is 3-5 plies, or shorter only
    when it ends the game."""
    s = real_services
    sid = s.sessions.start(FilterSpec(queue_size=12)).session_id
    short: list[str] = []
    checked = 0
    for _ in range(12):
        view = s.sessions.next_puzzle(sid)
        if view is None:
            break
        board = chess.Board(view.fen)
        board.push_uci(view.opponent_move)
        with s.sessions._session(sid).lock:
            expected = s.sessions._session(sid).current.state.puzzle.moves[1]
        wrong = next(
            (m.uci() for m in board.legal_moves if m.uci() != expected and not board.gives_check(m)),
            None,
        )
        if wrong is None:
            continue
        s.sessions.submit_move(sid, wrong)
        s.sessions.request_help(sid, "answer")
        r = s.sessions.get_refutation(sid)
        checked += 1
        after = chess.Board(r.fen_before)
        after.push_uci(r.wrong_move)
        for uci in r.line:
            assert chess.Move.from_uci(uci) in after.legal_moves, (view.puzzle_id, r.line)
            after.push_uci(uci)
        assert len(r.line) <= 5
        assert r.score and ("for you" in r.score or "mate" in r.score or "level" in r.score), r.score
        if len(r.line) < 3 and not after.is_game_over():
            short.append(f"{view.puzzle_id}: {wrong} -> {r.line} ({r.score})")
    assert checked >= 8
    assert not short, short


AWKWARD = [
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",  # both sides can castle both ways
    "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
    "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2",  # en passant is legal
    "4k3/8/8/8/3pP3/8/8/4K3 b - e3 0 1",  # en passant for black
    "4k3/1P6/8/8/8/8/6p1/4K3 w - - 0 1",  # both sides promote next
    "n3k3/1P6/8/8/8/8/8/4K3 w - - 0 1",  # promotion with capture
    "4k3/8/8/8/8/8/4q3/4K3 w - - 0 1",  # in check, one legal move
    "7k/8/6Q1/8/8/8/8/K7 b - - 0 1",  # black has few moves (no stalemate)
    "8/8/8/8/8/5k2/6q1/7K w - - 99 150",  # 50-move counter at 99
    "4k3/8/8/8/8/8/8/R3K3 w Q - 0 1",  # one castling right
]


def test_qa_awkward_positions_never_crash_the_real_engine(real_services, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO, logger="weaksquare")
    s = real_services
    s.engine.set_settings(think_s=0.2)
    for fen in AWKWARD:
        board = validate_fen(fen)
        player = "white" if board.turn == chess.WHITE else "black"
        a = s.engine.analyse(board, player)
        if a.game_over:
            continue
        assert a.lines, fen
        for line in a.lines:
            b = board.copy()
            for uci in line.pv:
                b.push_uci(uci)  # every shown move is legal
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "terminated" not in logged and "restarted" not in logged, logged


def _cpu_seconds(pid: int) -> float:
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"(Get-Process -Id {pid}).CPU"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out.replace(",", "."))


def test_qa_engine_is_idle_between_searches(stockfish_path: str) -> None:
    """CPU sanity: after a search the engine process uses (almost) no CPU while nobody asks."""
    e = StockfishEngine(stockfish_path, threads=2, hash_mb=64)
    try:
        e.analyse(chess.Board(), 0.5, 3)
        pid = e._engine.transport.get_pid()  # type: ignore[union-attr]
        time.sleep(0.5)
        before = _cpu_seconds(pid)
        time.sleep(4)
        after = _cpu_seconds(pid)
        assert after - before < 0.2, (before, after)
    finally:
        e.close()


def test_qa_close_during_a_real_search(stockfish_path: str) -> None:
    """NFR-6: closing while Stockfish thinks (5 s): close() returns, the search ends cleanly and the
    process is gone. Records how long close() waits."""
    e = StockfishEngine(stockfish_path, threads=1, hash_mb=16)
    e.analyse(chess.Board(), 0.1, 1)
    pid = e._engine.transport.get_pid()  # type: ignore[union-attr]
    errors: list[BaseException] = []

    def search() -> None:
        try:
            e.analyse(chess.Board(), 5.0, 3)
        except BaseException as ex:
            errors.append(ex)

    t = threading.Thread(target=search)
    t.start()
    time.sleep(0.5)
    started = time.monotonic()
    e.close()
    took = time.monotonic() - started
    t.join(10)
    print(f"\nclose() during a 5 s search took {took:.2f} s")
    assert not t.is_alive()
    alive = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    assert str(pid) not in alive
    assert took < 5.0 + 2.0
