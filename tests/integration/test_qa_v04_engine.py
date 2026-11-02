"""QA v0.4 (independent): FR-7.3 over the bridge at every step, argument checks, game-over positions,
the custom-engine probe against real non-engine programs, and shutdown during a search (NFR-6)."""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api

FAKE_UCI = Path(__file__).resolve().parents[1] / "fakes" / "uci_engine.py"


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    return build_api(paths, clock)


def _moves(api, sid):  # type: ignore[no-untyped-def]
    s = api._sessions._session(sid)
    with s.lock:
        return list(s.current.state.puzzle.moves)


def _long_puzzle(api):  # type: ignore[no-untyped-def]
    """A session whose current puzzle has at least two moves for the solver (4+ plies)."""
    sid = api.start_session({"queue_size": 50})["data"]["session_id"]
    for _ in range(50):
        view = api.next_puzzle(sid)["data"]
        if len(_moves(api, sid)) >= 4:
            board = chess.Board(view["fen"])
            board.push_uci(view["opponent_move"])
            return sid, view, board
    pytest.fail("no 4-ply puzzle in the fixture queue")


def _refused(r: dict) -> bool:
    return (not r["ok"]) and r["error"]["code"] == "conflict"


def _all_refused(api, sid, fens: list[str]) -> None:  # type: ignore[no-untyped-def]
    for fen in fens:
        for purpose in ("start", "panel", "board"):
            r = api.analyze_position(sid, fen, purpose)
            assert _refused(r), (fen, purpose, r)
    assert _refused(api.get_refutation(sid))


