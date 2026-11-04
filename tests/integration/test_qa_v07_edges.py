"""QA v0.7 (independent, qa/QA-v0.7.md): edge cases for LLM Explain and the cost guardrails beyond the
builder's tests. Fake engine and fake LLM provider only; never the network, never Credential Manager
(MemorySecretStore). The tests that pinned B1-B3 as expected failures are regression tests now that they're fixed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import chess
import httpx
import pytest

from tests.fakes.engine import plant_managed_install
from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FAKE_OPENAI_KEY
from tests.integration.test_explain_service import (
    answer_for,
    api,  # noqa: F401  (fixture)
    configure,
    fake,
    ok,
    puzzle_fen,
    run_explain,
    show_answer,
    start,
)
from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.llm.anthropic import AnthropicProvider
from weaksquare.adapters.llm.openai import OpenAIProvider
from weaksquare.core.explain import ExplainInput, validate
from weaksquare.core.llm import guardrails
from weaksquare.core.llm.provider import LLMError, LLMRequest, LLMResponse

FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"


# ---- validation (FR-8.4): a "variation" must be legal move by move ----------------------------------


def _one_ply_input() -> ExplainInput:
    # Opponent (White) plays Bc4; you (Black) reply Nf6.
    return ExplainInput(FEN, ("f1c4", "g8f6"), ("Opening",))


# Regression test for v0.7-B1 (fixed).
@pytest.mark.parametrize("null", ["--", "Z0", "0000", "@@@@"])
def test_qa_null_move_in_a_variation_is_dropped(null: str) -> None:
    """python-chess's parse_san accepts null moves ('--', 'Z0', '0000') without a legality check. A
    variation must be legal in sequence (FR-8.4), so a null move must drop it."""
    answer = {
        "summary": "s",
        "steps": [
            {"ply": 0, "move": "Nf6", "text": "t", "annotations": [], "variation": [null, "Nxe4"]}
        ],  # White "passes", Black moves twice
        "key_ideas": [],
    }
    x = validate(_one_ply_input(), json.dumps(answer))
    assert x is not None
    assert x.steps[0].variation == (), f"null move kept: {x.steps[0].variation}"
    assert x.discarded == 1


def test_qa_annotation_edge_squares_and_case() -> None:
    answer = {
        "summary": "s",
        "steps": [{"ply": 0, "move": "g8f6", "text": "t", "variation": [], "annotations": [
            {"type": "arrow", "from": "a1", "to": "h8", "color": "blue"},  # kept: corners
            {"type": "arrow", "from": "E2", "to": "e4", "color": "green"},  # upper case: dropped
            {"type": "arrow", "from": "e2", "to": "e2", "color": "green"},  # zero-length arrow: dropped
            {"type": "circle", "from": "d5", "to": None, "color": "yellow"},  # kept
            {"type": "circle", "from": "d5 ", "to": None, "color": "yellow"},  # padded: dropped
            {"type": "arrow", "from": "e2", "to": "e4", "color": "purple"},  # unknown color: dropped
            {"type": "line", "from": "e2", "to": "e4", "color": "green"},  # unknown type: dropped
        ]}],
        "key_ideas": ["fork", "<b>x</b>"],
    }  # fmt: skip
    x = validate(_one_ply_input(), json.dumps(answer))
    assert x is not None
    assert [(a.kind, a.orig, a.dest) for a in x.steps[0].annotations] == [("arrow", "a1", "h8"), ("circle", "d5", None)]
    assert x.discarded == 5
    assert "<b>x</b>" in x.key_ideas  # kept as text; the UI escapes it (FR-8.7)


def test_qa_huge_and_nested_junk_is_tolerated() -> None:
    answer = {"summary": "s" * 50_000, "steps": [{"ply": 0, "move": {"x": 1}}, 7, None], "key_ideas": [[1], 2]}
    x = validate(_one_ply_input(), json.dumps(answer))
    assert x is not None and len(x.summary) == 1200 and x.steps == () and x.key_ideas == () and x.discarded == 3
    assert validate(_one_ply_input(), "[]") is None
    assert validate(_one_ply_input(), json.dumps({"summary": "   "})) is None


# ---- guardrails: float edges -----------------------------------------------------------------------


def test_qa_worst_case_exactly_at_the_cap_is_allowed() -> None:
    """FR-8.12: blocked only when *above* the cap."""
    assert guardrails.check(0.5, 0.5, 0.0, 5.0) == "ok"
    assert guardrails.check(0.1 + 0.2, 0.3, 0.0, 5.0) == "ok"  # 0.30000000000000004
    assert guardrails.check(0.5000001, 0.5, 0.0, 5.0) == "over_cap"


def test_qa_budget_a_hair_under_100_percent_still_runs() -> None:
    assert guardrails.check(0.001, 0.5, 4.9999, 5.0) == "ok"
    assert guardrails.check(0.001, 0.5, 0.1 + 0.2 + 4.7, 5.0) == "over_budget"  # float sum == 5.0
    assert guardrails.spend_level(0.7999, 1.0) == "ok" and guardrails.spend_level(0.8, 1.0) == "warn"


def test_qa_cap_and_budget_fields_refuse_bad_values(api: Any) -> None:  # noqa: F811
    for cap in (-0.01, 1000.01, float("nan"), float("inf"), "0.5", True, None):
        assert api.set_llm_settings("anthropic", "", "low", cap, 5.0)["error"]["code"] == "invalid_argument", cap
    for reasoning in ("off", "LOW", "", None):
        assert api.set_llm_settings("anthropic", "", reasoning, 0.5, 5.0)["error"]["code"] == "invalid_argument"
    assert api.set_llm_settings("google", "", "low", 0.5, 5.0)["error"]["code"] == "invalid_argument"


# ---- model IDs and keys ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["../../v1/messages", "a b", "<script>", "x" * 101, "-lead", "é-model", "a\nb"])
def test_qa_odd_model_ids_are_refused(api: Any, model: str) -> None:  # noqa: F811
    assert api.set_llm_settings("anthropic", model, "low", 0.5, 5.0)["error"]["code"] == "invalid_argument"
    assert api.save_llm_price("anthropic", model, 1.0, 1.0)["error"]["code"] == "invalid_argument"


def test_qa_model_ids_with_slash_are_url_encoded_in_test_key() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={"id": "m"})

    http = HttpClient(transport=httpx.MockTransport(handler))
    AnthropicProvider(http).test_key(FAKE_ANTHROPIC_KEY, "org/model:v1@x")
    OpenAIProvider(http).test_key(FAKE_OPENAI_KEY, "ft:org/x")
    assert seen[0].endswith("/v1/models/org%2Fmodel%3Av1%40x") and seen[1].endswith("/v1/models/ft%3Aorg%2Fx")


# Regression test for v0.7-B2 (fixed).
def test_qa_an_anthropic_key_is_refused_as_an_openai_key(api: Any) -> None:  # noqa: F811
    """The shape check exists 'so a key pasted into the wrong provider is caught before it's stored'
    (services/llm_settings.py). Anthropic keys start with sk-ant-, which also starts with OpenAI's sk-."""
    r = api.set_llm_key("openai", FAKE_ANTHROPIC_KEY)
    assert not r["ok"], "an sk-ant- key was stored as the OpenAI key"


