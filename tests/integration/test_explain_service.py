"""Explain through the bridge (§9.2, FR-8.1–8.8): finished puzzles only, Stockfish required, the quote, the
guardrails (budget enforcement through Explain), caching by (puzzle, move path, provider, model), validation
of the answer against the real position, and readable errors. A fake engine and a fake LLM provider."""

from __future__ import annotations

import json
import shutil
from typing import Any

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FAKE_OPENAI_KEY, FakeLLMProvider
from tests.helpers import build_api
from weaksquare import config
from weaksquare.core.llm.defaults import PriceRow
from weaksquare.core.llm.provider import LLMError, LLMResponse


def ok(r: dict[str, Any]) -> Any:
    assert r.get("ok"), r
    return r["data"]


@pytest.fixture
def api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare.adapters.db.migrate import migrate

    FakeEngine.instances.clear()
    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    a = build_api(paths, clock)
    yield a
    a._runner.cancel_all()


def configure(api: Any, provider: str = "anthropic", model: str = "claude-haiku-5-5", budget: float = 5.0,
              cap: float = 0.5) -> None:  # fmt: skip
    ok(api.set_llm_key(provider, FAKE_ANTHROPIC_KEY if provider == "anthropic" else FAKE_OPENAI_KEY))
    ok(api.set_llm_settings(provider, model, "low", cap, budget))


def fake(api: Any, provider: str = "anthropic") -> FakeLLMProvider:
    return api._llm_settings._providers[provider]


def start(api: Any, mode: str = "standard") -> tuple[int, dict[str, Any], chess.Board, tuple[str, ...]]:
    sid = ok(api.start_session({"queue_size": 5}, True, mode))["session_id"]
    view = ok(api.next_puzzle(sid))
    board = chess.Board(view["fen"])
    if view.get("opponent_move"):
        board.push_uci(view["opponent_move"])
    with api._sessions._session(sid).lock:
        moves = api._sessions._session(sid).current.state.puzzle.moves
    return sid, view, board, moves


def show_answer(api: Any, sid: int) -> None:
    """The stuck ladder: Hint unlocks Show answer, which ends the puzzle (§7.2, FR-7.3)."""
    with api._sessions._session(sid).lock:
        state = api._sessions._session(sid).current.state
        hinted, finished = getattr(state, "hinted", True), state.finished
    if finished:
        return
    if not hinted:
        api.request_help(sid, "hint")  # Danger spotting before the call has no hint: Show answer goes straight
    ok(api.request_help(sid, "answer"))


def finish_with_a_wrong_move(api: Any, sid: int, board: chess.Board, moves: tuple[str, ...]) -> str:
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != moves[1] and not board.gives_check(m))
    assert ok(api.submit_move(sid, wrong))["kind"] == "wrong"
    show_answer(api, sid)  # Show answer ends it (FR-7.3)
    return wrong


def answer_for(moves: tuple[str, ...], fen: str, **over: Any) -> str:
    """A valid answer for this puzzle, built from its real solution."""
    b = chess.Board(fen)
    b.push_uci(moves[0])
    steps = []
    for i, uci in enumerate(moves[1:]):
        m = chess.Move.from_uci(uci)
        steps.append({"ply": i, "move": b.san(m), "text": f"Step {i}.", "variation": [],
                      "annotations": [{"type": "arrow", "from": uci[:2], "to": uci[2:4], "color": "green"}]})  # fmt: skip
        b.push(m)
    body = {"summary": "The idea.", "steps": steps, "key_ideas": ["fork"]} | over
    return json.dumps(body)


def run_explain(api: Any, sid: int) -> dict[str, Any]:
    job = ok(api.start_explain(sid))
    api._runner.wait(job, 10)
    return ok(api.get_job(job))


def puzzle_fen(api: Any, sid: int) -> str:
    with api._sessions._session(sid).lock:
        return api._sessions._session(sid).current.state.puzzle.fen


# ---- gates -------------------------------------------------------------------------------------------


