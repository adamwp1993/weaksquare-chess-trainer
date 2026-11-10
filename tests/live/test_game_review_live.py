"""Live Explain my game test (v0.9): opt-in with `uv run pytest -m live tests/live/test_game_review_live.py`.
Adam runs it, never Claude Code.

It makes exactly **one** real Explain my game call through the app's own path (bridge → GameExplainService →
LlmUsageService → the real adapter) with the cheapest model for whichever provider has a key in the separate
`weaksquare-test` entry (`scripts/set_test_token.py --llm anthropic|openai`), set as **Game Review's own
model** (FR-1.15) while Explain keeps none. Per-run cap $0.02, budget $0.05. The game is the anonymized
fixture game with a hand-made analysis, so no Stockfish is needed. It also checks the request that really
went out: no player name, header or result tag of the PGN is in it (FR-8.16, FR-11.19).
"""

from __future__ import annotations

import json
import random
import shutil
from typing import Any

import chess
import pytest

from tests.integration.test_review import ANALYSES, MOVES, SCHOLAR

pytestmark = pytest.mark.live

RUN_CAP = 0.02


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
    import os

    from tests.helpers import FakeDesktop, fake_service_kwargs
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
    from weaksquare.adapters.http import HttpClient
    from weaksquare.adapters.secret_store import SERVICE_TEST, KeyringSecretStore
    from weaksquare.app import build_services
    from weaksquare.bridge.api import Api
    from weaksquare.core.clock import FixedClock
    from weaksquare.core.game_review import grade_game
    from weaksquare.core.llm.defaults import LIVE_TEST_MODEL
    from weaksquare.jobs.runner import JobRunner

    provider = _provider_with_key()
    sent: list[Any] = []
    bodies: list[Any] = []

    class RecordingHttp(HttpClient):
        def post_json(self, url: str, body: Any, **kw: Any) -> Any:  # type: ignore[override]
            sent.append(body)
            out = super().post_json(url, body, **kw)
            bodies.append(out)
            return out

    data = tmp_path_factory.mktemp("live_game_review")
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
              games=s.games, analysis=s.analysis, review=s.review, puzzle_import=s.puzzle_import,
              game_explain=s.game_explain, game_puzzles=s.game_puzzles, coach=s.coach, plan=s.plan,
              journal=s.journal, openings=s.openings, opening_sources=s.opening_sources, opening_notes=s.opening_notes, opening_practice=s.opening_practice, repertoire=s.repertoire, studies=s.studies, lichess_window=s.lichess_window, backup=s.backup, checkpoints=s.checkpoints, setup=s.setup)  # fmt: skip
    model = LIVE_TEST_MODEL[provider]
    gid = api.import_game_pgn(SCHOLAR)["data"]["game_id"]
    assert api.set_game_color(gid, "black")["ok"]
    GameAnalysisRepo(s.db).replace(gid, grade_game(chess.STARTING_FEN, MOVES, ANALYSES), "analyzed", 0.3, "fixture")
    assert api.set_llm_settings(provider, "", "low", RUN_CAP, 0.05)["ok"]  # Explain: no model
    assert api.set_llm_feature("game_review", provider, model, "low")["ok"]  # Game Review: its own
    quote = api.get_game_narrative_quote(gid, None)["data"]
    assert quote["state"] == "ok" and quote["model"] == model and quote["worst_usd"] <= RUN_CAP, quote
    job_id = api.start_game_narrative(gid, None)["data"]
    runner.wait(job_id, 180)
    job = api.get_job(job_id)["data"]
    narrative = api.get_game_narrative(gid, None)["data"]
    with s.db.session() as conn:
        usage = [dict(r) for r in conn.execute("SELECT * FROM llm_usage")]
    yield {"provider": provider, "model": model, "job": job, "narrative": narrative, "usage": usage, "sent": sent,
           "bodies": bodies, "api": api, "gid": gid}  # fmt: skip
    runner.cancel_all()
    s.close()
    if old_env is None:
        os.environ.pop(config.DATA_DIR_ENV, None)
    else:
        os.environ[config.DATA_DIR_ENV] = old_env


def test_one_real_explain_my_game_under_the_cap(run) -> None:  # type: ignore[no-untyped-def]
    assert len(run["bodies"]) == 1  # exactly one generation request
    assert run["job"]["state"] == "done", run["job"]
    (row,) = run["usage"]
    assert (row["provider"], row["model"], row["feature"]) == (run["provider"], run["model"], "game_review")
    assert 0 < row["cost_usd"] <= RUN_CAP and row["input_tokens"] > 0 and row["output_tokens"] > 0
    n = run["narrative"]
    assert n and n["summary"] and n["key_moments"] == [5], n
    for m in n["moments"]:  # every move and square was validated
        assert m["ply"] == 5 and m["played_san"] == "Nf6"
        assert not m["better_uci"] or m["better_uci"][0] == "d8e7"
        for a in m["annotations"]:
            assert chess.parse_square(a["orig"]) >= 0


def test_the_request_was_anonymized(run) -> None:  # type: ignore[no-untyped-def]
    text = json.dumps(run["sent"][0])
    for word in ("opponent_b", "player_a", '[White "', '[Black "', '[Result "'):
        assert word not in text, word
    assert "Qxf7#" in text  # the SAN move list is there


def test_the_second_request_is_free(run) -> None:  # type: ignore[no-untyped-def]
    assert run["api"].get_game_narrative_quote(run["gid"], None)["data"]["state"] == "cached"