def test_qa_wrong_provider_key_errors_never_echo_the_key(api: Any) -> None:  # noqa: F811
    r = api.set_llm_key("anthropic", FAKE_OPENAI_KEY)
    assert r["error"]["code"] == "invalid_argument" and FAKE_OPENAI_KEY not in json.dumps(r)


# ---- price table validation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("anthropic", "m", -1, 1),
        ("anthropic", "m", 1, 1001),
        ("anthropic", "m", float("nan"), 1),
        ("anthropic", "m", "1", 1),
        ("anthropic", "m", True, 1),
        ("anthropic", "", 1, 1),
        ("openai2", "m", 1, 1),
        ("anthropic", "m", 1, 1, 0, 1, 1),
        ("anthropic", "m", 1, 1, 1000, 1, None),
        ("anthropic", "m", 1, 1, 1.5, 1, 1),
        ("anthropic", "m", 1, 1, None, None, None, "03/11/2026"),
    ],
)
def test_qa_price_rows_are_validated(api: Any, args: tuple[Any, ...]) -> None:  # noqa: F811
    assert api.save_llm_price(*args)["error"]["code"] == "invalid_argument"


# Regression test for v0.7-B3 (fixed).
def test_qa_impossible_as_of_date_is_refused(api: Any) -> None:  # noqa: F811
    assert (
        api.save_llm_price("anthropic", "m", 1, 1, None, None, None, "2026-13-45")["error"]["code"]
        == "invalid_argument"
    )


