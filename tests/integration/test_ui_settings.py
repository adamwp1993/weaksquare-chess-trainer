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
