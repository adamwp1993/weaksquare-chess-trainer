"""The LLM settings through the bridge (v0.7): no key ever comes back (SR-1), arguments are validated
(SR-2), Test key and the FR-1.6 launch check run as jobs, the price table is editable (FR-8.9) and the spend
indicator has what it needs (FR-1.10)."""

from __future__ import annotations

import json
from typing import Any

from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FAKE_OPENAI_KEY
from tests.helpers import build_api
from weaksquare.config import Paths
from weaksquare.core.clock import FixedClock
from weaksquare.core.llm.provider import LLMError


def ok(r: dict[str, Any]) -> Any:
    assert r.get("ok"), r
    return r["data"]


def wait(api: Any, job_id: str) -> dict[str, Any]:
    api._runner.wait(job_id, 5)
    return ok(api.get_job(job_id))


def test_defaults_nothing_preselected(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    d = ok(build_api(paths, clock).get_llm_settings())
    assert (d["provider"], d["reasoning"], d["run_cap_usd"], d["monthly_budget_usd"]) == ("none", "low", 0.5, 5.0)
    assert [(p["provider"], p["key_stored"], p["model"]) for p in d["providers"]] == [
        ("anthropic", False, ""),
        ("openai", False, ""),
    ]
    anthropic = d["providers"][0]["models"]
    assert anthropic[0]["model"] == "claude-haiku-5-5"  # cheapest first, from the seeded price table
    assert 0 < anthropic[0]["explain_usd"] < anthropic[-1]["explain_usd"]
    assert d["spend"] == {"month": "2026-01", "spent_usd": 0.0, "budget_usd": 5.0, "level": "ok", "configured": False}
    assert d["key_check"] == "none"


def test_saving_a_key_never_returns_it(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    responses = [
        api.set_llm_key("anthropic", FAKE_ANTHROPIC_KEY),
        api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 5.0),
        api.get_llm_settings(),
        api.list_llm_prices(),
        api.get_llm_spend(),
        api.set_llm_key("openai", FAKE_OPENAI_KEY),
    ]
    for r in responses:
        assert FAKE_ANTHROPIC_KEY not in json.dumps(r) and FAKE_OPENAI_KEY not in json.dumps(r)
    d = ok(api.get_llm_settings())
    assert d["provider"] == "anthropic" and [p["key_stored"] for p in d["providers"]] == [True, True]
    assert d["providers"][0]["model"] == "claude-haiku-5-5" and d["spend"]["configured"] is True
    with services.db.session() as conn:  # not in user.db either (SR-1)
        dump = str([tuple(r) for r in conn.execute("SELECT * FROM settings").fetchall()])
    assert FAKE_ANTHROPIC_KEY not in dump
    ok(api.delete_llm_key("anthropic"))
    assert ok(api.get_llm_settings())["spend"]["configured"] is False


def test_bad_arguments_are_refused(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    bad = [
        api.set_llm_settings("google", "m", "low", 0.5, 5.0),
        api.set_llm_settings("anthropic", "m", "max", 0.5, 5.0),
        api.set_llm_settings("anthropic", "m", "low", -1, 5.0),
        api.set_llm_settings("anthropic", "m", "low", 0.5, "5"),
        api.set_llm_settings("anthropic", "bad model!", "low", 0.5, 5.0),
        api.set_llm_key("anthropic", FAKE_OPENAI_KEY),  # an OpenAI key in the Anthropic field
        api.set_llm_key("none", FAKE_ANTHROPIC_KEY),
        api.save_llm_price("anthropic", "x", "1", 1.0),
        api.delete_llm_price("anthropic", "not-there"),
    ]
    codes = [r["error"]["code"] for r in bad]
    assert codes[:-1] == ["invalid_argument"] * 8 and codes[-1] == "not_found"
    assert FAKE_OPENAI_KEY not in json.dumps(bad)  # the refused key isn't echoed


def test_test_key_job(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    assert ok(api.get_llm_settings())  # seeds
    assert api.start_llm_key_test("anthropic", "")["error"]["code"] == "invalid_argument"  # no key yet
    ok(api.set_llm_key("anthropic", FAKE_ANTHROPIC_KEY))
    job = wait(api, ok(api.start_llm_key_test("anthropic", "claude-haiku-5-5")))
    assert job["state"] == "done" and "works with claude-haiku-5-5" in job["message"]
    fake = api._llm_settings._providers["anthropic"]
    assert fake.requests == []  # free: no generation request
    fake.test_error = LLMError("bad_key", 401)
    job = wait(api, ok(api.start_llm_key_test("anthropic", "claude-haiku-5-5")))
    assert job["state"] == "failed" and job["error_code"] == "llm_bad_key" and "rejected" in job["message"]
    assert FAKE_ANTHROPIC_KEY not in json.dumps(job)


def test_launch_check(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    assert api._llm_settings.start_launch_check() is None  # no AI set up: nothing to check
    ok(api.set_llm_key("anthropic", FAKE_ANTHROPIC_KEY))
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 5.0))
    job = api._llm_settings.start_launch_check()
    api._runner.wait(job, 5)
    assert ok(api.get_llm_settings())["key_check"] == "ok"
    api._llm_settings._providers["anthropic"].test_error = LLMError("network")
    api._runner.wait(api._llm_settings.start_launch_check(), 5)
    d = ok(api.get_llm_settings())
    assert d["key_check"] == "failed" and "internet" in d["key_check_message"]
    ok(api.set_llm_key("anthropic", FAKE_ANTHROPIC_KEY))  # a new key: the old result no longer applies
    assert ok(api.get_llm_settings())["key_check"] == "none"


def test_price_table_editing(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    rows = ok(api.list_llm_prices())
    assert len(rows) == 8
    haiku = next(r for r in rows if r["model"] == "claude-haiku-5-5")
    assert (haiku["long_ctx_threshold"], haiku["long_input_per_m"], haiku["long_output_per_m"]) == (100000, 0.5, 2.5)
    rows = ok(api.save_llm_price("openai", "gpt-custom", 1, 2.5))
    custom = next(r for r in rows if r["model"] == "gpt-custom")
    assert custom["as_of"] == "2026-01-01" and custom["input_per_m"] == 1.0  # dated today by default
    rows = ok(api.delete_llm_price("openai", "gpt-custom"))
    assert all(r["model"] != "gpt-custom" for r in rows)
    # the dropdown follows the table
    d = ok(api.get_llm_settings())
    assert "gpt-custom" not in [m["model"] for m in d["providers"][1]["models"]]


def test_reasoning_level_changes_the_per_model_cost(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    low = ok(api.get_llm_settings())["providers"][0]["models"][0]["explain_usd"]
    high = ok(api.set_llm_settings("none", "", "high", 0.5, 5.0))["providers"][0]["models"][0]["explain_usd"]
    assert high > low  # FR-8.15: the estimate accounts for reasoning