def test_qa_delete_unknown_price_row_is_not_found(api: Any) -> None:  # noqa: F811
    assert api.delete_llm_price("anthropic", "nope")["error"]["code"] == "not_found"


# ---- Explain end to end: modes, gates, cache, races --------------------------------------------------


def test_qa_cache_hit_runs_while_over_budget_and_makes_no_request(api: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api)
    sid, _v, _b, moves = start(api)
    show_answer(api, sid)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    assert run_explain(api, sid)["state"] == "done"
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 0.0))  # budget $0: everything else blocked
    assert ok(api.get_llm_spend())["level"] == "over"
    assert ok(api.get_explain_quote(sid))["state"] == "cached"
    assert run_explain(api, sid)["state"] == "done"
    x = ok(api.get_explanation(sid))
    assert x["cached"] and x["cost_usd"] == 0 and len(fake(api).requests) == 1


def test_qa_cap_zero_blocks_and_budget_zero_blocks(api: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api, cap=0.0)
    sid, _v, _b, _m = start(api)
    show_answer(api, sid)
    assert ok(api.get_explain_quote(sid))["state"] == "over_cap"
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 0.0))
    assert ok(api.get_explain_quote(sid))["state"] == "over_budget"
    assert fake(api).requests == []


def test_qa_bad_answer_is_logged_but_not_cached(api: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api)
    sid, _v, _b, _m = start(api)
    show_answer(api, sid)
    fake(api).queue(LLMResponse("not json", 900, 40))
    fake(api).queue(LLMResponse('{"summ', 900, 1500, "truncated"))
    assert run_explain(api, sid)["error_code"] == "llm_bad_answer"
    assert run_explain(api, sid)["error_code"] == "llm_truncated"
    with api._llm_usage._usage._db.session() as conn:  # type: ignore[attr-defined]
        assert [r[0] for r in conn.execute("SELECT status FROM llm_usage ORDER BY id")] == ["ok", "truncated"]
        assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
    assert ok(api.get_llm_spend())["spent_usd"] > 0  # billed answers count towards the budget


def test_qa_rapid_double_start_sends_one_request(api: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api)
    sid, _v, _b, moves = start(api)
    show_answer(api, sid)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    jobs = {ok(api.start_explain(sid)) for _ in range(5)}
    for j in jobs:
        api._runner.wait(j, 10)
    assert len(fake(api).requests) <= 2  # a finished job may start a second, cached one; never 5 requests
    assert api._llm_usage._usage.count() == 1


def test_qa_explain_in_a_practice_run(api: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api)
    sid, _v, _board, moves = start(api)
    show_answer(api, sid)
    api.retry_puzzle(sid)  # FR-5.12: a practice run of the same puzzle
    assert api.start_explain(sid)["error"]["code"] == "conflict"  # not before the practice run is over
    for i, uci in enumerate(moves[1:]):
        if i % 2 == 0:
            ok(api.submit_move(sid, uci))
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    assert run_explain(api, sid)["state"] == "done"
    assert "The player solved it." in fake(api).requests[0].user
    with api._sessions._session(sid).lock:
        attempt = api._sessions._session(sid).current.state.attempt
    assert attempt is None or attempt.help_used != "explain"


def test_qa_explain_after_commit_the_line(api: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api)
    sid = ok(api.start_session({"queue_size": 5}, True, "commit_line"))["session_id"]
    view = ok(api.next_puzzle(sid))
    with api._sessions._session(sid).lock:
        moves = api._sessions._session(sid).current.state.puzzle.moves
    assert view
    mine = list(moves[1:])
    ok(api.submit_line(sid, mine))
    show_answer(api, sid)
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    assert run_explain(api, sid)["state"] == "done"
    assert "Mode: Commit the line. The player entered:" in fake(api).requests[0].user


def test_qa_late_result_never_lands_on_the_next_puzzle(api: Any) -> None:  # noqa: F811
    """A job that finishes after you moved on mustn't show on the new puzzle."""
    plant_managed_install(api._paths)
    configure(api)
    sid, _v, _b, moves = start(api)
    show_answer(api, sid)
    import threading

    gate = threading.Event()
    f = fake(api)
    real = f.generate

    def slow(key: str, request: LLMRequest) -> LLMResponse:
        gate.wait(5)
        return real(key, request)

    f.generate = slow  # type: ignore[method-assign]
    f.queue(answer_for(moves, puzzle_fen(api, sid)))
    job = ok(api.start_explain(sid))
    ok(api.next_puzzle(sid))
    gate.set()
    api._runner.wait(job, 10)
    assert ok(api.get_explanation(sid)) is None


