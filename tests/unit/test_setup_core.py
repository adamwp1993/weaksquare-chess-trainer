"""v1.0 first-run wizard (NFR-8): when it shows and which step, decided from facts only (core/setup.py)."""

from __future__ import annotations

from dataclasses import replace

from weaksquare.core.backup import is_pc_local
from weaksquare.core.setup import DONE, ENGINE, LICHESS, PUZZLES, WELCOME, SetupFacts, shown, step

FRESH = SetupFacts(finished=False, choice=None, has_data=False, puzzles_installed=False, engine_ready=False,
                   engine_skipped=False, signed_in=False, lichess_skipped=False)  # fmt: skip


def test_a_fresh_install_starts_at_welcome() -> None:
    assert shown(FRESH) and step(FRESH) == WELCOME


def test_the_steps_follow_the_facts_in_order() -> None:
    f = replace(FRESH, choice="fresh")
    assert step(f) == PUZZLES
    f = replace(f, puzzles_installed=True)
    assert shown(f) and step(f) == ENGINE  # still shown once the puzzles are in: you've made a choice
    assert step(replace(f, engine_skipped=True)) == LICHESS
    f = replace(f, engine_ready=True)
    assert step(f) == LICHESS
    assert step(replace(f, lichess_skipped=True)) == DONE
    assert step(replace(f, signed_in=True)) == DONE


def test_an_install_with_your_data_and_its_puzzles_never_sees_it() -> None:
    old = replace(FRESH, has_data=True, puzzles_installed=True)
    assert not shown(old)


def test_a_first_launch_after_setup_imported_the_puzzles_still_shows_it() -> None:
    """setup.py imports the puzzle database, so a fresh clone starts with it: the wizard still offers Restore."""
    f = replace(FRESH, puzzles_installed=True, engine_ready=True)
    assert shown(f) and step(f) == WELCOME
    assert step(replace(f, choice="fresh")) == LICHESS


def test_finished_never_shows_again() -> None:
    assert not shown(replace(FRESH, finished=True)) and step(replace(FRESH, finished=True)) == DONE


def test_with_data_and_no_puzzles_the_welcome_is_skipped() -> None:
    """A restored backup (or an install whose puzzle database went missing) has data: straight to the puzzles."""
    assert step(replace(FRESH, has_data=True)) == PUZZLES
    assert step(replace(FRESH, has_data=True, choice="restore")) == PUZZLES


def test_setup_settings_stay_with_this_pc() -> None:
    assert is_pc_local("setup.choice") and is_pc_local("setup.finished") and is_pc_local("setup.skipped")
