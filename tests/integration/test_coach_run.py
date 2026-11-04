"""v0.10 Coach runs end to end (§10.1–10.7): your games, the Suggested mix's replace-or-banner rule, the
puzzle-history source, and another player's run kept apart (FR-10.3, Adam's v0.10 planning)."""

from __future__ import annotations

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_game_puzzles import Recorder, _game, _rows
from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.games import LibraryFilter

ANY_GAME = {"rated_only": False, "time_classes": []}


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _run(services, params: dict) -> int:  # type: ignore[no-untyped-def,type-arg]
    job = services.coach.start_run(params)
    st = services.coach._runner.wait(job, 20)
    assert st is not None and st.state == "done", (st.state, st.message) if st else None
    rid = services.coach.run_result(job)
    assert rid is not None
    return int(rid)


def _my_games(services, n: int = 3) -> list[int]:  # type: ignore[no-untyped-def]
    services.game_puzzles._engine = Recorder()
    return [_game(services, _rows()) for _ in range(n)]


def test_a_run_on_your_games_saves_a_report_and_applies_the_suggestion(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    ids = _my_games(services, 1)
    rid = _run(services, {"source": "games", **ANY_GAME})
    row, _trend = services.coach.report(rid)
    assert row.subject == "me" and row.game_ids == ids
    report = row.report
    assert report["games"] == 1
    assert [w["key"] for w in report["missed"]][:1] and report["preset"] is not None
    assert "allowed:mateIn1" in {w["key"] for w in report["allowed"]}
    sug = services.coach.suggestion()
    assert sug is not None and not sug.pending and sug.number == 1
    assert services.coach._settings.get("mixer.filters") == sug.spec  # untouched default filters: replaced
    assert services.coach.is_suggested(sug.spec)


def test_filters_you_changed_are_never_overwritten(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    mine = FilterSpec(themes=("pin",)).to_json()
    services.coach._settings.set("mixer.filters", mine)
    _run(services, {"source": "games", **ANY_GAME})
    sug = services.coach.suggestion()
    assert sug is not None and sug.pending and sug.previous == mine
    assert services.coach._settings.get("mixer.filters") == mine  # the banner waits; nothing replaced
    services.coach.dismiss_suggestion()
    assert services.coach._settings.get("mixer.filters") == mine and not services.coach.suggestion().pending
    services.coach.apply_suggestion()
    assert services.coach._settings.get("mixer.filters") == sug.spec


def test_a_new_suggestion_replaces_the_last_one_you_applied(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    _run(services, {"source": "games", **ANY_GAME})
    first = services.coach.suggestion()
    _run(services, {"source": "games", **ANY_GAME})
    second = services.coach.suggestion()
    assert second is not None and not second.pending and second.number == 2 and first is not None


def test_the_puzzle_history_source_needs_no_games(services) -> None:  # type: ignore[no-untyped-def]
    rid = _run(services, {"source": "puzzles"})
    row, _ = services.coach.report(rid)
    assert row.report["games"] == 0 and row.game_ids == []
    assert services.coach.suggestion() is None  # a puzzle-only report doesn't change the mix


def test_another_players_run_is_kept_apart(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    before = services.coach._settings.get("mixer.filters")
    rid = _run(services, {"source": "games", "player": "https://lichess.org/@/opponent_b", **ANY_GAME})
    row, _ = services.coach.report(rid)
    assert row.subject == "lichess:opponent_b" and row.subject_label.startswith("opponent_b")
    assert row.game_ids  # their games were fetched and analyzed
    assert services.games.list_games(LibraryFilter())[1] == 0  # not in My Games
    assert services.games.list_games(LibraryFilter(player="lichess:opponent_b"))[1] == len(row.game_ids)
    assert services.coach.suggestion() is None and services.coach._settings.get("mixer.filters") == before
    with services.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM custom_puzzles").fetchone()[0] == 0  # no puzzles from them


def test_bad_settings_are_refused(services) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"count": 7}, {"source": "x"}, {"color": "red"}, {"player": "  "}, {"surprise": 1},
                {"source": "puzzles", "player": "someone"}):  # fmt: skip
        with pytest.raises(ValidationError):
            services.coach.start_run(bad)
