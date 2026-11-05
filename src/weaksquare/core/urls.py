"""Web addresses out of free text (FR-8.16: never a URL to the LLM; FR-10.59: never a URL from it). Pure.

Used on your notes before they're sent (FR-10.60) and on everything an LLM writes that the app shows
(the summary, the findings, preset names). QA v0.11-B2: it catches any `scheme://…`, `www.…` and bare
domains on common top-level domains (`youtu.be/…`, `bit.ly/…`, `chessable.co.uk/…`, `example.de`), and it
stops at a word boundary, so chess text and missing spaces ("Qd1.Coming back") are left alone.
"""

from __future__ import annotations

import re

REPLACEMENT = "[link removed]"
TLDS = (
    "com", "org", "net", "io", "be", "ly", "de", "uk", "co", "tv", "gg", "me", "info", "app", "dev", "edu", "gov",
    "fr", "es", "it", "nl", "ru", "ca", "au", "in", "us", "ch", "se", "no", "pl", "br", "jp", "cn", "xyz", "site",
    "online", "link", "to", "gl", "cc", "eu", "ai", "ly", "at", "dk", "fi", "pt", "cz", "tk", "ws", "fm", "am",
)  # fmt: skip
_TLD = "|".join(sorted(set(TLDS), key=len, reverse=True))
_URL = re.compile(
    r"(?i)"
    r"\b[a-z][a-z0-9+.-]*://\S+"  # any scheme: http, https, ftp, …
    r"|\bwww\.\S+"
    rf"|\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:{_TLD})(?![a-z0-9-])(?:[/?#]\S*)?"
)


def strip_urls(text: str) -> str:
    return _URL.sub(REPLACEMENT, text)
