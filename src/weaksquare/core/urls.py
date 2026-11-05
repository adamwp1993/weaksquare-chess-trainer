"""Web addresses out of free text (FR-8.16: never a URL to the LLM; FR-10.59: never a URL from it). Pure.

Used on your notes before they're sent (FR-10.60) and on everything an LLM writes that the app shows
(the summary, the findings, preset names). What counts as an address:
- anything with a scheme (`https://…`, `ftp://…`, `hxxp://…`) or starting with `www.`;
- an IPv4 address;
- **any** dotted host followed by a path, query or fragment (`chess.academy/x`, `evil.example/x`), whatever
  its top-level domain (QA v0.11-B9);
- a bare dotted host with no path when it ends in a common top-level domain (`bit.ly`, `example.de`,
  `chessable.co.uk`, `Lichess.Org`). An ending that is also a short English word (No, To, It, At, Be…)
  counts only in lower case, so "Blundered.No time" and "Nf3.To be safe" are left alone (QA v0.11-B10).
"""

from __future__ import annotations

import re

REPLACEMENT = "[link removed]"
TLDS = (
    "com", "org", "net", "io", "be", "ly", "de", "uk", "co", "tv", "gg", "me", "info", "app", "dev", "edu", "gov",
    "fr", "es", "it", "nl", "ru", "ca", "au", "in", "us", "ch", "se", "no", "pl", "br", "jp", "cn", "xyz", "site",
    "online", "link", "to", "gl", "cc", "eu", "ai", "at", "dk", "fi", "pt", "cz", "tk", "ws", "fm", "am", "kr",
    "nz", "blog", "club", "live", "academy", "store", "shop", "news", "tech", "biz", "today", "page",
)  # fmt: skip
# Endings that are also short English words: after a dot they count only in lower case, because
# "Blundered.No time" is a missing space, while "Lichess.Org" is still an address (QA v0.11-B10).
WORDS = frozenset({"no", "to", "it", "at", "am", "be", "in", "me", "us", "co", "so", "go", "do", "my", "is", "on"})
_TLD = "|".join(sorted(set(TLDS), key=len, reverse=True))
_TLD_ANY_CASE = "|".join(sorted(set(TLDS) - WORDS, key=len, reverse=True))
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_URL = re.compile(
    r"(?i:\b[a-z][a-z0-9+.-]*://\S+)"  # any scheme
    r"|(?i:\bwww\.\S+)"
    r"|\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?(?:[/?#]\S*)?"  # IPv4
    rf"|(?i:\b(?:{_LABEL}\.)+[a-z]{{2,24}}(?::\d+)?[/?#]\S*)"  # any host with a path (B9)
    rf"|\b(?i:(?:{_LABEL}\.)+)(?:{_TLD})(?![A-Za-z0-9-])"  # a bare host, ending in lower case
    rf"|\b(?i:(?:{_LABEL}\.)+(?:{_TLD_ANY_CASE}))(?![A-Za-z0-9-])"  # any case, unless the ending is a word (B10)
)


def strip_urls(text: str) -> str:
    return _URL.sub(REPLACEMENT, text)