def test_qa_bridge_refuses_engine_output_at_every_step_until_the_end(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    """FR-7.3 probed over the bridge: start, after a correct move, after a wrong move (decided, still
    playing), after a hint; allowed only at the end; refused again on the next puzzle (no cache leak)."""
    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, _view, board = _long_puzzle(api)
    moves = _moves(api, sid)
    start = board.fen()
    _all_refused(api, sid, [start, chess.STARTING_FEN])

    fb = api.submit_move(sid, moves[1])["data"]
    assert fb["kind"] == "correct"
    after_correct = board.copy()
    after_correct.push_uci(moves[1])
    after_correct.push_uci(moves[2])
    _all_refused(api, sid, [start, after_correct.fen()])

    wrong = next(
        m.uci()
        for m in after_correct.legal_moves
        if m.uci() != moves[3] and not after_correct.gives_check(m) and not after_correct.is_capture(m)
    )
    assert api.submit_move(sid, wrong)["data"]["kind"] == "wrong"  # lost, still in progress
    _all_refused(api, sid, [start, after_correct.fen()])
    if len(moves) > 4:
        api.request_help(sid, "hint")
        _all_refused(api, sid, [start])
    assert FakeEngine.instances == []  # nothing even started the engine

    # finish the line by playing the rest of the solution
    for uci in moves[3::2]:
        api.submit_move(sid, uci)
    ok = api.analyze_position(sid, start, "start")
    assert ok["ok"] and ok["data"]["lines"], ok
    ref = api.get_refutation(sid)
    assert ref["ok"] and ref["data"]["wrong_move"] == wrong

    # the next puzzle is in progress again: the same FEN (cached for the last puzzle) is refused
    api.next_puzzle(sid)
    _all_refused(api, sid, [start])


def test_qa_game_over_positions_never_reach_the_engine(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    """Analysis board on mate / stalemate / dead positions: answered without the engine (FR-7.6)."""
    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, _view, _board = _long_puzzle(api)
    api.request_help(sid, "hint")
    api.request_help(sid, "answer")  # finished
    cases = {
        "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1": None,  # normal: goes to the engine
        "R5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 1 1": "Checkmate",
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1": "Stalemate",
        "8/8/4k3/8/8/3K4/8/8 w - - 0 1": "insufficient material",
    }
    for fen, expect in cases.items():
        r = api.analyze_position(sid, fen, "board")
        assert r["ok"], r
        if expect is None:
            assert r["data"]["lines"] and r["data"]["game_over"] is None
        else:
            assert r["data"]["lines"] == [] and expect in r["data"]["game_over"], r
    analysed = [c[0] for e in FakeEngine.instances for c in e.calls]
    assert len(analysed) == 1, analysed  # only the normal position


@pytest.mark.parametrize(
    "call",
    [
        ("set_engine_settings", {"think_s": True}),
        ("set_engine_settings", {"think_s": math.nan}),
        ("set_engine_settings", {"think_s": math.inf}),
        ("set_engine_settings", {"think_s": 0.19}),
        ("set_engine_settings", {"think_s": 10.01}),
        ("set_engine_settings", {"threads": -1}),
        ("set_engine_settings", {"threads": 9}),  # cpu_count is 8 in tests
        ("set_engine_settings", {"hash_mb": 15}),
        ("set_engine_settings", {"hash_mb": 2049}),
        ("set_engine_settings", {"hash_mb": 256.5}),
        ("start_custom_engine_check", {"path": 5}),
        ("start_custom_engine_check", {"path": ""}),
        ("start_custom_engine_check", {"path": "C:\\x\\notes.txt"}),
        ("start_custom_engine_check", {"path": "x" * 2000 + ".exe"}),
        ("start_engine_install", {"force": "yes"}),
    ],
    ids=lambda c: f"{c[0]}-{sorted(c[1].items())!r}"[:60],
)
def test_qa_bridge_rejects_bad_engine_settings(paths, clock, fixture_puzzles_db, call) -> None:  # type: ignore[no-untyped-def]
    api = _api(paths, clock, fixture_puzzles_db)
    before = api.get_engine_settings()["data"]
    name, kwargs = call
    r = getattr(api, name)(**kwargs)
    assert not r["ok"] and r["error"]["code"] == "invalid_argument", r
    assert api.get_engine_settings()["data"] == before


def test_qa_engine_settings_bounds_are_accepted_and_persist(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    api = _api(paths, clock, fixture_puzzles_db)
    for kwargs in ({"think_s": 0.2}, {"think_s": 10}, {"threads": 1}, {"threads": 8}, {"hash_mb": 16},
                   {"hash_mb": 2048}):  # fmt: skip
        r = api.set_engine_settings(**kwargs)
        assert r["ok"], (kwargs, r)
        ((key, value),) = kwargs.items()
        assert r["data"][key] == value
    again = build_api(paths, clock).get_engine_settings()["data"]  # a fresh Api on the same user.db
    assert (again["think_s"], again["threads"], again["hash_mb"]) == (10, 8, 2048)


@pytest.mark.parametrize(
    "fen",
    [
        5,
        "",
        "x" * 200,
        "not a fen",
        "4k3/8/8/8/8/8/8/4K2K w - - 0 1",  # two white kings
        "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1",  # black (not to move) is in check
        "4k3/8/8/8/8/8/8/4K3 w KQkq - 0 1",  # castling rights without rooks
        "4k3/8/8/8/8/8/8/4K3 w - e3 0 1",  # impossible en passant square
        "P3k3/8/8/8/8/8/8/4K3 w - - 0 1",  # pawn on the back rank
    ],
)
def test_qa_bad_positions_are_refused_before_the_engine(paths, clock, fixture_puzzles_db, fen) -> None:  # type: ignore[no-untyped-def]
    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, _view, _board = _long_puzzle(api)
    api.request_help(sid, "hint")
    api.request_help(sid, "answer")
    r = api.analyze_position(sid, fen, "board")
    assert not r["ok"] and r["error"]["code"] == "invalid_argument", r
    assert all(not e.calls for e in FakeEngine.instances)


# ---- the custom-engine probe against programs that aren't engines (real processes) ----------------


def _count(image: str) -> int:
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"], capture_output=True, text=True, check=False
    ).stdout
    return sum(1 for line in out.splitlines() if line.lower().startswith(image.lower()))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows programs")
def test_qa_probe_refuses_a_program_that_waits_on_stdin_and_kills_it() -> None:
    """A real .exe that reads stdin forever (sort.exe) as the custom engine: refused within the bound,
    and the process doesn't linger."""
    from weaksquare.adapters.stockfish import probe_engine
    from weaksquare.core.engine import EngineError

    exe = r"C:\Windows\System32\sort.exe"
    before = _count("sort.exe")
    started = time.monotonic()
    with pytest.raises(EngineError):
        probe_engine(exe)
    assert time.monotonic() - started < 20
    deadline = time.monotonic() + 5
    while _count("sort.exe") > before and time.monotonic() < deadline:
        time.sleep(0.2)
    assert _count("sort.exe") <= before


@pytest.mark.skipif(sys.platform != "win32", reason="Windows programs")
def test_qa_probe_refuses_a_file_that_is_not_a_program(tmp_path: Path) -> None:
    from weaksquare.adapters.stockfish import probe_engine
    from weaksquare.core.engine import EngineError

    fake = tmp_path / "engine.exe"
    fake.write_bytes(b"this is a text file, not a PE executable\n" * 10)
    started = time.monotonic()
    with pytest.raises(EngineError):
        probe_engine(str(fake))
    assert time.monotonic() - started < 5


# ---- NFR-6: closing while a search runs / after a timeout --------------------------------------------
# These run in a child Python: python-chess's engine thread isn't a daemon, so a stuck one would hang
# pytest at exit (which is exactly v0.4-B1).

_CHILD = r"""
import sys, threading, time
import chess
sys.path.insert(0, {src!r})
import weaksquare.adapters.stockfish as sf
from weaksquare.core.engine import EngineError
sf.TIMEOUT_S = {timeout_s}
engine = sf.StockfishEngine([sys.executable, {fake!r}, {mode!r}])
errors = []
def search():
    try:
        engine.analyse(chess.Board(), 0.3, 1)
    except EngineError as e:
        errors.append(e.code)
t = threading.Thread(target=search)
t.start()
if {wait_for_start}:  # close only once the process is up (round 2: the start-up itself was B8)
    deadline = time.monotonic() + 20
    while engine._engine is None and time.monotonic() < deadline:
        time.sleep(0.02)
time.sleep({wait})
started = time.monotonic()
engine.close()
t.join(10)
print("CLOSE_S", round(time.monotonic() - started, 2), "ERRORS", errors, "LEFT", engine._engine is None, flush=True)
"""


def _run_child(
    wait: float, *, mode: str = "hang", timeout_s: float = 1.0, wait_for_start: bool = True
) -> tuple[str, bool]:
    """(stdout, exited): the child's output, and whether the process exited within 30 s."""
    src = str(Path(__file__).resolve().parents[2] / "src")
    code = _CHILD.format(
        src=src, fake=str(FAKE_UCI), wait=wait, mode=mode, timeout_s=timeout_s, wait_for_start=wait_for_start
    )
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        return r.stdout, r.returncode == 0
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return out, False


def test_qa_close_during_a_hung_search_returns_within_the_bound() -> None:
    """close() while a search hangs: it returns promptly, the search fails quietly with engine_stopped
    (v0.4-B5: close kills a busy engine instead of waiting), and nothing is left in the adapter."""
    out, _exited = _run_child(wait=0.5)  # whether the process can then exit is B1 (next test)
    line = next((x for x in out.splitlines() if x.startswith("CLOSE_S")), "")
    assert line, out
    took = float(line.split()[1])
    assert took < 1.0, line
    assert "['engine_stopped']" in line and line.endswith("LEFT True")


def test_qa_process_exits_after_an_engine_timeout() -> None:
    """NFR-6: after an engine timeout and close(), the Python process must still be able to exit.
    Regression for v0.4-B1 (python-chess left its engine thread waiting on an unresolved future)."""
    out, exited = _run_child(wait=0.5)
    assert "CLOSE_S" in out
    assert exited, "the process didn't exit within 30 s of close()"


# ---- §7.2 step 2: the refutation is 3-5 plies ------------------------------------------------------


def test_qa_refutation_is_at_least_3_plies_when_the_game_goes_on(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    """Stockfish sometimes returns a 2-ply pv (seen with the real sf_19 at 1 s: RDPB7 e8f7 -> c2b3 b7b6).
    §7.2 asks for a 3-5 ply reply line unless the game ends sooner."""
    from weaksquare.core.engine import EngineLine

    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, _view, board = _long_puzzle(api)
    moves = _moves(api, sid)
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != moves[1] and not board.gives_check(m))
    api.submit_move(sid, wrong)
    api.request_help(sid, "answer")

    real = FakeEngine.analyse

    def short_pv(self, b, think_s, multipv):  # type: ignore[no-untyped-def]
        return [EngineLine(x.cp, x.mate, x.pv[:2]) for x in real(self, b, think_s, multipv)]

    FakeEngine.analyse = short_pv  # type: ignore[method-assign]
    try:
        r = api.get_refutation(sid)["data"]
    finally:
        FakeEngine.analyse = real  # type: ignore[method-assign]
    after = chess.Board(r["fen_before"])
    after.push_uci(r["wrong_move"])
    for uci in r["line"]:
        after.push_uci(uci)
    assert len(r["line"]) >= 3 or after.is_game_over(), r["line"]


def test_qa_process_exits_when_closed_while_the_engine_starts() -> None:
    """NFR-6: the window closes while the first search is still starting the engine (~0.35 s for sf_19).
    close() must leave nothing running, and the process must exit. Regression for v0.4-B8."""
    out, exited = _run_child(wait=0.0, mode="normal", timeout_s=10.0, wait_for_start=False)
    assert "CLOSE_S" in out, out
    assert out.strip().endswith("LEFT True"), out  # nothing assigned after close()
    assert exited, "the process didn't exit within 30 s of close()"