# ---- the key never leaves secret_store ------------------------------------------------------------


def test_qa_key_never_in_dtos_jobs_user_db_or_logs(api: Any, paths: Any) -> None:  # noqa: F811
    plant_managed_install(api._paths)
    configure(api)
    seen = [api.get_llm_settings(), api.get_llm_spend(), api.list_llm_prices()]
    job = ok(api.start_llm_key_test("anthropic", "claude-haiku-5-5"))
    api._runner.wait(job, 10)
    seen.append(api.get_job(job))
    fake(api).test_error = LLMError("bad_key", 401)
    job = ok(api.start_llm_key_test("anthropic", ""))
    api._runner.wait(job, 10)
    seen.append(api.get_job(job))
    sid, _v, _b, moves = start(api)
    show_answer(api, sid)
    seen.append(api.get_explain_quote(sid))
    fake(api).queue(LLMError("quota", 429))
    seen.append(run_explain(api, sid))
    fake(api).queue(answer_for(moves, puzzle_fen(api, sid)))
    run_explain(api, sid)
    seen.append(api.get_explanation(sid))
    blob = json.dumps(seen)
    assert FAKE_ANTHROPIC_KEY not in blob and "sk-ant-" not in blob
    with sqlite3.connect(paths.user_db) as conn:
        dump = "\n".join(conn.iterdump())
    assert FAKE_ANTHROPIC_KEY not in dump and "sk-ant-" not in dump
    for log in paths.logs_dir.glob("*.log*") if paths.logs_dir.exists() else []:
        assert "sk-ant-" not in log.read_text(encoding="utf-8", errors="replace")


# ---- provider error mapping through the real HTTP client ------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (429, {"error": {"message": "You exceeded your quota", "type": "insufficient_quota", "code": "insufficient_quota"}}, "quota"),
        (429, {"error": {"message": "slow down", "type": "requests", "code": "rate_limit_exceeded"}}, "rate_limited"),
        (401, {"error": {"message": "Incorrect API key provided: sk-FAKE...", "code": "invalid_api_key"}}, "bad_key"),
        (404, {"error": {"message": "The model does not exist", "code": "model_not_found"}}, "bad_model"),
        (400, {"error": {"message": "bad", "code": None}}, "bad_request"),
        (503, "<html>busy</html>", "server"),
    ],
)  # fmt: skip
def test_qa_openai_errors_through_the_http_client(status: int, body: Any, kind: str) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    p = OpenAIProvider(HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None))
    req = LLMRequest("m", "sys", "user", "n", {"type": "object"}, 1500, "low")
    with pytest.raises(LLMError) as e:
        p.generate(FAKE_OPENAI_KEY, req)
    assert e.value.kind == kind and len(calls) == 1  # never retried
    assert "sk-" not in str(e.value) and "exceeded" not in str(e.value)  # our message, never the provider's


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, "rate_limited"),
        (400, {"type": "error", "error": {"type": "billing_error", "message": "credit"}}, "quota"),
        (403, {"type": "error", "error": {"type": "permission_error", "message": "x"}}, "bad_key"),
        (404, {"type": "error", "error": {"type": "not_found_error", "message": "model: x"}}, "bad_model"),
        (500, {"type": "error", "error": {"type": "api_error", "message": "x"}}, "server"),
    ],
)
def test_qa_anthropic_errors_through_the_http_client(status: int, body: Any, kind: str) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(status, json=body)

    p = AnthropicProvider(HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None))
    req = LLMRequest("m", "sys", "user", "n", {"type": "object"}, 1500, "low")
    with pytest.raises(LLMError) as e:
        p.generate(FAKE_ANTHROPIC_KEY, req)
    assert e.value.kind == kind and len(calls) == 1
    assert calls[0].headers["x-api-key"] == FAKE_ANTHROPIC_KEY and "authorization" not in calls[0].headers


def test_qa_board_is_never_mutated_by_validation() -> None:
    inp = _one_ply_input()
    before = chess.Board(FEN).fen()
    validate(inp, json.dumps({"summary": "s", "steps": [{"ply": 0, "move": "Nf6", "text": "", "annotations": [],
                                                         "variation": ["Bxf7+", "Kxf7"]}], "key_ideas": []}))  # fmt: skip
    assert chess.Board(FEN).fen() == before