def test_only_after_the_puzzle_is_over(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, _board, _moves = start(api)
    assert api.get_explain_quote(sid)["error"]["code"] == "conflict"  # FR-7.3: not while solving
    assert api.start_explain(sid)["error"]["code"] == "conflict"
    assert fake(api).requests == []


def test_requires_stockfish(api) -> None:  # type: ignore[no-untyped-def]
    configure(api)
    sid, _view, _board, _moves = start(api)
    show_answer(api, sid)
    r = api.get_explain_quote(sid)
    assert r["error"]["code"] == "engine_not_installed"  # Adam, v0.7 planning
    assert api.start_explain(sid)["error"]["code"] == "engine_not_installed"


def test_quote_states(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    sid, _view, _board, _moves = start(api)
    show_answer(api, sid)
    assert ok(api.get_explain_quote(sid))["state"] == "not_configured"
    ok(api.set_llm_key("anthropic", FAKE_ANTHROPIC_KEY))
    ok(api.set_llm_settings("anthropic", "", "low", 0.5, 5.0))
    assert ok(api.get_explain_quote(sid))["state"] == "no_model"  # nothing pre-selected
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 5.0))
    q = ok(api.get_explain_quote(sid))
    assert q["state"] == "ok" and 0 < q["typical_usd"] < q["worst_usd"] < 0.01
    assert FakeEngine.instances == [] or all(not e.calls for e in FakeEngine.instances)  # the quote asks no engine


# ---- a run ---------------------------------------------------------------------------------------------


def test_explain_after_a_wrong_move(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, board, moves = start(api)
    wrong = finish_with_a_wrong_move(api, sid, board, moves)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    job = run_explain(api, sid)
    assert job["state"] == "done", job
    x = ok(api.get_explanation(sid))
    assert x["summary"] == "The idea." and x["discarded"] == 0 and not x["cached"]
    assert [s["uci"] for s in x["steps"]] == list(moves[1:])
    assert x["model"] == "claude-haiku-5-5" and x["cost_usd"] > 0
    req = fake(api).requests[0]
    assert req.max_tokens == 1500 and req.schema["required"] == ["summary", "steps", "key_ideas"]
    assert "Stockfish's refutation" in req.user and "Stockfish's top lines" in req.user  # grounded (FR-8.2)
    assert chess.Board(puzzle_fen(api, sid)).san(chess.Move.from_uci(moves[0])) in req.user
    with api._sessions._session(sid).lock:
        pid = api._sessions._session(sid).current.state.puzzle.ref.id
    assert pid not in req.user and pid not in req.system  # SR-11: no puzzle ID
    assert wrong  # the refutation is of this move
    with api._sessions._session(sid).lock:
        attempt = api._sessions._session(sid).current.state.attempt
    assert attempt.win is False and attempt.help_used == "none"  # decided by the wrong move; Explain changes nothing


def test_invalid_annotations_are_dropped_and_reported(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, _board, moves = start(api)
    show_answer(api, sid)
    text = json.loads(answer_for(moves, puzzle_fen(api, sid)))
    text["steps"][0]["annotations"].append({"type": "arrow", "from": "j9", "to": "a1", "color": "green"})
    text["steps"][0]["variation"] = ["Kxz9"]
    text["steps"].append({"ply": 40, "move": "Qh7#", "text": "invented", "annotations": [], "variation": []})
    fake(api).queue(json.dumps(text))
    assert run_explain(api, sid)["state"] == "done"
    x = ok(api.get_explanation(sid))
    assert x["discarded"] == 3 and all(s["text"] != "invented" for s in x["steps"])
    assert all(a["orig"] != "j9" for s in x["steps"] for a in s["annotations"])


def test_cache_hit_is_free_and_keyed_by_provider_and_model(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, _board, moves = start(api)
    show_answer(api, sid)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    run_explain(api, sid)
    assert ok(api.get_explain_quote(sid))["state"] == "cached"
    assert run_explain(api, sid)["state"] == "done"
    x = ok(api.get_explanation(sid))
    assert x["cached"] and x["cost_usd"] == 0
    assert len(fake(api).requests) == 1 and api._llm_usage._usage.count() == 1  # no second request or log row
    # another model: a miss, and its own entry (Adam's manual test compares two models)
    ok(api.set_llm_settings("anthropic", "claude-sonnet-5-5", "low", 0.5, 5.0))
    assert ok(api.get_explain_quote(sid))["state"] == "ok"
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid), summary="Sonnet's idea."))
    run_explain(api, sid)
    assert ok(api.get_explanation(sid))["summary"] == "Sonnet's idea." and len(fake(api).requests) == 2
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 5.0))
    assert ok(api.get_explain_quote(sid))["state"] == "cached"


