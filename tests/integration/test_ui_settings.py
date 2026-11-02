"""UI settings persist through the bridge into user.db (never browser storage), validated per key."""

from __future__ import annotations

from tests.helpers import build_api
from weaksquare.config import Paths
from weaksquare.core.clock import FixedClock


def test_coordinates_round_trip(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    assert api.get_settings()["data"]["coordinates"] is True  # default on
    assert api.set_setting("ui.coordinates", False)["ok"]
    assert build_api(paths, clock).get_settings()["data"]["coordinates"] is False  # a fresh Api: from user.db
    with services.db.session() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key = 'ui.coordinates'").fetchone()[0] == "false"


def test_bad_values_and_unknown_keys_refused(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    assert api.set_setting("ui.coordinates", "yes")["error"]["code"] == "invalid_argument"
    assert api.set_setting("ui.nope", True)["error"]["code"] == "invalid_argument"
    assert api.set_setting("mixer.filters", {"min_popularity": 500})["error"]["code"] == "invalid_argument"
    assert api.get_settings()["data"]["coordinates"] is True


def test_color_scheme_and_sounds_round_trip(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    d = api.get_settings()["data"]
    assert d["color_scheme"] == "light"  # FR-1.12 default
    assert d["sounds"] == {"on": True, "volume": 70, "set": "sfx"}  # FR-1.13 defaults
    assert api.set_setting("ui.color_scheme", "dark")["ok"]
    assert api.set_setting("ui.sounds", {"on": False, "volume": 35, "set": "piano"})["ok"]
    again = build_api(paths, clock).get_settings()["data"]  # as after a relaunch
    assert again["color_scheme"] == "dark" and again["sounds"] == {"on": False, "volume": 35, "set": "piano"}


def test_color_scheme_and_sounds_validated(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    api = build_api(paths, clock)
    for key, value in [
        ("ui.color_scheme", "purple"),
        ("ui.color_scheme", None),
        ("ui.sounds", {"on": True, "volume": 101, "set": "sfx"}),
        ("ui.sounds", {"on": True, "volume": 50, "set": "standard"}),  # Lichess's non-free set
        ("ui.sounds", {"on": "yes", "volume": 50, "set": "sfx"}),
        ("ui.sounds", {"on": True, "volume": 50}),
    ]:
        assert api.set_setting(key, value)["error"]["code"] == "invalid_argument", (key, value)


def test_unreadable_stored_values_fall_back_to_defaults(paths: Paths, clock: FixedClock, services) -> None:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        conn.execute("""INSERT INTO settings VALUES ('ui.color_scheme', '"neon"'), ('ui.sounds', '{"on": 3}')""")
    d = build_api(paths, clock).get_settings()["data"]
    assert d["color_scheme"] == "light" and d["sounds"]["set"] == "sfx"
