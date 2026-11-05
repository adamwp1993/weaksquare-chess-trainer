"""AI coaching on a Coach report: v0.10's guarantees (the anonymized prompt, validation with the
deterministic fallback, the Coach's own model and usage log, the cap and the budget, the saved answer
shown again for free) on the v0.11 whole-game diagnosis (§10.11): every answer is kept per option,
Advanced and Include my notes are per run and never remembered, and observations recur."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_game_explain import configure, fake, logged
from weaksquare.core.coach_llm import validate
from weaksquare.core.errors import AppError, ValidationError

LEAKS = ("player_a", "opponent_b", "lichess.org", "chess.com", "2026", "[%clk", "game_id", "Site", "180+0")


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _finding(ply: int = 13, **kw: Any) -> dict[str, Any]:
    f = {
        "key": "missed:mateIn1", "category": "tactical", "title": "Missed mates", "explanation": "You missed Rd8#.",
        "advice": "Check every check.", "topic": "theme:mateIn1", "evidence": [{"game": "G1", "ply": ply}],
    }  # fmt: skip
    f.update(kw)
    return f


def _answer(*findings: dict[str, Any], presets: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(
        {
            "summary": "You miss back-rank mates. See G1.",
            "weaknesses": list(findings) or [_finding(), _finding(ply=99, title="Invented", key=None)],
            "presets": presets
            if presets is not None
            else [
                {"name": "Back rank", "themes": ["backRankMate", "mateIn1", "notATheme"], "rating_min": 1200,
                 "rating_max": 1600, "lengths": [1, 7], "mode": "standard", "queue_size": 30},
            ],
        }
    )  # fmt: skip


def _report(services, paths) -> int:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    return _run(services, {"source": "games", **ANY_GAME})


def _wait(services, job: str) -> None:  # type: ignore[no-untyped-def]
    st = services.coach._runner.wait(job, 10)
    assert st is not None and st.state == "done", st


def _runs(services, rid: int) -> list[Any]:  # type: ignore[no-untyped-def]
    return services.coach.ai_runs(rid)


def test_the_prompt_is_anonymized(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_answer())
    _wait(services, services.coach.start_ai(rid))
    req = fake(services).requests[-1]
    text = req.system + req.user
    for leak in LEAKS:
        assert leak not in text, leak
    assert '"game":"G1"' in req.user and "Rd8#" in req.user  # games go as labels, positions as SAN
    assert "Move lists" not in req.user and "Your own notes" not in req.user  # a standard run
    assert "including but not limited to" in req.system
    assert req.max_tokens == 2500 and req.timeout_s == 180  # FR-8.14: Coach Summary


def test_the_answer_is_validated_saved_and_logged_under_the_coach(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    services.llm_settings.update_feature("coach", "anthropic", "claude-sonnet-5-5", "low")
    fake(services).queue(_answer())
    job = services.coach.start_ai(rid)
    _wait(services, job)
    (run,) = _runs(services, rid)
    assert services.coach.ai_job_run(job) == run.id
    assert run.format == "diagnosis" and not run.advanced and not run.include_notes
    res = run.result
    assert [f["title"] for f in res["findings"]] == ["Missed mates"]  # the invented ply is dropped
    f = res["findings"][0]
    assert f["key"] == "missed:mateIn1" and f["tentative"] is True and f["evidence"] == [{"game": "G1", "ply": 13}]
    assert res["labels"] == {"G1": services.coach.report(rid)[0].game_ids[0]}  # mapped back on your PC only
    preset = res["presets"][0]
    assert preset["themes"] == ["backRankMate", "mateIn1"] and preset["lengths"] == [1]
    assert run.model == "claude-sonnet-5-5"
    assert logged(services)[-1] == ("coach", "claude-sonnet-5-5", "ok")
    # Shown again for free: no second request.
    q = services.coach.quote_ai(rid)
    assert q.quote.state == "cached" and q.cached_run == run.id
    _wait(services, services.coach.start_ai(rid))
    assert len(fake(services).requests) == 1


def test_no_valid_preset_falls_back_to_the_reports_own(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_answer(_finding(), presets=[{"name": "x", "themes": ["nope"], "rating_min": 5000,
                                           "rating_max": 1, "lengths": [], "mode": "fly", "queue_size": 0}]))  # fmt: skip
    _wait(services, services.coach.start_ai(rid))
    (run,) = _runs(services, rid)
    assert run.result["fallback_preset"] and run.result["presets"][0]["name"] == "The report's mix"


def test_the_cap_and_the_budget_block_the_request(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    services.llm_settings.update_feature("coach", "anthropic", "claude-fable-5-1", "high")
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.01, 5.00)
    for opts in (None, {"advanced": True}):
        q = services.coach.quote_ai(rid, opts)
        assert q.quote.state == "over_cap" and q.quote.estimate.worst_usd > 0.01
        with pytest.raises(AppError):
            services.coach.start_ai(rid, opts)
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.50, 0.0)
    assert services.coach.quote_ai(rid).quote.state == "over_budget"
    assert services.coach.quote_ai(rid, {"advanced": True}).quote.state == "over_budget"
    with pytest.raises(AppError):
        services.coach.start_ai(rid, {"advanced": True})
    assert fake(services).requests == []


def test_advanced_adds_san_move_lists_and_is_kept_as_its_own_run(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    q = services.coach.quote_ai(rid, {"advanced": True, "game_cap": 10})
    assert q.quote.state == "ok" and q.compare is not None
    assert q.compare.games_with_moves == 1 and q.compare.token_ratio >= 1 and q.compare.minutes >= 1
    assert q.compare.standard_usd is not None and q.compare.budget_share is not None
    fake(services).queue(_answer(_finding()))
    _wait(services, services.coach.start_ai(rid))
    fake(services).queue(
        _answer(_finding(), _finding(ply=3, key=None, title="Early queen", topic="concept:development"))
    )
    _wait(services, services.coach.start_ai(rid, {"advanced": True, "game_cap": 10}))
    std, adv = fake(services).requests
    assert "Move lists" not in std.user
    assert (
        "Move lists (Advanced analysis; SAN only):" in adv.user
        and "G1: 1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#" in adv.user
    )
    for leak in LEAKS:
        assert leak not in adv.system + adv.user, leak
    runs = _runs(services, rid)
    assert [(r.advanced, r.game_cap) for r in runs] == [(False, None), (True, 10)]
    assert runs[0].new == () and runs[1].new == (1,)  # the early-queen finding is new in the Advanced run
    # ply 3 is citable only because the Advanced run sent the whole move list
    assert runs[1].result["findings"][1]["evidence"] == [{"game": "G1", "ply": 3}]


def test_advanced_and_notes_are_never_remembered(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    assert "advanced" not in json.dumps(services.coach._settings.get("coach.last_params"))
    with pytest.raises(ValidationError):
        services.coach.start_run({"source": "games", "advanced": True})  # not a run setting
    for bad in ({"advanced": "yes"}, {"game_cap": 9}, {"game_cap": 51}, {"game_cap": True}, {"surprise": 1}):
        with pytest.raises(ValidationError):
            services.coach.quote_ai(rid, bad)
    configure(services)
    fake(services).queue(_answer(_finding()))
    _wait(services, services.coach.start_ai(rid))  # no options: a standard run
    req = fake(services).requests[-1]
    assert "Move lists" not in req.user and "Your own notes" not in req.user


def test_notes_go_only_with_include_my_notes_and_match_the_preview(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    (gid,) = services.coach.report(rid)[0].game_ids
    services.review.set_game_reason(gid, 12, "didntLook", "saw it on https://example.org/x, missed it")
    preview = services.coach.notes_preview(rid)
    assert [(n.game, n.ply, n.reason, n.text) for n in preview] == [
        ("G1", 13, "didntLook", "saw it on [link removed] missed it")
    ]
    configure(services)
    fake(services).queue(_answer(_finding()))
    _wait(services, services.coach.start_ai(rid))
    assert "saw it on" not in fake(services).requests[-1].user
    fake(services).queue(_answer(_finding()))
    _wait(services, services.coach.start_ai(rid, {"include_notes": True}))
    user = fake(services).requests[-1].user
    assert '"note":"saw it on [link removed] missed it"' in user and "example.org" not in user
    assert [r.include_notes for r in _runs(services, rid)] == [False, True]


def test_another_players_report_gets_coaching_without_their_name(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    rid = _run(services, {"source": "games", "player": "opponent_b", "platform": "lichess", **ANY_GAME})
    configure(services)
    assert services.coach.notes_preview(rid) == []  # your notes never go with another player's report
    fake(services).queue(_answer(_finding()))
    _wait(services, services.coach.start_ai(rid))
    req = fake(services).requests[-1]
    assert "opponent_b" not in req.user and "opponent_b" not in req.system


def test_an_observation_is_noted_once_per_report(services, paths) -> None:  # type: ignore[no-untyped-def]
    obs = _finding(key=None, title="You trade when behind", topic="concept:trades")
    first = _report(services, paths)
    configure(services)
    fake(services).queue(_answer(obs))
    _wait(services, services.coach.start_ai(first))
    fake(services).queue(_answer(obs))
    _wait(services, services.coach.start_ai(first, {"include_notes": True}))  # same report: still 1
    second = _run(services, {"source": "games", **ANY_GAME})
    fake(services).queue(_answer(obs))
    _wait(services, services.coach.start_ai(second))
    assert [r.result["seen"] for r in _runs(services, first)] == [[1], [1]]
    assert _runs(services, second)[0].result["seen"] == [2]


def test_a_puzzle_history_report_keeps_the_keyed_prompt(services) -> None:  # type: ignore[no-untyped-def]
    rid = _run(services, {"source": "puzzles"})
    configure(services)
    with pytest.raises(ValidationError):
        services.coach.quote_ai(rid, {"advanced": True})
    fake(services).queue(json.dumps({"summary": "Train pins.", "weaknesses": [], "presets": []}))
    _wait(services, services.coach.start_ai(rid))
    (run,) = _runs(services, rid)
    assert run.format == "keyed"
    coaching, _ = services.coach.ai_result(rid)
    assert coaching.summary == "Train pins."


def test_validate_rejects_a_non_object() -> None:
    assert validate("[]", [], None) is None
    assert validate("not json", [], None) is None
    assert validate(json.dumps({"summary": ""}), [], None) is None