def test_cache_key_includes_your_moves(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, _board, _moves = start(api)
    show_answer(api, sid)
    _inp, clean = api._sessions.explain_facts(sid, with_engine=False)
    sid2, _v, board2, moves2 = start(api)
    finish_with_a_wrong_move(api, sid2, board2, moves2)
    _inp2, wrong = api._sessions.explain_facts(sid2, with_engine=False)
    assert clean.path == ("standard",) and wrong.path[:2] == ("standard", "wrong")


def test_budget_enforcement_through_explain(api) -> None:  # type: ignore[no-untyped-def]
    """ROADMAP v0.7 *Done when*: blocked when over; a cached result still shows; raising the budget unblocks."""
    plant_managed_install(api._paths)
    api._llm_settings.save_price("anthropic", "test-dear", 10.0, 10.0)
    configure(api, model="test-dear", budget=0.05, cap=5.0)
    f = fake(api)
    f.input_tokens, f.output_tokens = 2_500, 2_500  # $0.05 at $10/M each way: the whole budget in one go
    sid, _view, _board, moves = start(api)
    show_answer(api, sid)
    f.queue(answer_for(moves, puzzle_fen(api, sid)))
    assert run_explain(api, sid)["state"] == "done"
    spend = ok(api.get_llm_spend())
    assert spend["level"] == "over" and spend["spent_usd"] == pytest.approx(0.05)
    assert ok(api.get_explain_quote(sid))["state"] == "cached"  # the same puzzle: free, still shown
    sid2, _v, _b, moves2 = start(api)
    show_answer(api, sid2)
    q = ok(api.get_explain_quote(sid2))
    assert q["state"] == "over_budget" and "this month's AI budget" in q["message"]
    r = api.start_explain(sid2)
    assert r["error"]["code"] == "over_budget"
    assert len(f.requests) == 1
    ok(api.set_llm_settings("anthropic", "test-dear", "low", 5.0, 1.0))  # raise it
    f.queue(answer_for(moves2, puzzle_fen(api, sid2)))
    assert run_explain(api, sid2)["state"] == "done" and len(f.requests) == 2


def test_cap_enforcement_through_explain(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    api._llm_settings.save_price("anthropic", "test-dear", 10.0, 10.0)
    configure(api, model="test-dear", cap=0.01)  # 1,500 output tokens alone are $0.015
    sid, _view, _board, _moves = start(api)
    show_answer(api, sid)
    q = ok(api.get_explain_quote(sid))
    assert q["state"] == "over_cap" and q["worst_usd"] > 0.01
    assert api.start_explain(sid)["error"]["code"] == "over_cap" and fake(api).requests == []


def test_danger_spotting_explains_the_candidate(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, view, _board, moves = start(api, "danger_spotting")
    assert view["candidate"]
    ok(api.call_danger(sid, "safe"))
    with api._sessions._session(sid).lock:
        finished = api._sessions._session(sid).current.state.finished
    if not finished:
        show_answer(api, sid)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    assert run_explain(api, sid)["state"] == "done"
    user = fake(api).requests[0].user
    assert "Danger spotting" in user and "The player's call: safe" in user


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (LLMResponse('{"summary": "cut', 900, 1500, "truncated"), "llm_truncated"),
        (LLMResponse("", 900, 2, "refused"), "llm_refused"),
        (LLMResponse("not json at all", 900, 50), "llm_bad_answer"),
        (LLMError("bad_key", 401), "llm_bad_key"),
        (LLMError("quota", 429), "llm_quota"),
        (LLMError("timeout"), "llm_timeout"),
    ],
)
def test_failures_are_readable_and_cache_nothing(api, item: Any, code: str) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, _board, _moves = start(api)
    show_answer(api, sid)
    fake(api).queue(item)
    job = run_explain(api, sid)
    assert job["state"] == "failed" and job["error_code"] == code
    assert FAKE_ANTHROPIC_KEY not in json.dumps(job)
    assert ok(api.get_explanation(sid)) is None
    assert ok(api.get_explain_quote(sid))["state"] == "ok"  # not cached: you can try again


def test_a_result_doesnt_follow_you_to_the_next_puzzle(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api)
    sid, _view, _board, moves = start(api)
    show_answer(api, sid)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    run_explain(api, sid)
    assert ok(api.get_explanation(sid)) is not None
    ok(api.next_puzzle(sid))
    assert ok(api.get_explanation(sid)) is None


def test_openai_provider_works_the_same(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api, provider="openai", model="gpt-5.4-nano")
    sid, _view, _board, moves = start(api)
    show_answer(api, sid)
    fake(api, "openai").queue(answer_for(moves, puzzle_fen(api, sid)))
    assert run_explain(api, sid)["state"] == "done"
    assert ok(api.get_explanation(sid))["provider"] == "openai"
    assert fake(api).requests == []  # never the other provider


def test_price_row_needed_even_with_a_key(api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(api._paths)
    configure(api, model="claude-unpriced")
    sid, _view, _board, _moves = start(api)
    show_answer(api, sid)
    assert ok(api.get_explain_quote(sid))["state"] == "no_price"
    api._llm_settings._prices.upsert(PriceRow("anthropic", "claude-unpriced", 1.0, 1.0))
    assert ok(api.get_explain_quote(sid))["state"] == "ok"
