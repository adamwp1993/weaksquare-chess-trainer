"""Lichess study addresses (FR-13.4, 13.5): what counts as a study link, and which pages the Lichess window may show.

Pure functions, no I/O. The paste box, the Lichess window's toolbar and the app's re-check of what that window sends all
use `parse_study_ref`, so there is one rule for what a study address is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

LICHESS_HOST = "lichess.org"
STUDY_LIST_URL = "https://lichess.org/study"

# Lichess study and chapter IDs are 8 characters of [A-Za-z0-9] (checked on real studies, 2026-11-07).
_ID = r"[A-Za-z0-9]{8}"
_ID_RE = re.compile(rf"^{_ID}$")
_PATH_RE = re.compile(rf"^/study/(?P<study>{_ID})(?:/(?P<chapter>{_ID}))?/?$")
# Paths under /study/ that aren't a study ID even though they're 8 characters long.
_RESERVED = frozenset({"allstudy", "mine", "member", "public", "private", "liked", "topic", "search", "by"})
_MAX_INPUT = 300


@dataclass(frozen=True)
class StudyRef:
    """One study, optionally pointing at one of its chapters."""

    study_id: str
    chapter_id: str | None = None

    @property
    def url(self) -> str:
        """The study's address on Lichess, built by the app (never taken from the input)."""
        base = f"https://{LICHESS_HOST}/study/{self.study_id}"
        return f"{base}/{self.chapter_id}" if self.chapter_id else base


def is_study_id(value: object) -> bool:
    """An 8-character Lichess study or chapter ID, and nothing else (no query, path or fragment)."""
    return isinstance(value, str) and bool(_ID_RE.match(value)) and value.lower() not in _RESERVED


def ref_from_ids(study: object, chapter: object = None) -> StudyRef | None:
    """A study from separate IDs (what the Lichess window sends, what the database stores), each checked on its own."""
    if not is_study_id(study):
        return None
    if chapter in (None, ""):
        return StudyRef(str(study))
    if not is_study_id(chapter):
        return None
    return StudyRef(str(study), str(chapter))


def parse_study_ref(text: object) -> StudyRef | None:
    """A study from a pasted link, chapter link or bare ID; None for anything else (FR-13.5).

    Accepts `https://lichess.org/study/{id}`, `…/study/{id}/{chapterId}`, the same without the scheme or with
    `www.`, an optional trailing slash, query or `#fragment`, and a bare 8-character ID. Rejects other hosts (including
    look-alikes such as `lichess.org.evil.com`), `http:`, user info, ports and anything over a sane length.
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s or len(s) > _MAX_INPUT or any(c.isspace() for c in s):
        return None
    if _ID_RE.match(s):
        return None if s.lower() in _RESERVED else StudyRef(s)
    if "://" not in s:
        s = "https://" + s
    try:
        parts = urlsplit(s)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or port is not None or parts.username or parts.password:
        return None
    host = (parts.hostname or "").lower()
    if host not in (LICHESS_HOST, "www." + LICHESS_HOST):
        return None
    m = _PATH_RE.match(parts.path)
    if not m or m["study"].lower() in _RESERVED:
        return None
    return StudyRef(m["study"], m["chapter"])


_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,28}[A-Za-z0-9]$")


def clean_username(text: object) -> str | None:
    """A Lichess username for Studies by author (FR-13.5a): 2-30 letters, digits, `_` or `-`, also from a profile
    link (`lichess.org/@/name`). None for anything else, so no request is made."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    for prefix in ("https://lichess.org/@/", "lichess.org/@/", "@"):
        if s.lower().startswith(prefix):
            s = s[len(prefix) :].strip("/")
            break
    return s if _USERNAME_RE.match(s) else None


def is_lichess_page(url: object) -> bool:
    """Whether the Lichess window may show this address itself (FR-13.3): https on lichess.org only.

    Anything else (other hosts and schemes, look-alike hosts, user info, ports) is opened in the system browser instead.
    """
    if not isinstance(url, str) or len(url) > 4096:
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or port is not None or parts.username or parts.password:
        return False
    return (parts.hostname or "").lower() in (LICHESS_HOST, "www." + LICHESS_HOST)


def is_browser_safe(url: object) -> bool:
    """Whether a link the Lichess window refused may be handed to the system browser: http(s) only, never
    `file:`, `javascript:` or a custom protocol that could start a program."""
    if not isinstance(url, str) or len(url) > 4096:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)
