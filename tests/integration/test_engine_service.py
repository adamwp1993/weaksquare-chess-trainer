"""EngineService and the session's engine calls (FR-7.2–7.7, §7.2 step 2) with the fake engine."""

from __future__ import annotations

import threading

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from weaksquare.core.engine import EngineError, EngineNotInstalled
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def solution(services, puzzle_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT moves FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()[0].split()


def start(services):  # type: ignore[no-untyped-def]
    sid = services.sessions.start(FilterSpec(queue_size=5)).session_id
    view = services.sessions.next_puzzle(sid)
    return sid, view, solution(services, view.puzzle_id)


def wrong_move(view, moves: list[str]) -> str:  # type: ignore[no-untyped-def]
    board = chess.Board(view.fen)
    board.push_uci(view.opponent_move)
    return next(m.uci() for m in board.legal_moves if m.uci() != moves[1] and not board.gives_check(m))


def start_fen(view) -> str:  # type: ignore[no-untyped-def]
    board = chess.Board(view.fen)
    board.push_uci(view.opponent_move)
    return board.fen()


# ---- status, settings ---------------------------------------------------------------------------


def test_status_not_installed_then_managed(services, paths) -> None:  # type: ignore[no-untyped-def]
    st = services.engine.status()
    assert (st.state, st.source, st.tag) == ("not_installed", None, "sf_19")
    exe = plant_managed_install(paths)
    st = services.engine.status()
    assert (st.state, st.source, st.name, st.path) == ("ready", "managed", "Stockfish 19", str(exe))


def test_settings_defaults_and_validation(services) -> None:  # type: ignore[no-untyped-def]
    st = services.engine.settings()
    assert (st.think_s, st.threads, st.hash_mb, st.custom_path, st.max_threads) == (1.0, 7, 256, None, 8)  # FR-7.4
    st = services.engine.set_settings(think_s=2.5, threads=4, hash_mb=512)
    assert (st.think_s, st.threads, st.hash_mb) == (2.5, 4, 512)
    for bad in ({"think_s": 0.1}, {"think_s": 11}, {"think_s": "1"}, {"threads": 0}, {"threads": 9},
                {"threads": 2.5}, {"threads": True}, {"hash_mb": 8}, {"hash_mb": 4096}):  # fmt: skip
        with pytest.raises(ValidationError):
            services.engine.set_settings(**bad)
    assert services.engine.settings().threads == 4  # nothing changed by the refused calls


def test_settings_apply_to_a_running_engine(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.engine.analyse(chess.Board(), "white")
    services.engine.set_settings(threads=3, hash_mb=128)
    assert FakeEngine.instances[0].options == (3, 128)
    services.engine.set_settings(think_s=0.5)
    services.engine.analyse(chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1"), "white")
    assert FakeEngine.instances[0].calls[-1][1] == 0.5


def test_custom_engine_is_saved_only_after_the_probe(services, tmp_path) -> None:  # type: ignore[no-untyped-def]
    good = tmp_path / "myfish.exe"
    good.write_bytes(b"MZ")
    broken = tmp_path / "broken.exe"
    broken.write_bytes(b"MZ")
    job = services.engine.start_custom_check(str(broken))
    st = services.engine._runner.wait(job)
    assert st.state == "failed" and st.error_code == "smoke_test_failed"
    assert services.engine.settings().custom_path is None
    st = services.engine._runner.wait(services.engine.start_custom_check(str(tmp_path / "missing.exe")))
    assert st.state == "failed" and st.error_code == "not_found"
    for bad in ("", "notes.txt", 5):
        with pytest.raises(ValidationError):
            services.engine.start_custom_check(bad)

    st = services.engine._runner.wait(services.engine.start_custom_check(str(good)))
    assert st.state == "done" and "Custom Fish 2" in st.message
    status = services.engine.status()
    assert (status.state, status.source, status.name, status.path) == ("ready", "custom", "Custom Fish 2", str(good))
    services.engine.analyse(chess.Board(), "white")
    assert FakeEngine.instances[-1].path == str(good)  # the custom engine overrides the managed one

    good.unlink()
    assert services.engine.status().state == "custom_invalid"
    services.engine.clear_custom()
    assert services.engine.status().state == "not_installed"
    assert FakeEngine.instances[-1].closed


def test_install_job_conflict_and_unsupported_message(services) -> None:  # type: ignore[no-untyped-def]
    gate = threading.Event()
    services.engine._installer._d = services.engine._installer._d.__class__(
        **{**services.engine._installer._d.__dict__, "http": _BlockingHttp(gate)}
    )
    job = services.engine.start_install()
    with pytest.raises(ConflictError):
        services.engine.start_install()
    assert services.engine.status().install_job_id == job
    gate.set()
    st = services.engine._runner.wait(job)
    assert st.state == "failed" and st.error_code == "download_failed"
    assert services.engine.status().install_job_id is None


class _BlockingHttp:
    def __init__(self, gate: threading.Event) -> None:
        self.gate = gate

    def download(self, url, dest, *, progress=None, cancelled=lambda: False):  # type: ignore[no-untyped-def]
        self.gate.wait(5)
        raise OSError("offline")


# ---- FR-7.3: nothing during the puzzle ---------------------------------------------------------


def test_no_engine_output_while_the_puzzle_is_in_progress(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid, view, moves = start(services)
    fen = start_fen(view)
    with pytest.raises(ConflictError):
        services.sessions.analyze(sid, fen)
    services.sessions.submit_move(sid, wrong_move(view, moves))  # lost, but still in progress
    with pytest.raises(ConflictError):
        services.sessions.analyze(sid, fen)
    with pytest.raises(ConflictError):
        services.sessions.get_refutation(sid)
    if len(moves) > 2:  # a hint mid-puzzle doesn't finish it either
        services.sessions.submit_move(sid, moves[1])
        services.sessions.request_help(sid, "hint")
        with pytest.raises(ConflictError):
            services.sessions.analyze(sid, fen, "board")
    assert FakeEngine.instances == []  # the engine never even started


def test_engine_after_the_line_is_complete(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid, view, moves = start(services)
    for uci in moves[1::2]:
        services.sessions.submit_move(sid, uci)
    a = services.sessions.analyze(sid, start_fen(view), "start")
    assert len(a.lines) == 3 and all(line.score for line in a.lines)  # MultiPV 3 (FR-7.2)
    assert all(line.score.endswith("for you") or line.score.startswith("You") or "level" in line.score
               for line in a.lines)  # fmt: skip
    again = services.sessions.analyze(sid, start_fen(view), "panel")
    assert again == a and len(FakeEngine.instances[0].calls) == 1  # cached per position


def test_refutation_after_show_answer(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid, view, moves = start(services)
    bad = wrong_move(view, moves)
    services.sessions.submit_move(sid, bad)
    help_ = services.sessions.request_help(sid, "answer")
    assert help_.help.refute
    r = services.sessions.get_refutation(sid)
    assert r.fen_before == start_fen(view) and r.wrong_move == bad
    assert 1 <= len(r.line) <= 5 and r.score  # 3–5 plies unless the game ends sooner (§7.2)
    board = chess.Board(r.fen_before)
    board.push_uci(r.wrong_move)
    for uci in r.line:  # every move of the line is legal from there
        board.push_uci(uci)
    assert services.sessions.get_refutation(sid) is r  # cached
    assert FakeEngine.instances[0].calls[0][2] == 1  # one line is enough for a refutation


def test_no_refutation_without_a_wrong_move(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid, _view, moves = start(services)
    for uci in moves[1::2]:
        services.sessions.submit_move(sid, uci)
    with pytest.raises(NotFoundError):
        services.sessions.get_refutation(sid)


def test_not_installed_is_a_clear_error(services) -> None:  # type: ignore[no-untyped-def]
    sid, view, moves = start(services)
    services.sessions.submit_move(sid, wrong_move(view, moves))
    services.sessions.request_help(sid, "answer")
    with pytest.raises(EngineNotInstalled):
        services.sessions.get_refutation(sid)


def test_analysis_board_positions_are_validated(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid, view, moves = start(services)
    for uci in moves[1::2]:
        services.sessions.submit_move(sid, uci)
    for bad in ("8/8/8/8/8/8/8/8 w - - 0 1", "nonsense", None, "x" * 500):
        with pytest.raises(ValidationError):
            services.sessions.analyze(sid, bad, "board")
    with pytest.raises(ValidationError):
        services.sessions.analyze(sid, start_fen(view), "elsewhere")
    over = services.sessions.analyze(sid, "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3", "board")
    assert over.game_over and over.lines == ()  # mate: answered without the engine
    assert all(c[0] != "8/8/8/8/8/8/8/8 w - - 0 1" for e in FakeEngine.instances for c in e.calls)


def test_engine_errors_reach_the_caller_and_the_next_call_works(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.engine.analyse(chess.Board(), "white")
    FakeEngine.instances[0].fail = EngineError(
        "Stockfish stopped unexpectedly and was restarted.", code="engine_crashed"
    )
    with pytest.raises(EngineError):
        services.engine.analyse(chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1"), "white")
    FakeEngine.instances[0].fail = None
    assert services.engine.analyse(chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1"), "white").lines


def test_latest_request_wins(services, paths) -> None:  # type: ignore[no-untyped-def]
    """Stepping fast: requests queued behind a running search are dropped if a newer one arrived."""
    plant_managed_install(paths)
    services.engine.analyse(chess.Board(), "white")  # start the engine
    engine = FakeEngine.instances[0]
    engine.gate = threading.Event()
    engine.entered.clear()
    key = ("s", "panel")
    results: dict[str, object] = {}
    boards = {n: chess.Board(f) for n, f in [("a", "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"),
                                             ("b", "4k3/8/8/8/8/8/8/1R2K3 w - - 0 1"),
                                             ("c", "4k3/8/8/8/8/8/8/2R1K3 w - - 0 1")]}  # fmt: skip

    def run(name: str) -> None:
        results[name] = services.engine.analyse(boards[name], "white", key=key, gen=services.engine.ticket(key))

    ta = threading.Thread(target=run, args=("a",))
    ta.start()
    assert engine.entered.wait(5)
    tb = threading.Thread(target=run, args=("b",))
    tb.start()
    tc = threading.Thread(target=run, args=("c",))
    import time

    time.sleep(0.1)  # b is queued behind a
    tc.start()
    time.sleep(0.1)
    engine.gate.set()
    for t in (ta, tb, tc):
        t.join(5)
    assert results["b"].superseded and not results["c"].superseded  # type: ignore[attr-defined]
    assert [c[0] for c in engine.calls[1:]] == [boards["a"].fen(), boards["c"].fen()]


def test_close_stops_the_engine(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.engine.analyse(chess.Board(), "white")
    services.close()
    assert FakeEngine.instances[0].closed  # NFR-6


def test_log_banner_names_the_engine(paths, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """NFR-4: the first log line records the Stockfish version (or that it isn't installed)."""
    import logging

    from weaksquare.adapters.logging_setup import setup_logging
    from weaksquare.app import build_engine_installer
    from weaksquare.core.clock import FixedClock

    assert build_engine_installer(paths, None, FixedClock()).describe() == "not installed (sf_19 pinned)"
    plant_managed_install(paths)
    label = build_engine_installer(paths, None, FixedClock()).describe()
    assert label == "Stockfish 19 (sf_19, managed)"
    handler = setup_logging(tmp_path / "logs", "0.4.0", webview_version="1.0", stockfish=label)
    try:
        handler.flush()
        first = (tmp_path / "logs" / "weaksquare.log").read_text(encoding="utf-8").splitlines()[0]
        assert "Stockfish: Stockfish 19 (sf_19, managed)" in first
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
