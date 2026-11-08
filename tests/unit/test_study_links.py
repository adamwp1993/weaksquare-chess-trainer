"""FR-13.4, 13.5, 13.5a (v0.14): what counts as a Lichess study address, and which pages the Lichess window may show."""

from __future__ import annotations

import pytest

from weaksquare.core.study_links import StudyRef, is_browser_safe, is_lichess_page, parse_study_ref


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://lichess.org/study/ZCPaIb70", StudyRef("ZCPaIb70")),
        ("https://lichess.org/study/ZCPaIb70/", StudyRef("ZCPaIb70")),
        ("https://lichess.org/study/nq1GGbNO/rWqJitDx", StudyRef("nq1GGbNO", "rWqJitDx")),
        ("https://lichess.org/study/nq1GGbNO/rWqJitDx?x=1#3", StudyRef("nq1GGbNO", "rWqJitDx")),
        ("lichess.org/study/ZCPaIb70", StudyRef("ZCPaIb70")),
        ("https://www.lichess.org/study/ZCPaIb70", StudyRef("ZCPaIb70")),
        ("HTTPS://LICHESS.ORG/study/ZCPaIb70", StudyRef("ZCPaIb70")),
        ("  https://lichess.org/study/ZCPaIb70  ", StudyRef("ZCPaIb70")),
        ("ZCPaIb70", StudyRef("ZCPaIb70")),
    ],
)
def test_accepts_study_links_chapter_links_and_ids(text: str, expected: StudyRef) -> None:
    assert parse_study_ref(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        None,
        42,
        "http://lichess.org/study/ZCPaIb70",  # not https
        "https://lichess.org.evil.com/study/ZCPaIb70",
        "https://evil.com/lichess.org/study/ZCPaIb70",
        "https://evillichess.org/study/ZCPaIb70",
        "https://user@lichess.org/study/ZCPaIb70",
        "https://lichess.org:8443/study/ZCPaIb70",
        "https://lichess.org/ZCPaIb70",  # a game, not a study
        "https://lichess.org/study",
        "https://lichess.org/study/ZCPaIb7",  # 7 characters
        "https://lichess.org/study/ZCPaIb70x",  # 9 characters
        "https://lichess.org/study/ZCPa-b70",
        "https://lichess.org/study/ZCPaIb70/rWqJitDx/extra",
        "https://lichess.org/study/allstudy",
        "https://lichess.org/study/by/someone",
        "https://lichess.org/study/search?q=vienna",
        "allstudy",
        "ZCPa Ib70",
        "javascript:alert(1)",
        "file:///C:/study/ZCPaIb70",
        "https://lichess.org/study/" + "A" * 400,
    ],
)
def test_refuses_anything_else(text: object) -> None:
    assert parse_study_ref(text) is None


def test_the_url_is_built_by_the_app() -> None:
    assert StudyRef("nq1GGbNO").url == "https://lichess.org/study/nq1GGbNO"
    assert StudyRef("nq1GGbNO", "rWqJitDx").url == "https://lichess.org/study/nq1GGbNO/rWqJitDx"
    assert parse_study_ref("lichess.org/study/ZCPaIb70?evil=1").url == "https://lichess.org/study/ZCPaIb70"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://lichess.org/study", True),
        ("https://lichess.org/study/search?q=vienna", True),
        ("https://lichess.org/", True),
        ("https://www.lichess.org/@/someone", True),
        ("http://lichess.org/study", False),
        ("https://lichess.org.evil.com/", False),
        ("https://lichess1.org/assets/x.js", False),
        ("https://user:pw@lichess.org/", False),
        ("https://lichess.org:444/", False),
        ("https://example.com/", False),
        ("file:///C:/Windows/win.ini", False),
        ("about:blank", False),
        ("javascript:alert(1)", False),
        ("", False),
        (None, False),
    ],
)
def test_window_shows_only_lichess_pages(url: object, allowed: bool) -> None:
    assert is_lichess_page(url) is allowed


@pytest.mark.parametrize(
    ("url", "safe"),
    [
        ("https://example.com/x", True),
        ("http://example.com/x", True),
        ("file:///C:/Windows/win.ini", False),
        ("ms-settings:privacy", False),
        ("javascript:alert(1)", False),
        ("mailto:a@b.c", False),
        ("https:///nohost", False),
        (None, False),
    ],
)
def test_only_web_links_reach_the_system_browser(url: object, safe: bool) -> None:
    assert is_browser_safe(url) is safe
