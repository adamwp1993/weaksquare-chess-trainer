"""FR-3.13 presets (Done when: preset round-trip), plus the opening catalog and bucket counts."""

from __future__ import annotations

import pytest

from tests.helpers import build_api
from weaksquare.config import Paths
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.services.mixer import opening_name

FULL = FilterSpec(
    themes=(),
    exclude_themes=("castling",),
    rating_min=1200,
    rating_max=1800,
    lengths=(2, 3),
    side="black",
    order="by_theme",
    queue_size=None,
    openings=("Sicilian_Defense", "Italian_Game_Evans_Gambit"),
    min_popularity=70,
    min_plays=None,
    exclude_solved_here=False,
    only_my_misses=True,
    ratios=(RatioBucket(("fork",), 50), RatioBucket(("pin", "skewer"), 30), RatioBucket(("oneMove",), 20)),
)


def test_round_trip_every_field(services) -> None:  # type: ignore[no-untyped-def]
    services.presets.save("Combo night", FULL)
    (p,) = services.presets.list()
    assert p.name == "Combo night" and p.error is None
    assert p.spec == FULL


def test_names_are_unique_ignoring_case_and_overwrite_replaces(services) -> None:  # type: ignore[no-untyped-def]
    services.presets.save("Combo night", FilterSpec())
    with pytest.raises(ConflictError):
        services.presets.save("combo NIGHT", FULL)
    services.presets.save("combo NIGHT", FULL, overwrite=True)
    (p,) = services.presets.list()
    assert p.name == "combo NIGHT" and p.spec == FULL


def test_rename_and_delete(services) -> None:  # type: ignore[no-untyped-def]
    services.presets.save("A", FilterSpec())
    services.presets.save("B", FULL)
    with pytest.raises(ConflictError):
        services.presets.rename("A", "b")
    services.presets.rename("A", "a")  # a case-only change is fine
    services.presets.rename("a", "Endgames")
    assert [p.name for p in services.presets.list()] == ["B", "Endgames"]
    services.presets.delete("endgames")
    assert [p.name for p in services.presets.list()] == ["B"]
    with pytest.raises(NotFoundError):
        services.presets.delete("Endgames")
    with pytest.raises(NotFoundError):
        services.presets.rename("nope", "x")


@pytest.mark.parametrize("name", ["", "   ", "x" * 61, "tab\there", 42])
def test_bad_names_rejected(services, name: object) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.presets.save(name, FilterSpec())


def test_name_whitespace_is_tidied(services) -> None:  # type: ignore[no-untyped-def]
    services.presets.save("  Combo   night ", FilterSpec())
    assert [p.name for p in services.presets.list()] == ["Combo night"]


def test_unusable_stored_preset_is_reported_and_left_alone(services) -> None:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        conn.execute(
            "INSERT INTO presets VALUES ('From v0.8', 'from v0.8', '{\"source\": \"my\"}', 't', 't'),"
            " ('Broken', 'broken', 'not json', 't', 't')"
        )
    by_name = {p.name: p for p in services.presets.list()}
    assert by_name["From v0.8"].spec is None and "can't be used" in (by_name["From v0.8"].error or "")
    assert by_name["Broken"].spec is None and by_name["Broken"].error
    with services.db.session() as conn:
        assert conn.execute("SELECT filters_json FROM presets WHERE name = 'From v0.8'").fetchone()[0] == (
            '{"source": "my"}'
        )


def test_bridge_round_trip(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    saved = api.save_preset("Combo night", FULL.to_json())
    assert saved["ok"], saved
    listed = api.list_presets()["data"]
    assert listed[0]["name"] == "Combo night" and FilterSpec.from_json(listed[0]["spec"]) == FULL
    again = api.save_preset("Combo night", FULL.to_json())
    assert again["error"]["code"] == "conflict"
    assert api.save_preset("Bad", {"ratios": [{"themes": ["fork"], "weight": 100}]})["error"]["code"] == (
        "invalid_argument"
    )
    assert api.rename_preset("Combo night", "Tactics")["ok"]
    assert api.delete_preset("Tactics")["ok"]
    assert api.list_presets()["data"] == []


def test_opening_catalog(services) -> None:  # type: ignore[no-untyped-def]
    catalog = services.mixer.opening_catalog()
    names = [f.family.name for f in catalog]
    assert names == sorted(names, key=str.casefold) and "Sicilian Defense" in names
    sicilian = next(f for f in catalog if f.family.tag == "Sicilian_Defense")
    assert sicilian.family.count >= sum(v.count for v in sicilian.variations) > 0
    assert all(not v.name.startswith("Sicilian") for v in sicilian.variations)


def test_opening_name() -> None:
    assert opening_name("Sicilian_Defense") == "Sicilian Defense"
    assert opening_name("Sicilian_Defense_Najdorf_Variation", "Sicilian_Defense") == "Najdorf Variation"
    assert opening_name("Rapport-Jobava_System") == "Rapport-Jobava System"


def test_bucket_counts(services) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(ratios=(RatioBucket(("fork",), 50), RatioBucket(("noSuchTheme",), 50)))
    fork, nothing = services.mixer.bucket_counts(spec)
    assert fork == services.mixer.count(FilterSpec(themes=("fork",))) > 0 and nothing == 0
