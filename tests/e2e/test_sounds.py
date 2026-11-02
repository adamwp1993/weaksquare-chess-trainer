"""FR-1.13 against the mock, with a stubbed audio player: sounds play when on (including the
opponent's first move), never when off (nothing is even created), the volume and set apply, and the
setting is saved through the bridge.

The mock's first puzzle is DtKOy (you play black): a1b1 (a quiet rook move), then Nxc3, Rxb5, Nxd1.
"""

from __future__ import annotations

import json

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_qa_v01_ui import your_turn

pytestmark = pytest.mark.e2e

STUB = """
window.__played = [];
window.__audioCreated = 0;
const RealAudio = window.Audio;
window.Audio = function (src) { window.__audioCreated++; return new RealAudio(src); };
HTMLMediaElement.prototype.play = function () {
  window.__played.push({ src: new URL(this.src).pathname, volume: this.volume });
  return Promise.resolve();
};
"""


def open_app(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.add_init_script(STUB)
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()


def played(page) -> list[dict]:  # type: ignore[no-untyped-def]
    return page.evaluate("window.__played")


def files(page) -> list[str]:  # type: ignore[no-untyped-def]
    return [p["src"] for p in played(page)]


def test_sounds_play_for_every_move_and_the_result(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    assert files(page) == ["/sounds/sfx/Move.ogg"]  # the opponent's first move, before any click
    assert played(page)[0]["volume"] == pytest.approx(0.7)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(600)  # the reply plays
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    page.wait_for_timeout(500)
    assert files(page) == [
        "/sounds/sfx/Move.ogg",
        "/sounds/sfx/Capture.ogg",  # Nxc3
        "/sounds/sfx/Capture.ogg",  # Rxb5 (the reply)
        "/sounds/sfx/Capture.ogg",  # Nxd1
        "/sounds/sfx/GenericNotify.ogg",  # solved (sfx's own Victory was too loud: Adam, v0.2 manual test)
    ]


def test_wrong_move_plays_the_move_then_failed(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "g7g6", "black")  # legal, wrong
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.wait_for_timeout(500)
    assert files(page)[1:] == ["/sounds/sfx/Move.ogg", "/sounds/sfx/Defeat.ogg"]


def test_off_is_silent_and_loads_nothing(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?sounds=off")
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(600)
    assert played(page) == [] and page.evaluate("window.__audioCreated") == 0


def open_settings(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Settings…").click()
    page.get_by_test_id("settings").wait_for()


def saved_sounds(page) -> dict:  # type: ignore[no-untyped-def]
    calls = page.evaluate("window.__mockApi.calls")
    last = [c for c in calls if c.startswith("setting:ui.sounds=")][-1]
    return json.loads(last.split("=", 1)[1])


def test_set_volume_and_off_apply_at_once_and_are_saved(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    open_settings(page)
    page.get_by_test_id("sound-set").click()
    page.get_by_role("option", name="Piano").click()
    assert saved_sounds(page) == {"on": True, "volume": 70, "set": "piano"}
    page.get_by_test_id("volume").focus()
    for _ in range(4):
        page.keyboard.press("ArrowLeft")  # 70 → 50
    page.keyboard.up("ArrowLeft")
    page.wait_for_timeout(200)
    page.get_by_test_id("sound-test").click()
    last = played(page)[-1]
    assert last["src"] == "/sounds/piano/Capture.ogg"
    assert last["volume"] == pytest.approx(saved_sounds(page)["volume"] / 100)
    page.get_by_test_id("sounds-switch").click()
    assert saved_sounds(page)["on"] is False
    page.keyboard.press("Escape")
    count = len(played(page))
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    page.wait_for_timeout(300)
    assert len(played(page)) == count  # off: silent
