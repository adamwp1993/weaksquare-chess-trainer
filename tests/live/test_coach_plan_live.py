"""Live AI coaching with the plan (v0.12): opt-in with `uv run pytest -m live tests/live/test_coach_plan_live.py`.
Adam runs it, never Claude Code.

The mock can't tell whether a real provider accepts the v0.12 schema, with its nested weeks → days → tasks and its
nullable fields, so this makes exactly **one** real Get AI coaching call through the app's own path, with the cheapest
model for whichever provider has a key in the separate `weaksquare-test` entry. Per-run cap $0.05, budget $0.10. The
game is the anonymized fixture game with a hand-made analysis, so no Stockfish is needed. It also checks what really
went out: no player name from the PGN and none of the journal unless asked (FR-8.16, FR-10.71).
"""

from __future__ import annotations

import json
import random
import shutil
from typing import Any

import chess
import pytest

from tests.integration.test_review import ANALYSES, MOVES, SCHOLAR
from tests.live.test_game_review_live import _provider_with_key

pytestmark = pytest.mark.live

RUN_CAP = 0.05
JOURNAL = "A journal line that must stay home"


@pytest.fixture(scope="module")
def run(tmp_path_factory, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    import os

    from tests.helpers import FakeDesktop, fake_service_kwargs
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.db.repos.coach import CoachReportsRepo
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

    class RecordingHttp(HttpClient):
        def post_json(self, url: str, body: Any, **kw: Any) -> Any:  # type: ignore[override]
            sent.append(body)
            return super().post_json(url, body, **kw)

    data = tmp_path_factory.mktemp("live_coach_plan")
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
              journal=s.journal, openings=s.openings, opening_sources=s.opening_sources, opening_notes=s.opening_notes, repertoire=s.repertoire)  # fmt: skip
    model = LIVE_TEST_MODEL[provider]
    gid = api.import_game_pgn(SCHOLAR)["data"]["game_id"]
    assert api.set_game_color(gid, "black")["ok"]
    GameAnalysisRepo(s.db).replace(gid, grade_game(chess.STARTING_FEN, MOVES, ANALYSES), "analyzed", 0.3, "fixture")
    weak = {
        "key": "missed:fork", "kind": "missed", "name": "fork", "label": "Missed: Fork", "count": 1, "per10": 10.0,
        "severity": 300, "score": 3.0, "themes": ["fork"], "mode": None, "reasons": {},
        "examples": [{"game_id": gid, "ply": 5, "cp_loss": 300}],
    }  # fmt: skip
    rid = CoachReportsRepo(s.db).add(
        "2026-01-01T10:00:00+00:00", "me", "You", "games", {"detail": "summary"},
        {"source": "games", "games": 1, "per10": {"blunders": 10.0}, "results": {}, "weaknesses": [weak], "missed": [weak],
         "allowed": [], "habits": [], "puzzles": [], "whole_game": []},
        [gid],
    )  # fmt: skip
    assert api.add_journal_entry({"text": JOURNAL, "game_id": gid})["ok"]
    assert api.set_setting("plan.params", {"weeks": 1, "weekdays": [0, 1], "minutes": 20})["ok"]
    assert api.set_llm_settings(provider, "", "low", RUN_CAP, 0.10)["ok"]
    assert api.set_llm_feature("coach", provider, model, "low")["ok"]
    quote = api.get_coach_ai_quote(rid, None)["data"]["quote"]
    assert quote["state"] == "ok" and quote["worst_usd"] <= RUN_CAP, quote
    job_id = api.start_coach_ai(rid, None)["data"]
    runner.wait(job_id, 300)
    job = api.get_job(job_id)["data"]
    runs = api.list_coach_ai_runs(rid)["data"]
    answer = api.get_coach_ai_run(rid, runs[-1]["id"])["data"] if runs else None
    with s.db.session() as conn:
        usage = [dict(r) for r in conn.execute("SELECT * FROM llm_usage")]
    yield {"job": job, "answer": answer, "usage": usage, "sent": sent, "api": api}
    runner.cancel_all()
    s.close()
    if old_env is None:
        os.environ.pop(config.DATA_DIR_ENV, None)
    else:
        os.environ[config.DATA_DIR_ENV] = old_env


def test_the_provider_accepts_the_schema_and_the_answer_is_complete(run) -> None:  # type: ignore[no-untyped-def]
    assert run["job"]["state"] == "done", run["job"]
    assert len(run["usage"]) == 1 and 0 < run["usage"][0]["cost_usd"] <= RUN_CAP
    plan = run["answer"]["plan"]
    assert plan is not None and len(plan["days"]) == 2
    for day in plan["days"]:
        assert sum(t["minutes"] for t in day["tasks"]) == 20 and 2 <= len(day["tasks"]) <= 4


def test_the_ai_plan_was_usable_not_just_replaced_by_the_free_one(run) -> None:  # type: ignore[no-untyped-def]
    """Not a schema failure if it does fail, but it says the plan rules in the prompt need work."""
    assert run["answer"]["plan_check"]["fallback"] is False, run["answer"]["plan_check"]


def test_the_request_holds_no_names_and_no_journal(run) -> None:  # type: ignore[no-untyped-def]
    text = json.dumps(run["sent"])
    assert JOURNAL not in text
    for leak in ("[White", "[Black", "[Site", "opponent_b", "player_a"):  # the fixture PGN's tags and names
        assert leak not in text
