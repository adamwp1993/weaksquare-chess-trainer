"""FR-3.10 ratios and FR-3.11 order, end to end on the fixture DB."""

from __future__ import annotations

import pytest

from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.core.queue import theme_group

OPEN = {"min_popularity": None, "min_plays": None, "exclude_solved_here": False}  # the whole fixture


def themes_of(services, puzzle_id: str) -> set[str]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return set(conn.execute("SELECT themes FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()[0].split())


def rating_of(services, puzzle_id: str) -> int:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return int(conn.execute("SELECT rating FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()[0])


def serve_all(services, spec: FilterSpec) -> list[str]:  # type: ignore[no-untyped-def]
    sid = services.sessions.start(spec).session_id
    out = []
    while (v := services.sessions.next_puzzle(sid)) is not None:
        out.append(v.puzzle_id)
    return out


def ratio_spec(*buckets: tuple[tuple[str, ...], int], **kw: object) -> FilterSpec:
    return FilterSpec(ratios=tuple(RatioBucket(t, w) for t, w in buckets), **{**OPEN, **kw})  # type: ignore[arg-type]


def test_ratio_50_30_20_in_a_session(services) -> None:  # type: ignore[no-untyped-def]
    """Disjoint groups, so each puzzle's group is unambiguous: 60 puzzles split 30/18/12 (±1)."""
    spec = ratio_spec((("middlegame",), 50), (("endgame",), 30), (("opening",), 20), queue_size=60)
    served = serve_all(services, spec)
    assert len(served) == 60 and len(set(served)) == 60
    tally = {"middlegame": 0, "endgame": 0, "opening": 0}
    for pid in served:
        (group,) = tally.keys() & themes_of(services, pid)
        tally[group] += 1
    assert abs(tally["middlegame"] - 30) <= 1 and abs(tally["endgame"] - 18) <= 1 and abs(tally["opening"] - 12) <= 1


def test_empty_group_is_left_out_and_the_others_share(services) -> None:  # type: ignore[no-untyped-def]
    spec = ratio_spec((("middlegame",), 50), (("noSuchTheme",), 50), queue_size=20)
    info = services.sessions.start(spec)
    assert info.empty_buckets == [1]
    served = serve_all(services, spec)
    assert len(served) == 20 and all("middlegame" in themes_of(services, p) for p in served)


def test_group_that_runs_dry_is_topped_up_by_the_others(services) -> None:  # type: ignore[no-untyped-def]
    """skewer has 4 puzzles; asking for 50% of 20 takes all 4, and middlegame fills the rest."""
    spec = ratio_spec((("skewer",), 50), (("middlegame",), 50), queue_size=20)
    served = serve_all(services, spec)
    assert len(served) == 20 and len(set(served)) == 20
    assert sum("skewer" in themes_of(services, p) for p in served) >= 4


def test_endless_ratio_session_never_repeats_and_ends_when_all_groups_are_dry(services) -> None:  # type: ignore[no-untyped-def]
    spec = ratio_spec((("fork",), 50), (("pin",), 50), queue_size=None)
    served = serve_all(services, spec)
    assert len(served) == len(set(served))
    expected = {pid for pid in served if themes_of(services, pid) & {"fork", "pin"}}
    assert set(served) == expected
    with services.db.session() as conn:
        pool = conn.execute(
            "SELECT COUNT(*) FROM pz.puzzles WHERE ' '||themes||' ' LIKE '% fork %' OR ' '||themes||' ' LIKE '% pin %'"
        ).fetchone()[0]
    assert len(served) == pool


def test_easy_to_hard_fixed_queue(services) -> None:  # type: ignore[no-untyped-def]
    served = serve_all(services, FilterSpec(order="easy_to_hard", queue_size=80, **OPEN))  # type: ignore[arg-type]
    ratings = [rating_of(services, p) for p in served]
    assert len(served) == 80 and ratings == sorted(ratings)


def test_easy_to_hard_endless_sorts_each_block_of_50(services) -> None:  # type: ignore[no-untyped-def]
    served = serve_all(services, FilterSpec(order="easy_to_hard", queue_size=None, **OPEN))  # type: ignore[arg-type]
    ratings = [rating_of(services, p) for p in served]
    for i in range(0, len(ratings), 50):
        assert ratings[i : i + 50] == sorted(ratings[i : i + 50])


def test_grouped_by_theme_follows_selection_order(services) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(themes=("pin", "fork"), order="by_theme", queue_size=40, **OPEN)  # type: ignore[arg-type]
    served = serve_all(services, spec)
    groups = [theme_group(tuple(themes_of(services, p)), ("pin", "fork")) for p in served]
    # all the pins, then all the forks (a puzzle with both counts as a pin, the first chosen)
    assert groups == sorted(groups, key=["pin", "fork"].index)
    assert groups[0] == "pin" and groups[-1] == "fork"


@pytest.mark.parametrize("order", ["by_theme", "easy_to_hard"])
def test_ordered_ratio_sessions(services, order: str) -> None:  # type: ignore[no-untyped-def]
    spec = ratio_spec((("middlegame",), 50), (("endgame",), 50), queue_size=30, order=order)
    served = serve_all(services, spec)
    assert len(served) == 30 and len(set(served)) == 30
    if order == "by_theme":
        first_endgame = next(i for i, p in enumerate(served) if "endgame" in themes_of(services, p))
        assert all("middlegame" in themes_of(services, p) for p in served[:first_endgame])
        assert first_endgame == 15
