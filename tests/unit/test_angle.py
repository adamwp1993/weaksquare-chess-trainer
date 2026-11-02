"""FR-6.13 / FR-6.14 / FR-6.15 and Adam's v0.3 planning decision 2: the angle reported to Lichess."""

from __future__ import annotations

import pytest

from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.core.scoring import MIX, angle_for, length_theme, selected_themes

FORK_PUZZLE = ("fork", "middlegame", "short", "advantage")


def test_mix_only_when_themes_and_move_count_are_all() -> None:
    assert angle_for(FilterSpec(), FORK_PUZZLE, 2) == MIX
    # Selecting every length is the same as All.
    assert angle_for(FilterSpec(lengths=(1, 2, 3, 4)), FORK_PUZZLE, 2) == MIX


@pytest.mark.parametrize(
    "spec",
    [
        FilterSpec(exclude_themes=("mateIn1",)),
        FilterSpec(openings=("Italian_Game",)),
        FilterSpec(rating_min=1500, rating_max=1800),
        FilterSpec(side="black"),
        FilterSpec(min_popularity=90, min_plays=1000),
        FilterSpec(exclude_solved_here=False, only_my_misses=True),
        FilterSpec(order="easy_to_hard", queue_size=None),
    ],
)
def test_other_filters_keep_mix(spec: FilterSpec) -> None:
    assert angle_for(spec, FORK_PUZZLE, 2) == MIX


def test_one_selected_theme() -> None:
    assert angle_for(FilterSpec(themes=("fork",)), FORK_PUZZLE, 2) == "fork"


def test_any_mode_reports_the_theme_this_puzzle_matched() -> None:
    spec = FilterSpec(themes=("pin", "fork", "skewer"), match="any")
    assert angle_for(spec, FORK_PUZZLE, 2) == "fork"
    assert angle_for(spec, ("pin", "endgame", "long"), 3) == "pin"


def test_several_matches_use_selection_order_within_a_tier() -> None:
    spec = FilterSpec(themes=("pin", "fork"), match="all")
    assert angle_for(spec, ("fork", "pin", "middlegame", "long"), 3) == "pin"
    spec2 = FilterSpec(themes=("fork", "pin"), match="all")
    assert angle_for(spec2, ("fork", "pin", "middlegame", "long"), 3) == "fork"


def test_motifs_before_phases_and_goals() -> None:
    for chosen in (("middlegame", "fork"), ("advantage", "fork"), ("master", "fork")):
        spec = FilterSpec(themes=chosen, match="all")
        assert angle_for(spec, (*FORK_PUZZLE, "master"), 2) == "fork"


def test_mates_and_special_moves_rank_as_motifs() -> None:
    spec = FilterSpec(themes=("endgame", "mateIn2"), match="all")
    assert angle_for(spec, ("endgame", "mateIn2", "mate", "short"), 2) == "mateIn2"
    spec = FilterSpec(themes=("endgame", "promotion"), match="all")
    assert angle_for(spec, ("endgame", "promotion", "long"), 3) == "promotion"


def test_phase_or_goal_when_no_motif_was_selected() -> None:
    assert angle_for(FilterSpec(themes=("endgame",)), ("endgame", "fork", "long"), 3) == "endgame"
    assert angle_for(FilterSpec(themes=("crushing",)), ("crushing", "fork"), 2) == "crushing"


def test_selected_length_theme_ranks_last() -> None:
    spec = FilterSpec(themes=("short", "endgame"), match="all")
    assert angle_for(spec, ("short", "endgame", "fork"), 2) == "endgame"


@pytest.mark.parametrize(
    ("length", "theme"), [(1, "oneMove"), (2, "short"), (3, "long"), (4, "veryLong"), (7, "veryLong")]
)
def test_only_the_move_count_narrowed_reports_the_length_theme(length: int, theme: str) -> None:
    narrowed = FilterSpec(lengths=(min(length, 4),))
    assert angle_for(narrowed, ("fork", "middlegame"), length) == theme
    assert length_theme(length) == theme


def test_theme_selection_wins_over_a_narrowed_move_count() -> None:
    spec = FilterSpec(themes=("fork",), lengths=(2,))
    assert angle_for(spec, FORK_PUZZLE, 2) == "fork"


def test_ratios_use_every_groups_themes_in_group_order() -> None:
    spec = FilterSpec(
        ratios=(
            RatioBucket(("fork",), 50),
            RatioBucket(("capturingDefender", "pin"), 30),
            RatioBucket(("oneMove",), 20),
        )
    )
    assert selected_themes(spec) == ("fork", "capturingDefender", "pin", "oneMove")
    assert angle_for(spec, FORK_PUZZLE, 2) == "fork"
    assert angle_for(spec, ("pin", "capturingDefender", "long"), 3) == "capturingDefender"
    assert angle_for(spec, ("oneMove", "mateIn1", "mate"), 1) == "oneMove"
    # Ratios are never mix, even though spec.themes is empty.
    assert angle_for(spec, ("fork", "pin"), 2) != MIX


def test_no_selected_theme_matched_falls_back_to_length() -> None:
    assert angle_for(FilterSpec(themes=("skewer",)), ("fork", "long"), 3) == "long"
