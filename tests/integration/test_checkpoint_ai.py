"""v1.0 Auto AI checkpoint summary (FR-10.37, on by default since Adam's 2026-11-10 change): it runs without a Confirm
only when the quote is ok, otherwise it waits behind Get AI take; it never fails a checkpoint, never runs for a backfill,
and its prompt carries the checkpoint's statuses as aggregates only (no Advanced, notes or journal)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_checkpoint_backfill import _backfill, _history
from tests.integration.test_checkpoints import CLEAN, SMALL, _games, _run
from tests.integration.test_coach_ai import LEAKS, _answer
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_game_puzzles import Recorder
from weaksquare.services.checkpoints import BACKFILL_KEY, BACKFILL_VERSION


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def backfill_cp(services, paths):  # type: ignore[no-untyped-def]
    """Small settings, the backfill still to run."""
    plant_managed_install(paths)
    services.game_puzzles._engine = Recorder()
    services.checkpoints.set_settings(SMALL)
    services.scheduler.pending.clear()
    return services.checkpoints


@pytest.fixture
def cp(backfill_cp, services):  # type: ignore[no-untyped-def]
    """Small settings, the backfill already done: live checkpoints only."""
    services.coach._settings.set(BACKFILL_KEY, BACKFILL_VERSION)
    return backfill_cp


def _two_checkpoints(services) -> Any:  # type: ignore[no-untyped-def]
    _games(services, 10)
    _run(services)
    _games(services, 10, CLEAN)
    return _run(services)


def test_on_and_set_up_the_summary_runs_without_a_confirm(services, cp) -> None:  # type: ignore[no-untyped-def]
    assert services.checkpoints.settings().auto_ai is True  # the default
    configure(services)
    services.checkpoints.set_settings({**SMALL, "auto_ai": False})
    _games(services, 10)
    _run(services)  # the first checkpoint, without AI
    services.checkpoints.set_settings(SMALL)
    fake(services).queue(_answer())
    _games(services, 10, CLEAN)
    st = _run(services)
    assert st.message.endswith("AI summary ready.")
    cp2 = services.checkpoints._repo.last()
    assert cp2.ai_run_id is not None and services.coach.latest_ai_run(cp2.report_id) == cp2.ai_run_id
    req = fake(services).requests[-1]
    assert "Checkpoint (aggregates only):" in req.user and "checkpoint commentary" in req.system
    assert '"status":"improving"' in req.user and '"from":"training","to":"improving"' in req.user


def test_the_summary_prompt_has_aggregates_only(services, cp) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    fake(services).queue(_answer())
    fake(services).queue(_answer())
    _two_checkpoints(services)
    req = fake(services).requests[-1]
    text = req.system + req.user
    for leak in LEAKS:
        assert leak not in text, leak
    assert "Move lists" not in req.user and "Your own notes" not in req.user and "journal" not in req.user


def test_no_ai_key_sends_nothing_and_the_checkpoint_is_saved(services, cp) -> None:  # type: ignore[no-untyped-def]
    st = _two_checkpoints(services)
    assert fake(services).requests == [] and st.message.startswith("Checkpoint #2 saved")
    assert "AI" not in st.message
    assert services.checkpoints._repo.last().ai_run_id is None


def test_over_the_cap_it_waits_for_get_ai_take(services, cp) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.0001, 5.00)  # a per-run cap nothing fits
    st = _two_checkpoints(services)
    assert fake(services).requests == [] and "Get AI take" in st.message
    last = services.checkpoints._repo.last()
    assert last.ai_run_id is None
    # Get AI take: the report's own Get AI coaching, with the usual estimate and Confirm.
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.50, 5.00)
    fake(services).queue(_answer())
    job = services.coach.start_ai(last.report_id)
    st = services.coach._runner.wait(job, 10)
    assert st is not None and st.state == "done"
    view = services.checkpoints.progress()
    assert view.checkpoints[-1].ai_run_id is not None  # shown as this checkpoint's AI summary


def test_off_it_never_runs(services, cp) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    services.checkpoints.set_settings({**SMALL, "auto_ai": False})
    _two_checkpoints(services)
    assert fake(services).requests == []


def test_a_bad_answer_never_fails_the_checkpoint(services, cp) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    fake(services).queue("not json at all")
    _games(services, 6)
    st = _run(services)
    assert st.state == "done" and "Get AI take" in st.message
    assert services.checkpoints._repo.last().number == 1


def test_a_backfill_never_asks_the_ai(services, backfill_cp) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    _history(services)
    _backfill(services)
    assert len(services.checkpoints._repo.all()) == 3 and fake(services).requests == []


def test_another_report_gets_no_checkpoint_part(services, cp) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    services.checkpoints.set_settings({**SMALL, "auto_ai": False})
    _games(services, 6)
    _run(services)
    job = services.coach.start_run({"source": "games", "rated_only": False, "time_classes": []})
    services.coach._runner.wait(job, 30)
    rid = services.coach.run_result(job)
    fake(services).queue(_answer())
    services.coach._runner.wait(services.coach.start_ai(rid), 10)
    req = fake(services).requests[-1]
    assert "Checkpoint (aggregates only):" not in req.user and "checkpoint commentary" not in req.system
