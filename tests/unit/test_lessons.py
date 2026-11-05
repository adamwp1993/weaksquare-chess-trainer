"""Lesson pointers (v0.11, FR-10.59): curated links stay on the allowlist, search links are built only by
the app, and the drill sits 200 below your band."""

from __future__ import annotations

import pytest

from weaksquare.core import lessons
from weaksquare.core.preset_suggestion import validate_coach_preset


def test_every_curated_link_is_on_the_allowlist() -> None:
    assert {"lichess.org"} == lessons.ALLOWED_HOSTS
    for topic_id, links in lessons.CURATED.items():
        assert links, topic_id
        for title, url in links:
            assert lessons.is_allowed(url), url
            assert url.startswith(("https://lichess.org/practice/", "https://lichess.org/learn")), url
            assert title.startswith(("Lichess Practice: ", "Lichess Learn: "))


def test_every_curated_topic_is_in_the_catalog() -> None:
    ids = {t.id for t in lessons.catalog()}
    assert set(lessons.CURATED) <= ids


@pytest.mark.parametrize(
    "url",
    [
        "http://lichess.org/practice",
        "https://lichess.org.evil.com/practice",
        "https://evil.com/?u=https://lichess.org",
        "https://user@lichess.org/learn",
        "javascript:alert(1)",
        "https://www.youtube.com/results?search_query=x",
    ],
)
def test_other_links_are_not_allowed(url: str) -> None:
    assert not lessons.is_allowed(url)


def test_search_links_encode_the_topic_words() -> None:
    t = lessons.topic("endgame:rook")
    assert t is not None
    assert lessons.search_url("youtube", t) == "https://www.youtube.com/results?search_query=chess+rook+endgames"
    assert lessons.search_url("chesscom", t) == "https://www.chess.com/search?q=chess+rook+endgames"
    custom = lessons.search_url("custom", t, "https://example.org/find?q={q}&lang=en")
    assert custom == "https://example.org/find?q=chess+rook+endgames&lang=en"


def test_an_opening_topic_needs_a_family_from_the_run() -> None:
    assert lessons.topic("opening:Sicilian Defense") is None
    t = lessons.topic("opening:Sicilian Defense", ["Sicilian Defense"])
    assert t is not None and t.drill == ()
    url = lessons.search_url("youtube", t)
    assert url.endswith("search_query=chess+Sicilian+Defense")


def test_odd_characters_in_a_topic_are_encoded() -> None:
    t = lessons.topic("opening:Queen's Gambit & co", ["Queen's Gambit & co"])
    assert t is not None
    assert lessons.search_url("youtube", t).endswith("chess+Queen%27s+Gambit+%26+co")


@pytest.mark.parametrize(
    "bad",
    [
        "http://example.org/?q={q}",
        "https://example.org/",
        "https://example.org/?q={q}&r={q}",
        "https://exa mple.org/?q={q}",
        "https://localhost/?q={q}",
        "https://user@example.org/?q={q}",
        "ftp://example.org/{q}",
        "https://example.org/?q={q}" + "x" * 300,
    ],
)
def test_bad_custom_search_sites_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        lessons.validate_custom_template(bad)


def test_unknown_sites_are_refused() -> None:
    t = lessons.topic("theme:fork")
    assert t is not None
    with pytest.raises(ValueError):
        lessons.search_url("bing", t)
    with pytest.raises(ValueError):
        lessons.search_url("custom", t, "")


def test_the_drill_is_200_below_your_band_and_a_valid_preset() -> None:
    t = lessons.topic("theme:zugzwang")
    assert t is not None
    p = lessons.drill_preset(t, 1600)
    assert p is not None and p["rating_min"] == 1250 and p["rating_max"] == 1550 and p["mode"] == "standard"
    preset, dropped = validate_coach_preset(p)
    assert preset is not None and dropped == 0 and preset.themes == ("zugzwang",)
    assert lessons.drill_preset(lessons.Topic("concept:x", "X", "x", ()), 1500) is None
