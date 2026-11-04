"""v0.8 My puzzles source (FR-3.15, FR-10.43, FR-10.47, FR-10.49): served with no opponent move first,
never synced, strict for imported sets (any mate counts), the engine tolerance for puzzles saved from your
games (and the line continues from your move), Spaced repetition, the history filters, Both, and the
modes that support them."""

from __future__ import annotations

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from weaksquare.adapters.db.repos.custom_puzzles import CustomPuzzlesRepo
from weaksquare.adapters.db.repos.stats import StatsRepo
from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.modes.danger import MODE as DANGER
from weaksquare.core.puzzle import NewCustomPuzzle
from weaksquare.core.srs import MODE as SRS
from weaksquare.services.session import COMMIT, NAME

# Quiet for the fake engine: White's moves score ±10 cp; Rd1 hangs the rook to Nxd1 (and isn't in its top 3).
QUIET = "4k3/8/8/8/8/8/1n6/R3K3 w - - 0 1"
TWO_MATES = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1"  # Ra8# and Rb8#
MINE = FilterSpec(source="my", exclude_solved_here=False, exclude_played_on_lichess=False)


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _add(services, fen: str, line: tuple[str, ...], *, strict: bool, label: str | None = None) -> int:  # type: ignore[no-untyped-def]
    color = "white" if " w " in fen else "black"
    pid, _ = CustomPuzzlesRepo(services.db).add(
        NewCustomPuzzle(fen=fen, solution=line, player_color=color, origin="import" if strict else "manual",
                        strict=strict, set_label=label),
        "2026-01-01T00:00:00+00:00",
    )  # fmt: skip
    return pid


def _attempt(services) -> tuple:  # type: ignore[no-untyped-def]
    with services.db.session() as c:
        return c.execute(
            "SELECT puzzle_source, puzzle_id, win, sync_status, puzzle_rating FROM attempts ORDER BY id DESC LIMIT 1"
        ).fetchone()


def test_a_my_puzzle_starts_from_its_own_position_and_never_syncs(services) -> None:  # type: ignore[no-untyped-def]
    pid = _add(services, TWO_MATES, ("a1a8",), strict=True, label="Book")
    sid = services.sessions.start(MINE).session_id
    view = services.sessions.next_puzzle(sid)
    assert (view.source, view.puzzle_id, view.fen, view.opponent_move) == ("my", str(pid), TWO_MATES, "")
    assert view.opponent_sound is None and view.rating == 0 and view.player_color == "white"
    r = services.sessions.submit_move(sid, "a1a8")
    assert r.feedback.kind == "solved" and r.outcome.win and r.outcome.solution == ["a1a8"]
    assert tuple(_attempt(services)) == ("my", str(pid), 1, "local", None)  # never queued for Lichess


def test_imported_puzzles_are_strict_but_any_mate_counts(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)  # even with Stockfish, an imported puzzle has no tolerance (FR-10.49)
    _add(services, TWO_MATES, ("a1a8",), strict=True)
    sid = services.sessions.start(MINE).session_id
    services.sessions.next_puzzle(sid)
    assert services.sessions.submit_move(sid, "b1b8").outcome.win  # the other mate (§4.2)
    _add(services, QUIET, ("e1e2",), strict=True)
    sid = services.sessions.start(MINE).session_id
    view = services.sessions.next_puzzle(sid)
    while view.fen != QUIET:
        view = services.sessions.next_puzzle(sid)
    r = services.sessions.submit_move(sid, "a1a3")  # a fine move, but not the book's
    assert r.feedback.kind == "wrong" and not r.outcome.win


def _quiet_session(services, line: tuple[str, ...]):  # type: ignore[no-untyped-def]
    _add(services, QUIET, line, strict=False)
    sid = services.sessions.start(MINE).session_id
    services.sessions.next_puzzle(sid)
    return sid


