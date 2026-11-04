"""QA v0.7 with the real Stockfish 19 (`uv run pytest -m engine`): Explain's grounded facts (FR-8.2) built
from real engine output, in Standard (after a wrong move and after Show answer) and Danger spotting. Every
SAN in the prompt must replay legally, the engine lines and refutation must be present, and the prompt
must carry no puzzle ID or rating (SR-11). No LLM is called: the facts are built and checked only."""

from __future__ import annotations

import re

import chess
import pytest

from tests.helpers import fake_service_kwargs
from weaksquare.adapters.stockfish import StockfishEngine
from weaksquare.core.explain import build_prompt
from weaksquare.core.filters import FilterSpec

pytestmark = pytest.mark.engine

PUZZLES = 6


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
    s.engine._settings.set("engine.custom_path", stockfish_path)
    s.engine._settings.set("engine.custom_name", "Stockfish 19")
    s.engine._settings.set("engine.think_s", 0.3)
    yield s
    s.close()


def _engine_lines_are_legal(prompt: str, start_fen: str) -> int:
    """Each '- <score>: SAN SAN …' engine line replays from the position before your first move."""
    n = 0
    for line in prompt.splitlines():
        m = re.match(r"- (.+?): (.+)$", line)
        if not m or m.group(2) == "(none)":
            continue
        b = chess.Board(start_fen)
        for san in m.group(2).split():
            b.push_san(san)  # raises if illegal
        n += 1
    return n


def _puzzle(s, sid):  # type: ignore[no-untyped-def]
    with s.sessions._session(sid).lock:
        return s.sessions._session(sid).current.state.puzzle


def test_qa_real_engine_facts_standard(real_services) -> None:  # type: ignore[no-untyped-def]
    s = real_services
    sid = s.sessions.start(FilterSpec(queue_size=PUZZLES)).session_id
    checked = 0
    for i in range(PUZZLES):
        view = s.sessions.next_puzzle(sid)
        if view is None:
            break
        p = _puzzle(s, sid)
        board = chess.Board(p.fen)
        board.push_uci(p.moves[0])
        start_fen = board.fen()
        if i % 2 == 0:  # a wrong move, then Show answer
            wrong = next(m.uci() for m in board.legal_moves if m.uci() != p.moves[1] and not board.gives_check(m))
            s.sessions.submit_move(sid, wrong)
        s.sessions.request_help(sid, "hint")
        s.sessions.request_help(sid, "answer")
        inp, parts = s.sessions.explain_facts(sid)
        prompt = build_prompt(inp)
        assert inp.engine_lines, "no Stockfish lines in the facts"
        assert _engine_lines_are_legal(prompt, start_fen) >= 1
        if i % 2 == 0:
            assert inp.refutation is not None and "Stockfish's refutation" in prompt
            assert parts.path[:2] == ("standard", "wrong")
        assert p.ref.id not in prompt and str(p.rating) not in prompt.split("FEN")[0]
        checked += 1
    assert checked >= 4


def test_qa_real_engine_facts_danger_spotting(real_services) -> None:  # type: ignore[no-untyped-def]
    s = real_services
    sid = s.sessions.start(FilterSpec(queue_size=4), True, "danger_spotting").session_id
    checked = 0
    for _ in range(4):
        view = s.sessions.next_puzzle(sid)
        if view is None:
            break
        s.sessions.call_danger(sid, "unsafe")
        with s.sessions._session(sid).lock:
            finished = s.sessions._session(sid).current.state.finished
        if not finished:  # a correct Unsafe: the refutation is still to be found (Hint unlocks Show answer)
            s.sessions.request_help(sid, "hint")
            s.sessions.request_help(sid, "answer")
        inp, parts = s.sessions.explain_facts(sid)
        prompt = build_prompt(inp)
        assert inp.danger is not None and "Mode: Danger spotting" in prompt
        assert parts.path[:3] == ("danger_spotting", "call", "unsafe")
        p = _puzzle(s, sid)
        board = chess.Board(p.fen)
        board.push_uci(p.moves[0])
        assert _engine_lines_are_legal(prompt, board.fen()) >= 1
        checked += 1
    assert checked >= 2
