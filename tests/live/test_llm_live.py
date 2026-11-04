"""Live Explain test (v0.7; ROADMAP *Done when*): opt-in with `uv run pytest -m live`. Adam runs it, never
Claude Code.

It makes exactly **one** real Explain call through the app's own path (bridge → ExplainService →
LlmUsageService → the real adapter), with the cheapest model for whichever provider has a key in the
separate `weaksquare-test` entry (`scripts/set_test_token.py --llm anthropic|openai`), a per-run cap of
$0.01 and a $0.05 budget. Stockfish is the fake engine, so no binary is needed.

With `--record-llm` it writes a scrubbed copy of the provider's response to tests/fixtures/http/llm/,
keeping only the fields the parser reads, so no IDs, headers or keys are stored (SR-12, SR-12a).
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import Any

import chess
import pytest

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "llm"
RUN_CAP = 0.01
KEEP = {
    "anthropic": ("type", "role", "content", "stop_reason", "usage"),
    "openai": ("object", "status", "incomplete_details", "output", "usage"),
}
FILE = {"anthropic": "anthropic_messages.json", "openai": "openai_responses.json"}


def _provider_with_key() -> str:
    from weaksquare.adapters.secret_store import ANTHROPIC, OPENAI, SERVICE_TEST, KeyringSecretStore, SecretStoreError

    store = KeyringSecretStore(SERVICE_TEST)
    for provider in (ANTHROPIC, OPENAI):
        try:
            if store.get(provider):
                return provider
        except SecretStoreError:
            break
    pytest.skip("no live-test AI key: run uv run python scripts/set_test_token.py --llm anthropic in your own window")


@pytest.fixture(scope="module")
def run(tmp_path_factory, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    """One real Explain, through the bridge."""
    import os

    from tests.fakes.engine import plant_managed_install
    from tests.helpers import FakeDesktop, fake_service_kwargs
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.http import HttpClient
    from weaksquare.adapters.secret_store import SERVICE_TEST, KeyringSecretStore
    from weaksquare.app import build_services
    from weaksquare.bridge.api import Api
    from weaksquare.core.clock import FixedClock
    from weaksquare.core.llm.defaults import LIVE_TEST_MODEL
    from weaksquare.jobs.runner import JobRunner

    provider = _provider_with_key()
    bodies: list[Any] = []

    class RecordingHttp(HttpClient):
        def post_json(self, url: str, body: Any, **kw: Any) -> Any:  # type: ignore[override]
            out = super().post_json(url, body, **kw)
            bodies.append(out)
            return out

    data = tmp_path_factory.mktemp("live_llm")
    old_env = os.environ.get(config.DATA_DIR_ENV)
    os.environ[config.DATA_DIR_ENV] = str(data)  # never the real data folder (NFR-2)
    paths = config.resolve_paths(dev=True)
    paths.ensure()
    clock = FixedClock()
    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    kwargs = fake_service_kwargs()
    kwargs.pop("llm_providers")  # the real adapters
    kwargs["secrets"] = KeyringSecretStore(SERVICE_TEST)
    runner = JobRunner()
    s = build_services(paths, clock, runner, random.Random(1), http=RecordingHttp(), **kwargs)
    api = Api(paths=paths, desktop=FakeDesktop(), clock=clock, dev_mode=True, runner=runner, puzzle_db=s.puzzle_db,
              mixer=s.mixer, sessions=s.sessions, presets=s.presets, stats=s.stats, ui_settings=s.ui_settings,
              db_update=s.db_update, account=s.account, sync=s.sync, history=s.history, engine=s.engine,
              reasons=s.reasons, llm_settings=s.llm_settings, llm_usage=s.llm_usage, explain=s.explain,
              games=s.games, analysis=s.analysis, review=s.review, puzzle_import=s.puzzle_import)  # fmt: skip
    plant_managed_install(paths)
    model = LIVE_TEST_MODEL[provider]
    assert api.set_llm_settings(provider, model, "low", RUN_CAP, 0.05)["ok"]
    sid = api.start_session({"queue_size": 1})["data"]["session_id"]
    api.next_puzzle(sid)
    api.request_help(sid, "hint")
    assert api.request_help(sid, "answer")["ok"]
    quote = api.get_explain_quote(sid)["data"]
    assert quote["state"] == "ok" and quote["worst_usd"] <= RUN_CAP, quote
    job_id = api.start_explain(sid)["data"]
    runner.wait(job_id, 120)
    job = api.get_job(job_id)["data"]
    explanation = api.get_explanation(sid)["data"]
    with s.db.session() as conn:
        usage = [dict(r) for r in conn.execute("SELECT * FROM llm_usage")]
    yield {"provider": provider, "model": model, "job": job, "explanation": explanation, "usage": usage,
           "bodies": bodies, "api": api, "sid": sid}  # fmt: skip
    runner.cancel_all()
    s.close()
    if old_env is None:
        os.environ.pop(config.DATA_DIR_ENV, None)
    else:
        os.environ[config.DATA_DIR_ENV] = old_env


def test_one_real_explain_under_the_cap(run) -> None:  # type: ignore[no-untyped-def]
    assert len(run["bodies"]) == 1  # exactly one generation request
    assert len(run["usage"]) == 1
    row = run["usage"][0]
    assert (row["provider"], row["model"], row["feature"]) == (run["provider"], run["model"], "explain")
    assert 0 < row["cost_usd"] <= RUN_CAP and row["input_tokens"] > 0 and row["output_tokens"] > 0
    assert run["job"]["state"] == "done", run["job"]
    x = run["explanation"]
    assert x and x["summary"] and x["steps"], x
    for step in x["steps"]:  # every square was validated (FR-8.4)
        for a in step["annotations"]:
            assert chess.parse_square(a["orig"]) >= 0


def test_the_second_explain_is_free(run) -> None:  # type: ignore[no-untyped-def]
    api, sid = run["api"], run["sid"]
    assert api.get_explain_quote(sid)["data"]["state"] == "cached"  # FR-8.6: no second request


def test_record(run, request) -> None:  # type: ignore[no-untyped-def]
    if not request.config.getoption("--record-llm"):
        pytest.skip("pass --record-llm to update the fixture")
    body = run["bodies"][0]
    kept = {k: body[k] for k in KEEP[run["provider"]] if k in body}
    if run["provider"] == "openai":  # drop item IDs inside the output too
        kept["output"] = [{k: v for k, v in item.items() if k != "id"} for item in kept.get("output", [])]
    (FIXTURES / FILE[run["provider"]]).write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    readme = FIXTURES / "README.md"
    lines = [x for x in readme.read_text(encoding="utf-8").splitlines() if not x.startswith("Status:")]
    lines.append(
        f"Status: {FILE[run['provider']]} recorded from a live response (scrubbed); the other is hand-written."
    )
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
