"""v1.0 first-run wizard (NFR-8, FR-15.4) through the services and the bridge: a fresh install shows it, an existing
one doesn't, each step resumes from what's installed, and a restore from it comes back at the puzzle-database step."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.engine import plant_managed_install
from tests.helpers import api_for
from tests.integration.test_backup import backup_of, dump, files_for, new_install, seed
from weaksquare import config
from weaksquare.adapters.db.migrate import migrate
from weaksquare.app import apply_staged_restore
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import ValidationError
from weaksquare.services.setup_state import CHOICE_KEY


def _no_puzzles(services: Any) -> Any:
    """A fresh install: no puzzle database imported yet. Returns the real deps, to put the database back."""
    real = services.puzzle_db._d
    services.puzzle_db._d = replace(real, read_meta=lambda: None)
    return real


def test_a_fresh_install_shows_the_wizard_at_welcome(services: Any) -> None:
    _no_puzzles(services)
    st = services.setup.state()
    assert st.show and st.step == "welcome" and not st.facts.has_data


def test_an_install_with_your_data_and_its_puzzle_database_never_shows_it(services: Any) -> None:
    seed(services)
    st = services.setup.state()
    assert st.facts.puzzles_installed and st.facts.has_data and not st.show


def test_a_first_launch_after_setup_imported_the_puzzles_shows_it_at_welcome(services: Any) -> None:
    st = services.setup.state()
    assert st.facts.puzzles_installed and not st.facts.has_data
    assert st.show and st.step == "welcome"


def test_start_fresh_then_each_step_follows_what_is_installed(services: Any, paths: config.Paths) -> None:
    real = _no_puzzles(services)
    assert services.setup.choose("fresh").step == "puzzles"
    services.puzzle_db._d = real  # the import finished
    st = services.setup.state()
    assert st.show and st.step == "engine"  # still shown: you started it
    plant_managed_install(paths)
    assert services.setup.state().step == "lichess"
    with pytest.raises(ValidationError):
        services.setup.finish()  # a step is left
    assert services.setup.skip("lichess").step == "done"
    st = services.setup.finish()
    assert not st.show and services.setup.state().facts.finished


def test_an_older_puzzle_database_is_upgraded_at_the_puzzle_step_not_downloaded(services: Any, paths: config.Paths,
                                                                                clock: FixedClock) -> None:  # fmt: skip
    """v1.0 self-check regression: a fresh install with a v0.1 puzzles.db must get the upgrade screen."""
    real = services.puzzle_db._d
    services.puzzle_db._d = replace(real, latest_schema=real.schema_version(real.puzzles_db) + 1)
    services.setup.choose("fresh")
    st = services.setup.state()
    assert st.step == "puzzles" and st.puzzles_need_upgrade and not st.facts.puzzles_installed
    api = api_for(services, paths, clock, services.checkpoints._runner)
    assert api.get_setup_state()["data"]["puzzles_need_upgrade"] is True
    services.puzzle_db._d = real  # upgraded
    st = services.setup.state()
    assert st.step == "engine" and not st.puzzles_need_upgrade


def test_closing_the_app_resumes_at_the_same_step(services: Any) -> None:
    _no_puzzles(services)
    services.setup.choose("fresh")
    services.setup.skip("engine")
    # Nothing stores the step: a new SetupService over the same data folder decides the same.
    from weaksquare.services.setup_state import SetupService

    again = SetupService(services.setup._settings, services.puzzle_db, services.engine, services.account, lambda: False)
    assert again.state().step == "puzzles"


def test_only_engine_and_lichess_can_be_skipped(services: Any) -> None:
    for bad in ("puzzles", "welcome", "done", None):
        with pytest.raises(ValidationError):
            services.setup.skip(bad)
    with pytest.raises(ValidationError):
        services.setup.choose("maybe")


def test_the_bridge(services: Any, paths: config.Paths, clock: FixedClock) -> None:
    _no_puzzles(services)
    api = api_for(services, paths, clock, services.checkpoints._runner)
    st = api.get_setup_state()["data"]
    assert st["show"] is True and st["step"] == "welcome" and st["choice"] is None
    assert api.choose_setup("fresh")["data"]["step"] == "puzzles"
    assert api.skip_setup_step("puzzles")["error"]["code"] == "invalid_argument"
    assert api.finish_setup()["ok"] is False


def test_a_restore_from_the_wizard_comes_back_at_the_puzzle_step(
    services: Any, tmp_path: Path, clock: FixedClock
) -> None:
    """FR-15.4 from the wizard: the choice is this PC's, so it survives the swap; the restored data skips welcome."""
    seed(services)
    zip_path = backup_of(services, tmp_path, clock)
    new = new_install(tmp_path)
    migrate(new.user_db, config.MIGRATIONS_DIR / "user", clock)
    conn = sqlite3.connect(new.user_db)
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (CHOICE_KEY, '"restore"'))
    conn.commit()
    conn.close()
    files_for(new).stage_restore(zip_path)
    assert apply_staged_restore(new, clock).error is None  # type: ignore[union-attr]
    settings = dict(dump(new.user_db)["settings"])
    assert settings[CHOICE_KEY] == '"restore"'  # kept through the restore
    assert settings["mixer.filters"] == '{"seeded": true}'  # and your data came across
