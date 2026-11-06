"""The opening book and repertoire against a real database and the real services (v0.13, FR-12.1–12.4, 12.13)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from weaksquare.adapters.db.repos.openings import OpeningBookRepo
from weaksquare.core.engine import EngineNotInstalled
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.openings import STARTING_KEY, OpeningDataError, parse_line, validate_scope
from weaksquare.jobs.runner import CancelToken

CUSTOM = validate_scope("custom", 0, 8)


@pytest.fixture
def book(services: Any) -> Any:
    assert services.openings.import_now() == 3865
    return services.openings


# ---- the book --------------------------------------------------------------------------------------


def test_the_book_needs_importing_once(services: Any) -> None:
    assert services.openings.status().ready is False
    services.openings.import_now()
    assert services.openings.status().ready is True
    assert services.openings.status().lines == 3865


def test_a_failed_import_keeps_the_old_book(book: Any, services: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import weaksquare.services.openings as module

    def bad(*_a: Any) -> Any:
        raise OpeningDataError("damaged")

    monkeypatch.setattr(module, "parse_line", bad)
    with pytest.raises(OpeningDataError):
        book.import_now()
    assert OpeningBookRepo(services.db).count() == 3865


def test_lines_survive_being_stored(book: Any, services: Any) -> None:
    stored = {ln.name: ln for ln in OpeningBookRepo(services.db).lines()}
    fresh = parse_line("C50", "Italian Game", "1. e4 e5 2. Nf3 Nc6 3. Bc4")
    assert stored["Italian Game"].moves == fresh.moves
    assert stored["Italian Game"].sans == fresh.sans
    assert stored["Italian Game"].keys == fresh.keys


def test_search_by_name_and_eco(book: Any) -> None:
    assert [f.name for f in book.families("italian")] == ["Italian Game"]
    assert all(f.eco.startswith("B1") for f in book.families("b1"))
    assert book.families("no such opening") == []


def test_a_position_finds_its_name_whatever_the_move_order(book: Any) -> None:
    a = parse_line("X", "x", "1. Nf3 Nc6 2. e4 e5 3. Bc4")
    named = book.name_of(a.final_key)
    assert named is not None and named.family == "Italian Game"


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("Italian Game: Giuoco Piano", "Italian Game"),
        ("italian game", "Italian Game"),
        ("Not An Opening", None),
        ("", None),
    ],
)
def test_a_games_opening_name_matches_a_family(book: Any, name: str, family: str | None) -> None:
    assert book.match_family(name) == family


# ---- scope ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("preset", "subs", "moves"), [("light", 1, 8), ("standard", 3, 12), ("deep", 6, 16)])
def test_each_preset_gives_the_right_counts(book: Any, preset: str, subs: int, moves: int) -> None:
    scope = validate_scope(preset)
    assert (scope.sub_lines, scope.max_moves) == (subs, moves)
    lines = book.lines("Italian Game", scope, extend=False).lines
    assert len(lines) == subs + 1
    assert all(len(ln.moves) <= moves * 2 for ln in lines)


def test_custom_is_clamped_to_its_limits() -> None:
    assert validate_scope("custom", 99, 99) == validate_scope("custom", 10, 20)
    low = validate_scope("custom", -3, 1)
    assert (low.sub_lines, low.max_moves) == (0, 4)


@pytest.mark.parametrize("args", [("nonsense", None, None), ("custom", "3", 12), ("custom", 3, True)])
def test_a_bad_scope_is_refused(args: tuple[Any, Any, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_scope(*args)


def test_scope_and_extend_settings_persist(book: Any) -> None:
    assert book.scope().preset == "standard" and book.extend_setting() is True
    book.set_scope("deep")
    book.set_extend(False)
    assert book.scope().preset == "deep" and book.extend_setting() is False


# ---- extending past the book (FR-12.13) ---------------------------------------------------------------


@pytest.fixture
def engine_ready(services: Any, paths: Any) -> Any:
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    return services


def test_stop_at_the_books_end_uses_only_book_moves(book: Any, engine_ready: Any) -> None:
    view = book.lines("Italian Game", CUSTOM, extend=False)
    assert view.extend is False and view.pending == 0
    assert {m.source for ln in view.lines for m in ln.moves} == {"book"}


def test_reading_a_line_never_runs_the_engine(book: Any, engine_ready: Any) -> None:
    view = book.lines("Polish Opening", validate_scope("custom", 0, 12), extend=True)
    assert view.pending == 1
    assert sum(len(e.calls) for e in FakeEngine.instances) == 0


def test_the_job_fills_the_store_and_lines_then_grow_with_labels(book: Any, engine_ready: Any) -> None:
    scope = validate_scope("custom", 0, 12)
    before = book.lines("Polish Opening", scope, extend=True).lines[0]
    assert len(before.moves) < 24
    n = book.extend_now(book.lines("Polish Opening", scope, extend=False).lines, 12, CancelToken(), lambda _f, _m: None)
    assert n > 0
    after = book.lines("Polish Opening", scope, extend=True)
    line = after.lines[0]
    assert after.pending == 0 and len(line.moves) > len(before.moves)  # the fake engine mates, ending the line
    assert line.moves[-1].source == "engine"
    assert [m.source for m in line.moves[: len(before.moves)]] == [m.source for m in before.moves]


def test_extending_twice_costs_nothing_the_second_time(book: Any, engine_ready: Any) -> None:
    scope = validate_scope("custom", 0, 12)
    lines = book.lines("Polish Opening", scope, extend=False).lines
    book.extend_now(lines, 12, CancelToken(), lambda _f, _m: None)
    assert book.extend_now(lines, 12, CancelToken(), lambda _f, _m: None) == 0


def test_a_cancelled_extension_keeps_finished_positions(book: Any, engine_ready: Any) -> None:
    from weaksquare.jobs.runner import JobCancelled

    scope = validate_scope("custom", 0, 12)
    lines = book.lines("Polish Opening", scope, extend=False).lines
    token = CancelToken()
    seen = [0]

    def progress(_f: Any, _m: str) -> None:
        seen[0] += 1
        if seen[0] == 2:
            token.cancel()

    with pytest.raises(JobCancelled):
        book.extend_now(lines, 12, token, progress)
    assert len(book.lines("Polish Opening", scope, extend=True).lines[0].moves) > len(lines[0].moves)


def test_extending_without_an_engine_says_so(book: Any) -> None:
    with pytest.raises(EngineNotInstalled):
        book.start_extend("Italian Game", CUSTOM)
    view = book.lines("Italian Game", validate_scope("custom", 0, 12), extend=True)
    assert view.engine_ready is False and {m.source for ln in view.lines for m in ln.moves} == {"book"}


# ---- the Learn board's engine --------------------------------------------------------------------------

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_analyze_stores_its_result_and_reuses_it_for_either_side(book: Any, engine_ready: Any) -> None:
    first = book.analyze(START, "panel", "white")
    calls = sum(len(e.calls) for e in FakeEngine.instances)
    assert first.lines and calls == 1
    second = book.analyze(START, "panel", "black")
    assert sum(len(e.calls) for e in FakeEngine.instances) == calls
    assert second.lines[0].pv == first.lines[0].pv


@pytest.mark.parametrize("fen", ["not a fen", "8/8/8/8/8/8/8/8 w - - 0 1", ""])
def test_an_illegal_position_never_reaches_the_engine(book: Any, engine_ready: Any, fen: str) -> None:
    with pytest.raises(ValidationError):
        book.analyze(fen, "panel", "white")
    assert sum(len(e.calls) for e in FakeEngine.instances) == 0


# ---- the repertoire (FR-12.4) ------------------------------------------------------------------------


def test_adding_lines_stores_them_for_one_color(book: Any, services: Any) -> None:
    book.set_scope("custom", 1, 8)
    book.set_extend(False)
    result = services.repertoire.add_lines("white", "Italian Game", [0])
    assert result.added > 0 and result.kept == 0
    view = services.repertoire.view("white")
    assert view.rows[0].edge.san == "e4" and view.rows[0].edge.source == "book"
    assert [o.name for o in view.openings] == ["Italian Game"]
    assert services.repertoire.view("black").rows == ()


def test_adding_again_keeps_what_you_have(book: Any, services: Any) -> None:
    book.set_scope("custom", 1, 8)
    book.set_extend(False)
    services.repertoire.add_lines("white", "Italian Game", [0])
    again = services.repertoire.add_lines("white", "Italian Game", [0])
    assert again.added == 0 and again.kept > 0
    assert len(services.repertoire.view("white").openings) == 1


def test_a_stored_move_keeps_its_source_when_a_line_adds_it_again(book: Any, services: Any) -> None:
    from weaksquare.adapters.db.repos.openings import RepertoireRepo
    from weaksquare.core.repertoire import NewMove

    RepertoireRepo(services.db).add_moves(
        "white", [NewMove(STARTING_KEY, "e2e4", "e4", "you")], "2026-11-06T00:00:00+00:00"
    )
    book.set_scope("custom", 0, 4)
    book.set_extend(False)
    services.repertoire.add_lines("white", "Italian Game", [0])
    assert services.repertoire.view("white").rows[0].edge.source == "you"


@pytest.mark.parametrize("indices", [[], [99], [-1], ["0"], [True], "0"])
def test_a_bad_line_choice_is_refused(book: Any, services: Any, indices: Any) -> None:
    with pytest.raises(ValidationError):
        services.repertoire.add_lines("white", "Italian Game", indices)


def test_removal_previews_then_deletes_only_what_is_unreachable(book: Any, services: Any) -> None:
    book.set_scope("custom", 2, 8)
    book.set_extend(False)
    services.repertoire.add_lines("white", "Italian Game", [0, 1, 2])
    rows = services.repertoire.view("white").rows
    last = rows[-1].edge
    preview = services.repertoire.removal_preview("white", last.position_key, last.move_uci)
    assert last in preview
    before = len(rows)
    assert services.repertoire.remove("white", last.position_key, last.move_uci) == len(preview)
    assert len(services.repertoire.view("white").rows) == before - len(preview)


def test_removing_a_missing_move_says_so(book: Any, services: Any) -> None:
    with pytest.raises(NotFoundError):
        services.repertoire.remove("white", STARTING_KEY, "e2e4")


def test_main_and_order_can_be_changed(book: Any, services: Any) -> None:
    book.set_scope("custom", 3, 8)
    book.set_extend(False)
    services.repertoire.add_lines("black", "Italian Game", [0, 1, 2, 3])
    rows = services.repertoire.view("black").rows
    edges = services.repertoire.edges("black")
    by_key: dict[str, list[Any]] = {}
    for e in edges:
        by_key.setdefault(e.position_key, []).append(e)
    key, moves = next((k, v) for k, v in by_key.items() if len(v) > 1)
    assert sum(1 for m in moves if m.is_main) == 1 and rows
    other = next(m for m in moves if not m.is_main)
    services.repertoire.set_main("black", key, other.move_uci)
    fresh = [e for e in services.repertoire.edges("black") if e.position_key == key]
    assert [e.move_uci for e in fresh if e.is_main] == [other.move_uci]
    order = [e.move_uci for e in fresh]
    services.repertoire.move("black", key, order[1], "up")
    assert next(e.move_uci for e in services.repertoire.edges("black") if e.position_key == key) == order[1]
    with pytest.raises(NotFoundError):
        services.repertoire.set_main("black", key, "a1a1")


# ---- the explorer in lines (FR-12.2, 12.13) --------------------------------------------------------------


def _store_popular(services: Any, key: str, moves: dict[str, int]) -> None:
    from weaksquare.adapters.db.repos.openings import ExplorerCacheRepo

    params = services.opening_sources.explorer_settings().params
    body = {"moves": [{"uci": u, "white": n, "draws": 0, "black": 0} for u, n in moves.items()]}
    ExplorerCacheRepo(services.db).put(key, params, body, "2026-01-01T12:00:00+00:00")


def test_stored_popularity_ranks_the_lines(book: Any, services: Any) -> None:
    root = book.root("Italian Game")
    assert book.lines("Italian Game", CUSTOM, extend=False).lines[0].moves[5].san == "Bc5"
    _store_popular(services, root.final_key, {"g8f6": 5000, "f8c5": 10})
    assert book.lines("Italian Game", CUSTOM, extend=False).lines[0].moves[5].san == "Nf6"


def test_a_line_continues_with_a_popular_move_labelled_as_such(book: Any, services: Any, engine_ready: Any) -> None:
    from weaksquare.core.openings import final_key_of

    scope = validate_scope("custom", 0, 12)
    book.extend_now(book.lines("Polish Opening", scope, extend=False).lines, 12, CancelToken(), lambda _f, _m: None)
    line = book.lines("Polish Opening", scope, extend=False).lines[0]
    key = final_key_of(line.moves)
    from weaksquare.core.openings import board_of

    legal = next(iter(board_of(key).legal_moves)).uci()
    _store_popular(services, key, {legal: 500})
    grown = book.lines("Polish Opening", scope, extend=True).lines[0]
    assert grown.moves[len(line.moves)].uci == legal
    assert grown.moves[len(line.moves)].source == "explorer"


def test_too_few_games_is_not_a_popular_move(book: Any, services: Any, engine_ready: Any) -> None:
    from weaksquare.core.openings import board_of, final_key_of

    scope = validate_scope("custom", 0, 12)
    line = book.lines("Polish Opening", scope, extend=False).lines[0]
    key = final_key_of(line.moves)
    legal = next(iter(board_of(key).legal_moves)).uci()
    _store_popular(services, key, {legal: 3})
    grown = book.lines("Polish Opening", scope, extend=True).lines[0]
    assert all(m.source != "explorer" for m in grown.moves)


def test_a_broken_stored_answer_cant_put_an_illegal_move_in_a_line(book: Any, services: Any) -> None:
    from weaksquare.core.openings import final_key_of

    scope = validate_scope("custom", 0, 12)
    line = book.lines("Polish Opening", scope, extend=False).lines[0]
    key = final_key_of(line.moves)
    _store_popular(services, key, {"a1a8": 5000, "nonsense": 5000})
    assert book.lines("Polish Opening", scope, extend=True).lines[0].moves == line.moves
