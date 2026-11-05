"""AI coaching with the plan, the journal and the trend, end to end (v0.12, FR-10.66, 10.71, 10.73)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.plan_llm_helpers import plan_answer
from tests.integration.test_coach_ai import _answer, _report, _runs, _wait
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_qa_v011_coach import _games
from weaksquare.adapters.db.repos.coach import AiRunsRepo, CoachReportsRepo
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.plan import PUZZLES
from weaksquare.services.analysis import THINK_KEY
from weaksquare.services.coach import CoachAiOptions


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _with(plan: Any = None, trend: Any = None) -> str:
    """The standard answer, with a plan and trend."""
    data = json.loads(_answer())
    data["plan"] = plan if plan is not None else {"weeks": []}
    data["trend"] = trend or []
    return json.dumps(data)


# ---- what's sent ----


def test_your_report_asks_for_a_plan_in_your_shape(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    services.plan._settings.set("plan.params", {"weeks": 3, "weekdays": [1, 3], "minutes": 40})
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    req = fake(services).requests[-1]
    assert "3 week(s), 2 training day(s) a week, 40 minutes a day" in req.user
    assert '"plan"' in req.system and "plan" in req.schema["required"] and "trend" in req.schema["required"]


def test_the_new_limits_reach_the_request(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    req = fake(services).requests[-1]
    assert req.max_tokens == 7500 and req.timeout_s == 300  # FR-8.14; v0.12 planning


def test_another_players_report_gets_no_plan_and_no_journal(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    gid = _games(services, 1)[0]
    services.journal.add("My private note.", game_id=gid)
    with services.db.transaction() as conn:
        conn.execute("UPDATE game_subjects SET subject = 'lichess:someone' WHERE game_id = ?", (gid,))
    rid = CoachReportsRepo(services.db).add(
        "2026-11-05T10:00:00+00:00", "lichess:someone", "someone", "games", {"detail": "summary"},
        {"source": "games", "games": 1, "weaknesses": [], "missed": [], "whole_game": []}, [gid],
    )  # fmt: skip
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid, {"include_journal": True}))
    req = fake(services).requests[-1]
    assert "plan" not in req.schema["required"] and "Plan shape" not in req.user
    assert "My private note." not in req.user
    assert "plan" not in _runs(services, rid)[-1].result
    assert services.coach.journal_preview(rid) == []


def test_journal_text_goes_only_with_the_option_and_the_preview_is_what_is_sent(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    gid = services.coach.report(rid)[0].game_ids[0]
    services.journal.add("I rushed this one, https://lichess.org/AbCd1234 shows it.", game_id=gid, ply=12, weakness_key="missed:mateIn1")  # fmt: skip
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    assert "rushed" not in fake(services).requests[-1].user  # off by default

    preview = services.coach.journal_preview(rid)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid, {"include_journal": True}))
    user = fake(services).requests[-1].user
    assert len(preview) == 1 and preview[0].text in user
    assert preview[0].game == "G1" and preview[0].ply == 13  # the report's label, 1-based
    assert "lichess.org" not in user and "AbCd1234" not in user
    assert f'"game_id":{gid}' not in user


def test_the_options_are_never_remembered(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid, {"include_journal": True}))
    assert "include_journal" not in json.dumps(services.coach.last_params().to_json())
    assert CoachAiOptions.from_json(None).include_journal is False


def test_a_puzzle_only_report_refuses_the_journal(services) -> None:  # type: ignore[no-untyped-def]
    rid = CoachReportsRepo(services.db).add(
        "2026-11-05T10:00:00+00:00", "me", "You", "puzzles", {"detail": "summary"},
        {"source": "puzzles", "games": 0, "puzzles": [], "weaknesses": []}, [],
    )  # fmt: skip
    configure(services)
    with pytest.raises(ValidationError):
        services.coach.quote_ai(rid, {"include_journal": True})


# ---- saved answers ----


def test_a_journal_edit_forces_a_new_request_and_no_edit_reuses_the_answer(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    gid = services.coach.report(rid)[0].game_ids[0]
    eid = services.journal.add("First words.", game_id=gid)
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid, {"include_journal": True}))
    sent = len(fake(services).requests)
    assert services.coach.quote_ai(rid, {"include_journal": True}).quote.state == "cached"
    _wait(services, services.coach.start_ai(rid, {"include_journal": True}))
    assert len(fake(services).requests) == sent  # the same text: the saved answer

    services.journal.edit(eid, "Different words.")
    assert services.coach.quote_ai(rid, {"include_journal": True}).quote.state == "ok"
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid, {"include_journal": True}))
    assert len(fake(services).requests) == sent + 1
    assert "Different words." in fake(services).requests[-1].user


def test_a_stored_answer_without_a_plan_is_not_reused_for_your_report(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    cfg = services.llm_settings.config("coach")
    AiRunsRepo(services.db).add(
        rid, "2026-11-04T10:00:00+00:00", "diagnosis", advanced=False, include_notes=False, game_cap=None,
        provider=cfg.provider, model=cfg.model, cost_usd=0.01, result={"summary": "from v0.11", "findings": []},
    )  # fmt: skip
    assert services.coach.quote_ai(rid).quote.state == "ok"
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    assert services.coach.quote_ai(rid).quote.state == "cached"
    assert [("plan" in r.result) for r in _runs(services, rid)] == [False, True]


def test_changing_the_plan_settings_does_not_rebill_you(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    services.plan._settings.set("plan.params", {"weeks": 4, "weekdays": [0], "minutes": 90})
    assert services.coach.quote_ai(rid).quote.state == "cached"


# ---- the AI's plan ----


def test_the_ai_plan_is_validated_and_stored_complete(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    services.plan._settings.set("plan.params", {"weeks": 1, "weekdays": [0, 1], "minutes": 20})
    configure(services)
    fake(services).queue(_with(plan=plan_answer()))
    _wait(services, services.coach.start_ai(rid))
    res = _runs(services, rid)[-1].result
    assert (
        res["plan_check"]["ai_tasks"] >= 1 and res["plan_check"]["dropped"] == 1 and not res["plan_check"]["fallback"]
    )
    for day in res["plan"]["days"]:
        assert sum(t["minutes"] for t in day["tasks"]) == 20
    assert not any("invented" in json.dumps(t) for d in res["plan"]["days"] for t in d["tasks"])


def test_a_broken_ai_plan_falls_back_to_the_deterministic_one(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_with(plan={"weeks": "nonsense"}))
    _wait(services, services.coach.start_ai(rid))
    res = _runs(services, rid)[-1].result
    assert res["plan_check"]["fallback"] is True
    assert res["plan"]["days"]
    assert res["plan"] == services.plan.build(services.coach.report(rid)[0], services.plan.params()).to_json()


def test_an_answer_with_no_plan_at_all_still_offers_the_deterministic_one(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_answer())
    _wait(services, services.coach.start_ai(rid))
    assert _runs(services, rid)[-1].result["plan_check"]["fallback"] is True


def test_use_this_plan_makes_it_current_with_a_confirm(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_with(plan=plan_answer()))
    _wait(services, services.coach.start_ai(rid))
    run = _runs(services, rid)[-1]
    first = services.coach.use_ai_plan(run.id)
    view = services.plan.current()
    assert view.plan.id == first and view.plan.source == "ai" and view.plan.ai_run_id == run.id
    with pytest.raises(ConflictError):
        services.coach.use_ai_plan(run.id)
    assert services.coach.use_ai_plan(run.id, True) != first


def test_an_answer_with_no_plan_cannot_be_used(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    run = AiRunsRepo(services.db).add(
        rid, "2026-11-04T10:00:00+00:00", "diagnosis", advanced=False, include_notes=False, game_cap=None,
        provider="p", model="m", cost_usd=0, result={"findings": []},
    )  # fmt: skip
    with pytest.raises(NotFoundError):
        services.coach.use_ai_plan(run)


def test_plan_progress_goes_as_aggregates(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    services.plan.create({"weeks": 1})
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    user = fake(services).requests[-1].user
    assert "How the current training plan went" in user and '"tasks_by_type"' in user
    part = user.split("How the current training plan went", 1)[1].split("\n\n", 1)[0]
    assert "your game against" not in part and "game_id" not in part and '"title"' not in part


# ---- the trend ----


def _two_reports(services: Any, paths: Any) -> tuple[int, int]:
    plant_managed_install(paths)
    _games(services, 6)
    a = _run(services, {"source": "games", **ANY_GAME})
    _games(services, 12)  # the same 6, and 6 new ones
    b = _run(services, {"source": "games", **ANY_GAME})
    return a, b


def test_a_first_report_has_no_trend(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    assert services.coach.comparison(rid) is None
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(rid))
    assert "Since last report" not in fake(services).requests[-1].user


def test_the_second_report_is_compared_and_the_prompt_part_is_aggregates(services, paths) -> None:  # type: ignore[no-untyped-def]
    a, b = _two_reports(services, paths)
    c = services.coach.comparison(b)
    assert c is not None and c.earlier_id == a and c.settings == "same"
    assert (c.new_games, c.shared_games, c.enough_new_games) == (6, 6, True)
    configure(services)
    fake(services).queue(_with())
    _wait(services, services.coach.start_ai(b))
    user = fake(services).requests[-1].user
    part = user.split("Since last report (aggregates only):", 1)[1].split("\n\n", 1)[0]
    data = json.loads(part)
    assert data["reports"][0]["label"] == "1 report ago"
    assert "created_at" not in part and '"game_id"' not in part


def test_a_trend_statement_must_match_the_numbers(services, paths) -> None:  # type: ignore[no-untyped-def]
    _, b = _two_reports(services, paths)
    c = services.coach.comparison(b)
    row = next(w for w in c.weaknesses if w.verdict in ("better", "worse", "same"))
    right = {"better": "improved", "worse": "worse", "same": "same"}[row.verdict]
    wrong = "worse" if right != "worse" else "improved"
    configure(services)
    good = {"key": row.key, "change": right, "comment": "Holding up."}
    bad = {"key": "missed:invented", "change": wrong, "comment": "Made up."}
    fake(services).queue(_with(trend=[good, bad]))
    _wait(services, services.coach.start_ai(b))
    res = _runs(services, b)[-1].result
    assert res["trend"] == [good] and res["trend_dropped"] == 1


def test_a_changed_analysis_setting_is_flagged(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _games(services, 6)
    _run(services, {"source": "games", **ANY_GAME})
    services.plan._settings.set(THINK_KEY, 1.0)
    _my_games(services, 6)
    b = _run(services, {"source": "games", **ANY_GAME})
    assert services.coach.comparison(b).settings == "different"


def test_reports_from_before_v012_show_unknown_settings(services, paths) -> None:  # type: ignore[no-untyped-def]
    a, b = _two_reports(services, paths)
    with services.db.transaction() as conn:
        row = conn.execute("SELECT report_json FROM coach_reports WHERE id = ?", (a,)).fetchone()
        data = json.loads(row[0])
        data.pop("analysis_settings", None)
        conn.execute("UPDATE coach_reports SET report_json = ? WHERE id = ?", (json.dumps(data), a))
    assert services.coach.comparison(b).settings == "unknown"


def test_another_players_reports_never_compare_with_yours(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    theirs = CoachReportsRepo(services.db).add(
        "2026-11-05T10:00:00+00:00", "lichess:someone", "someone", "games", {},
        {"source": "games", "games": 10, "weaknesses": [], "missed": [], "whole_game": []}, [],
    )  # fmt: skip
    assert rid < theirs and services.coach.comparison(theirs) is None


def test_puzzle_history_reports_compare_only_with_each_other(services, paths) -> None:  # type: ignore[no-untyped-def]
    repo = CoachReportsRepo(services.db)
    games = _report(services, paths)
    row = {"key": "puzzle:fork", "label": "Fork", "puzzle_accuracy": 0.5}
    a = repo.add("2026-11-05T10:00:00+00:00", "me", "You", "puzzles", {}, {"source": "puzzles", "games": 0, "puzzles": [row]}, [])  # fmt: skip
    assert services.coach.comparison(a) is None  # the earlier report is on games
    b = repo.add("2026-11-06T10:00:00+00:00", "me", "You", "puzzles", {}, {"source": "puzzles", "games": 0, "puzzles": [row]}, [])  # fmt: skip
    assert services.coach.comparison(b).earlier_id == a
    assert services.coach.comparison(games) is None


def test_puzzle_tasks_in_the_ai_plan_use_a_known_type(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_with(plan=plan_answer()))
    _wait(services, services.coach.start_ai(rid))
    types = {t["type"] for d in _runs(services, rid)[-1].result["plan"]["days"] for t in d["tasks"]}
    assert PUZZLES in types
