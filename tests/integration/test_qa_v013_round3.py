"""QA v0.13 round 3: pressing on the fixes at e6a12e7. Real database, fake provider and engine, invented page text, no network.
A test exposing an open bug is marked xfail with its ID."""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.integration.test_opening_notes import finish
from tests.integration.test_qa_v013_notes import FAMILY, api, configure, provider  # noqa: F401
from weaksquare.core.opening_explain import REF_CLOSE, REF_OPEN, _reference
from weaksquare.core.opening_sources import MAX_PROMPT_CHARS, WikiPage, clean_page, prompt_text
from weaksquare.core.openings import validate_scope
from weaksquare.jobs.runner import CancelToken

MB = 2_000_000  # about the largest page MediaWiki allows


# ---- the cleaner on slow input ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(("a." * 50 + " ") * (MB // 101), id="the slowest words at the largest page"),
        pytest.param(("a-" * 50 + " ") * (MB // 101), id="hyphens"),
        pytest.param(("x.y/" * 24 + "abc ") * (MB // 100), id="domain and path"),
        pytest.param("=" * MB + "x", id="equals"),
        pytest.param(("=" * 50 + "x\n") * (MB // 52), id="lines of equals"),
        pytest.param("== References ==\n" * (MB // 17), id="dropped headings"),
        pytest.param("\n" * MB, id="newlines"),
        pytest.param(" " * MB + "x", id="spaces"),
        pytest.param("\x07" * MB, id="control characters"),
        pytest.param("\r\n" * (MB // 2), id="line ends"),
        pytest.param("a " * (MB // 2), id="no-break spaces"),
        pytest.param("." * MB, id="dots"),
        pytest.param("/" * MB, id="slashes"),
    ],
)
def test_the_largest_hostile_page_takes_seconds_at_most(text: str) -> None:
    """Measured at 6 s for the slowest on this machine. It grows in step with the page now, not with its square."""
    started = time.perf_counter()
    assert len(clean_page(text)) <= 8000
    assert time.perf_counter() - started < 20.0


def test_markers_nested_as_deep_as_a_prompt_allows_are_quick_and_gone() -> None:
    pages = [WikiPage(f"p{i}", "ok", 1, ("REFERE" * 600 + "NCE>>>" * 600)[:8000]) for i in range(3)]
    text, _ = prompt_text(pages)
    assert len(text) <= MAX_PROMPT_CHARS + 100
    started = time.perf_counter()
    out = _reference(text)
    assert time.perf_counter() - started < 1.0
    assert out.count(REF_CLOSE) == 1 and out.count(REF_OPEN) == 1


@pytest.mark.parametrize(
    ("line", "kept"),
    [("== Plans ==", "Plans"), ("=== A deeper idea ===", "A deeper idea"), ("= One =", "One"), ("==a=b==", "a=b")],
)
def test_ordinary_headings_read_as_before(line: str, kept: str) -> None:
    assert clean_page(line) == kept


def test_a_link_in_a_heading_is_removed_too() -> None:
    assert "evil" not in clean_page("== See https://evil.example/x now ==\nText.")


def test_a_link_in_a_dropped_section_goes_with_it() -> None:
    assert "evil" not in clean_page("Intro.\n== References ==\nhttps://evil.example/x\n=== evil.example/y ===\nAlso.")


# ---- B2: what Export and Delete cover, and how far they reach ---------------------------------------------------------------


@pytest.mark.parametrize("family", ["Catalan Opening", "Sicilian Defense", "King's Pawn Game", "Queen's Gambit"])
@pytest.mark.parametrize(("subs", "moves"), [(0, 5), (2, 10), (5, 14), (7, 18)])
def test_a_custom_setting_youve_since_left_is_covered_in_the_book(api: Any, family: str, subs: int, moves: int) -> None:  # noqa: F811
    """The guide's known limit, measured. Across all 149 families a sample of 24 Custom settings left out 0 of 118,302 moves."""
    keys = set(api._opening_notes._note_keys(family))
    for line in api._openings.lines(family, validate_scope("custom", subs, moves), False).lines:
        assert all(m.key_before in keys for m in line.moves), line.name


def test_a_line_grown_at_a_setting_youve_since_left_is_still_covered(api: Any) -> None:  # noqa: F811
    wide = validate_scope("custom", 3, 20)
    book = api._openings.lines(FAMILY, wide, False).lines
    api._openings.extend_now(book, 20, CancelToken(), lambda *_: None)
    grown = api._openings.lines(FAMILY, wide, True).lines
    api._openings.set_scope("light")
    keys = set(api._opening_notes._note_keys(FAMILY))
    for line in grown:
        for m in line.moves:
            assert m.key_before in keys, (line.name, m.san, m.source)


@pytest.mark.parametrize("family", ["King's Pawn Game", "Sicilian Defense", "Queen's Pawn Game", "Indian Defense"])
def test_working_out_what_an_opening_covers_stays_quick(api: Any, family: str) -> None:  # noqa: F811
    started = time.perf_counter()
    api._opening_notes._note_keys(family)
    assert time.perf_counter() - started < 3.0


@pytest.mark.xfail(
    reason="v0.13-B34: Delete still reaches other openings' notes, now after asking and giving the count. Narrowing "
    "it would leave notes it showed undeletable, so that is Adam's decision",
    strict=True,
)
def test_deleting_a_parent_opening_leaves_another_openings_own_notes(api: Any) -> None:  # noqa: F811
    configure(api)
    finish(api, api._opening_notes.start_prefetch(FAMILY, "standard", None, None, False))
    root = api._openings.root(FAMILY)
    lines = api._openings.lines(FAMILY, validate_scope("standard"), False).lines
    past_root = {(m.key_before, m.uci) for ln in lines for i, m in enumerate(ln.moves) if i >= len(root.moves)}
    assert past_root
    api._opening_notes.delete("King's Knight Opening")
    left = sum(api._opening_notes.note(k, u, "move") is not None for k, u in past_root)
    assert left == len(past_root), f"{left} of {len(past_root)} left"
    assert provider(api).requests  # the notes were real, and paid for


def test_the_notes_own_opening_can_still_delete_them_all(api: Any) -> None:  # noqa: F811
    configure(api)
    finish(api, api._opening_notes.start_prefetch(FAMILY, "standard", None, None, False))
    assert api._opening_notes.delete(FAMILY) > 0
    assert api._opening_notes.plan(FAMILY, "standard", None, None, False).stored == 0


# ---- B29, B30 ----------------------------------------------------------------------------------------------------------------


def test_a_cut_line_with_a_clean_finish_elsewhere_counts_only_the_finished_one(api: Any) -> None:  # noqa: F811
    from tests.integration.test_qa_v013_round2 import C4, D4, D5, E4, E5, NF3, store

    store(api, "white", [D4, D5], [E4, E5, NF3, "b8c6", C4])
    p = api._opening_practice
    s = p.start("white", mode="all", limit=2)
    s = p.play(s.session_id, D4)
    assert s.state == "line_end" and not s.line_cut and s.lines_clean == 1
    s = p.proceed(s.session_id)
    s = p.play(s.session_id, E4)
    assert s.state == "line_end" and s.line_cut and s.lines_clean == 1 and s.lines_lost == 0
    assert p.proceed(s.session_id).state == "finished"


def test_a_tolerance_check_waits_its_turn_and_isnt_called_wrong(api: Any) -> None:  # noqa: F811
    """A board analysis holds the engine. The check must wait for its own answer, never come back with none."""
    import threading

    from tests.integration.test_qa_v013_round2 import E4, E5, store

    store(api, "white", [E4, E5])
    p = api._opening_practice
    p.set_tolerance(True)
    s = p.start("white", mode="all")
    engine = api._engine
    release = threading.Event()
    busy = threading.Event()

    def hold() -> None:
        with engine._engine_lock:
            busy.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    busy.wait(5)
    seen: list[Any] = []
    player = threading.Thread(target=lambda: seen.append(p.play(s.session_id, "a2a3")))
    player.start()
    time.sleep(0.3)
    # Anything else asked for now takes a newer ticket: the check must not be dropped for it.
    engine.ticket(("openings", "panel"))
    engine.ticket(("openings", "practice"))
    release.set()
    holder.join()
    player.join(10)
    assert seen and engine._engine is not None
    assert len(engine._engine.calls) >= 1