def test_a_saved_game_puzzle_accepts_a_move_within_the_tolerance(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid = _quiet_session(services, ("e1e2",))
    r = services.sessions.submit_move(sid, "a1a3")  # 20 cp from the best for the fake engine
    assert r.feedback.kind == "solved" and r.outcome.win and r.outcome.solution == ["a1a3"]
    interactive = [e for e in FakeEngine.instances if e.calls]
    assert interactive and all(e.options[0] == 7 for e in interactive)  # the interactive engine only


def test_a_move_outside_the_tolerance_is_wrong(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid = _quiet_session(services, ("e1e2",))
    r = services.sessions.submit_move(sid, "a1d1")  # hangs the rook
    assert r.feedback.kind == "wrong" and not r.outcome.win


def test_without_stockfish_a_saved_puzzle_checks_its_stored_line(services) -> None:  # type: ignore[no-untyped-def]
    sid = _quiet_session(services, ("e1e2",))
    assert services.sessions.submit_move(sid, "a1a3").feedback.kind == "wrong"


def test_the_engine_continues_the_line_from_your_move(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    sid = _quiet_session(services, ("e1e2", "e8d7", "e2e3"))
    r = services.sessions.submit_move(sid, "a1a3")
    assert r.feedback.kind == "correct" and r.feedback.reply  # the engine's reply to your move
    state = services.sessions._sessions[sid].current.state
    nxt = state.puzzle.moves[state.next_index]
    assert state.puzzle.moves[1] == "a1a3" and len(state.puzzle.moves) == 4
    done = services.sessions.submit_move(sid, nxt)
    assert done.feedback.kind == "solved" and done.outcome.win


def test_my_puzzles_come_back_in_spaced_repetition(services, clock) -> None:  # type: ignore[no-untyped-def]
    pid = _add(services, TWO_MATES, ("a1a8",), strict=True)
    sid = services.sessions.start(MINE).session_id
    services.sessions.next_puzzle(sid)
    services.sessions.submit_move(sid, "a1a2")  # a miss
    assert services.sessions.srs_status().due == 0  # due tomorrow (calendar day)
    clock.advance(days=1)
    assert services.sessions.srs_status().due == 1
    srs = services.sessions.start(FilterSpec(), mode=SRS).session_id
    view = services.sessions.next_puzzle(srs)
    assert (view.source, view.puzzle_id, view.opponent_move) == ("my", str(pid), "")
    assert services.sessions.submit_move(srs, "a1a8").outcome.win


def test_history_filters_apply_to_my_puzzles(services) -> None:  # type: ignore[no-untyped-def]
    a = _add(services, TWO_MATES, ("a1a8",), strict=True)
    _add(services, QUIET, ("e1e2",), strict=True)
    count = services.sessions._puzzles.count
    assert count(FilterSpec(source="my")) == 2
    sid = services.sessions.start(MINE).session_id
    view = services.sessions.next_puzzle(sid)
    while view.puzzle_id != str(a):
        view = services.sessions.next_puzzle(sid)
    services.sessions.submit_move(sid, "a1a8")  # solved
    while services.sessions.next_puzzle(sid) is not None:  # serve the other one, then move on: a loss
        pass
    assert count(FilterSpec(source="my")) == 1  # Exclude solved here (on by default)
    assert count(FilterSpec(source="my", only_my_misses=True)) == 1  # the other one was moved on from: a loss
    assert count(FilterSpec(source="my", lengths=(2,), exclude_solved_here=False)) == 0
    assert count(FilterSpec(source="my", side="black", exclude_solved_here=False)) == 0


def test_my_puzzles_filters_by_origin_and_set(services) -> None:  # type: ignore[no-untyped-def]
    _add(services, TWO_MATES, ("a1a8",), strict=True, label="Book A")
    _add(services, QUIET, ("e1e2",), strict=True, label="Book B")
    _add(services, QUIET, ("a1a3",), strict=False)
    count = services.sessions._puzzles.count
    assert count(FilterSpec(source="my", my_sets=("Book A",))) == 1
    assert count(FilterSpec(source="my", my_origins=("import",))) == 2
    assert count(FilterSpec(source="my", my_origins=("manual",))) == 1


def test_both_mixes_lichess_and_my_puzzles(services) -> None:  # type: ignore[no-untyped-def]
    _add(services, TWO_MATES, ("a1a8",), strict=True)
    spec = FilterSpec(source="both", queue_size=None, min_popularity=None, min_plays=None)
    lichess_only = services.sessions._puzzles.count(FilterSpec(source="lichess", min_popularity=None, min_plays=None))
    assert services.sessions._puzzles.count(spec) == lichess_only + 1
    sid = services.sessions.start(spec).session_id
    sources = set()
    for _ in range(lichess_only + 1):  # nothing repeats, so yours comes up by the end at the latest
        sources.add(services.sessions.next_puzzle(sid).source)
        if sources == {"lichess", "my"}:
            break
    assert sources == {"lichess", "my"}


@pytest.mark.parametrize("mode", [NAME, DANGER])
def test_name_the_idea_and_danger_spotting_stay_lichess_only(services, mode: str) -> None:  # type: ignore[no-untyped-def]
    _add(services, TWO_MATES, ("a1a8",), strict=True)
    with pytest.raises(ValidationError, match="Standard, Commit the line and Spaced repetition"):
        services.sessions.start(MINE, mode=mode)


def test_commit_the_line_grades_my_puzzles_against_the_stored_line(services) -> None:  # type: ignore[no-untyped-def]
    _add(services, TWO_MATES, ("a1a8",), strict=False)
    sid = services.sessions.start(MINE, mode=COMMIT).session_id
    services.sessions.next_puzzle(sid)
    assert services.sessions.submit_line(sid, ["b1b8"]).outcome.win  # any mate counts where the line mates


def test_stats_see_my_puzzles_length(services) -> None:  # type: ignore[no-untyped-def]
    _add(services, TWO_MATES, ("a1a8",), strict=True)
    sid = services.sessions.start(MINE).session_id
    services.sessions.next_puzzle(sid)
    services.sessions.submit_move(sid, "a1a8")
    rows = StatsRepo(services.db).attempt_rows()
    assert rows[-1].length == 1 and rows[-1].puzzle_rating is None


def test_my_puzzle_keys_survive_a_puzzle_db_change(services) -> None:  # type: ignore[no-untyped-def]
    _add(services, TWO_MATES, ("a1a8",), strict=True)
    _add(services, QUIET, ("e1e2",), strict=True)
    sid = services.sessions.start(MINE).session_id
    first = services.sessions.next_puzzle(sid).puzzle_id
    s = services.sessions._sessions[sid]
    s.db_version -= 1  # as if puzzles.db had been swapped
    services.sessions._follow_reimport(s)
    assert -int(first) in s.served_keys  # your puzzle isn't served again
