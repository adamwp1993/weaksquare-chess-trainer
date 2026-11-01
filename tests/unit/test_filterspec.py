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


@pytest.mark.parametrize(
    "data",
    [
        {"openings": ["Italian Game"]},
        {"min_popularity": 80},
        {"min_plays": 100},
        {"exclude_solved_here": True},
        {"exclude_played_on_lichess": True},
        {"only_my_misses": True},
        {"ratios": [{"themes": ["fork"], "weight": 50}]},
        {"order": "easy_to_hard"},
        {"source": "my"},
    ],
)
def test_later_version_fields_rejected_not_ignored(data: dict) -> None:
    with pytest.raises(UnsupportedInThisVersion) as e:
        FilterSpec.from_json(data)
    assert e.value.code == "unsupported_in_this_version"
