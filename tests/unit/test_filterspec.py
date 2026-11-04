"""ARCHITECTURE §3 decision 5: FilterSpec JSON round-trip and validation."""

from __future__ import annotations

import pytest

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec, UnsupportedInThisVersion


def test_defaults_are_all_puzzles() -> None:
    spec = FilterSpec()
    assert spec.all_themes and spec.all_lengths and spec.side == "either" and spec.queue_size == 20


def test_json_round_trip() -> None:
    spec = FilterSpec(themes=("fork", "long"), match="all", exclude_themes=("mate",), rating_min=1200,
                      rating_max=1600, lengths=(2, 3), side="black", queue_size=None)  # fmt: skip
    data = spec.to_json()
    assert data["themes"] == ["fork", "long"] and data["queue_size"] is None
    assert FilterSpec.from_json(data) == spec


def test_lengths_all_selected_means_all() -> None:
    assert FilterSpec(lengths=(1, 2, 3, 4)).all_lengths


@pytest.mark.parametrize(
    "data",
    [
        "not a dict",
        {"themes": "fork"},
        {"themes": ["fork", "<script>"]},
        {"match": "some"},
        {"rating_min": 1600, "rating_max": 1200},
        {"rating_min": -5},
        {"rating_min": "1200"},
        {"lengths": [0]},
        {"lengths": [2, 2]},
        {"lengths": [True]},
        {"side": "red"},
        {"queue_size": 0},
        {"queue_size": 501},
        {"surprise": 1},
    ],
)
def test_invalid_input_rejected(data: object) -> None:
    with pytest.raises(ValidationError):
        FilterSpec.from_json(data)


def test_v08_puzzle_source_and_my_puzzles_filters() -> None:
    spec = FilterSpec.from_json(
        {"source": "both", "my_origins": ["manual"], "my_sets": ["Book"], "my_kinds": ["missed"],
         "my_phases": ["endgame"], "my_time_classes": ["rapid", "blitz"]}
    )  # fmt: skip
    assert spec.source == "both" and spec.my_time_classes == ("rapid", "blitz")
    assert FilterSpec.from_json(spec.to_json()) == spec
    old = {k: v for k, v in FilterSpec().to_json().items() if not k.startswith("my_") and k != "source"}
    assert FilterSpec.from_json(old).source == "lichess"  # a preset saved before v0.8 loads as Lichess DB


@pytest.mark.parametrize(
    "data, words",
    [
        ({"source": "mine"}, "source must be"),
        ({"my_origins": ["coach"]}, "my_origins"),  # v0.10
        ({"my_kinds": ["missed", "missed"]}, "my_kinds"),
        ({"my_sets": ["x" * 61]}, "set label"),
        ({"source": "my", "order": "easy_to_hard"}, "order is random"),
        (
            {"source": "both", "ratios": [{"themes": ["fork"], "weight": 50}, {"themes": ["pin"], "weight": 50}]},
            "Ratios",
        ),
    ],
)
def test_my_puzzles_rules(data: dict, words: str) -> None:
    with pytest.raises(ValidationError, match=words):
        FilterSpec.from_json(data)


def test_the_later_version_error_type_still_exists() -> None:
    assert UnsupportedInThisVersion("x").code == "unsupported_in_this_version"


# ---- v0.2 -------------------------------------------------------------------------------------


def test_v02_defaults() -> None:
    """Decided at v0.2 planning: a light quality filter and Exclude solved on, all adjustable."""
    spec = FilterSpec()
    assert spec.min_popularity == 50 and spec.min_plays == 100
    assert spec.exclude_solved_here and not spec.only_my_misses
    assert FilterSpec.from_json({}) == spec


@pytest.mark.parametrize(
    "data",
    [
        {"openings": ["Italian_Game", "Sicilian_Defense_Najdorf_Variation", "Rapport-Jobava_System"]},
        {"min_popularity": -100},
        {"min_popularity": 100},
        {"min_popularity": None, "min_plays": None},
        {"min_plays": 0},
        {"exclude_solved_here": False},
        {"only_my_misses": True},
        {"order": "easy_to_hard"},
        {"order": "by_theme"},
        {"ratios": [{"themes": ["fork"], "weight": 50}, {"themes": ["pin", "skewer"], "weight": 30},
                    {"themes": ["oneMove"], "weight": 20}]},
    ],
)  # fmt: skip
def test_v02_fields_accepted_and_round_trip(data: dict) -> None:
    spec = FilterSpec.from_json(data)
    assert FilterSpec.from_json(spec.to_json()) == spec


@pytest.mark.parametrize(
    "data",
    [
        {"openings": ["Italian Game"]},  # spaces: not a Lichess tag
        {"openings": ["x' OR 1=1 --"]},
        {"openings": "Italian_Game"},
        {"min_popularity": 101},
        {"min_popularity": -101},
        {"min_plays": -1},
        {"min_plays": True},
        {"order": "sideways"},
        {"ratios": [{"themes": ["fork"], "weight": 100}]},  # one bucket isn't a ratio
        {"ratios": [{"themes": ["fork"], "weight": 50}, {"themes": ["pin"], "weight": 40}]},  # 90%
        {"ratios": [{"themes": [], "weight": 50}, {"themes": ["pin"], "weight": 50}]},
        {"ratios": [{"themes": ["nope!"], "weight": 50}, {"themes": ["pin"], "weight": 50}]},
        {"ratios": [{"themes": ["fork"], "weight": 0}, {"themes": ["pin"], "weight": 100}]},
        {"ratios": [{"themes": ["fork"], "weight": True}, {"themes": ["pin"], "weight": 99}]},
        {"themes": ["fork"], "ratios": [{"themes": ["fork"], "weight": 50}, {"themes": ["pin"], "weight": 50}]},
    ],
)
def test_v02_invalid_input_rejected(data: object) -> None:
    with pytest.raises(ValidationError):
        FilterSpec.from_json(data)


def test_only_my_misses_overrides_exclude_solved() -> None:
    assert FilterSpec().excludes_solved
    assert not FilterSpec(only_my_misses=True).excludes_solved
    assert not FilterSpec(exclude_solved_here=False).excludes_solved


def test_bucket_pool_uses_the_bucket_themes() -> None:
    spec = FilterSpec.from_json(
        {"match": "all", "rating_min": 1200, "ratios": [{"themes": ["fork"], "weight": 60},
                                                        {"themes": ["pin", "skewer"], "weight": 40}]}
    )  # fmt: skip
    b = spec.bucket(1)
    assert b.themes == ("pin", "skewer") and b.match == "any" and b.ratios == () and b.rating_min == 1200


def test_v01_saved_filters_get_defaults_once() -> None:
    from weaksquare.core.filters import upgrade_saved

    v01 = {**FilterSpec().to_json(), "min_popularity": None, "min_plays": None, "exclude_solved_here": False}
    up = upgrade_saved(v01, 1)
    assert (up["min_popularity"], up["min_plays"], up["exclude_solved_here"]) == (50, 100, True)
    # Already at v0.2: your choices (thresholds off, solved included) are kept.
    assert upgrade_saved(v01, 2) == v01
    assert upgrade_saved({**v01, "min_plays": 500}, 1)["min_plays"] == 500
