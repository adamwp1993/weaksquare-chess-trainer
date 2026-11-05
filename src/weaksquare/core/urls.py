"""Web addresses out of free text (FR-8.16: never a URL to the LLM; FR-10.59: never a URL from it). Pure.

Used on your notes before they're sent (FR-10.60) and on everything an LLM writes that the app shows
(the summary, the findings, preset names).

**One word at a time** (QA v0.11-B14: no regex backtracking, so a long AI answer is filtered in linear
time). A whitespace-separated word is an address, and is replaced whole, when it:
- has a scheme (`https://…`, `ftp://…`, `hxxp://…`), starts with `www.` or `//host`;
- is an IPv4 address, or any host with a port (`evil.example:8080`, `localhost:8080/x`) (B13);
- is a dotted host followed by a path, query or fragment (`chess.academy/x`, `café.example/menu`,
  `my_site.example/x`, `пример.рф/x`), whatever its top-level domain (B9, B13);
- is a bare dotted host ending in a common top-level domain (`bit.ly`, `example.de`, `EVIL.CO.UK`).

**Not an address:** the ending must be letters, at least two, and written in lower case or all capitals.
A capitalized ending is a missing space ("blunder.Today I learned", "Nf3.Why?", "Ng5.Black/White"),
except for `.Com` and `.Org` (`Lichess.Org`) (B10–B12). A bare host whose ending is also a short English word
(`.no`, `.to`, `.it`, `.be`…) needs a path to count, so "blundered.it was bad" is left alone. Chess text
never matches: a move's label has a digit or `+`/`=`/`#` (`12.Rd1/Rd2`, `e4.Bc4?`, `e8=Q.Why?`).
"""

from __future__ import annotations

import re

REPLACEMENT = "[link removed]"
TLDS = frozenset(
    {
        "com", "org", "net", "io", "be", "ly", "de", "uk", "co", "tv", "gg", "me", "info", "app", "dev", "edu",
        "gov", "fr", "es", "it", "nl", "ru", "ca", "au", "in", "us", "ch", "se", "no", "pl", "br", "jp", "cn",
        "xyz", "site", "online", "link", "to", "gl", "cc", "eu", "ai", "at", "dk", "fi", "pt", "cz", "tk", "ws",
        "fm", "am", "kr", "nz", "blog", "club", "live", "academy", "store", "shop", "news", "tech", "biz", "today",
        "page",
    }
)  # fmt: skip
# Endings that are also short English words: a bare host with one of these needs a path to count.
WORDS = frozenset({"no", "to", "it", "at", "am", "be", "in", "me", "us", "co", "so", "go", "do", "my", "is", "on"})
TITLE_CASE_OK = frozenset({"com", "org"})  # "Lichess.Org": a capitalized ending that is still an address
_SPACE = re.compile(r"(\s+)")
_LEAD = "([{<\"'«“‘"
_TRAIL = ".,;:!?)]}>\"'»”’"
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_PORT = re.compile(r"^:\d{1,5}(?=$|[/?#])")


def _label_ok(label: str) -> bool:
    return bool(label) and all(c.isalnum() or c in "-_" for c in label)


def _ending(tld: str) -> str | None:
    """The ending's case class: 'lower', 'upper', 'title', or None when it can't be a top-level domain."""
    if tld.lower().startswith("xn--") and _label_ok(tld):
        return "lower"
    if len(tld) < 2 or len(tld) > 24 or not tld.isalpha():
        return None
    if tld.islower():
        return "lower"
    if tld.isupper():
        return "upper"
    if tld[0].isupper() and tld[1:].islower():
        return "title"
    return None


def _is_ipv4(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() and len(p) <= 3 and int(p) <= 255 for p in parts)


def is_address(word: str) -> bool:
    w = word.lstrip(_LEAD)
    if not w:
        return False
    if _SCHEME.match(w) or w.lower().startswith("www."):
        return True
    if w.startswith("//"):
        w = w[2:]
    core = w.rstrip(_TRAIL)
    cut = next((i for i, c in enumerate(core) if c in "/?#:"), len(core))
    host, rest = core[:cut], core[cut:]
    port = _PORT.match(rest)
    if port:
        rest = rest[port.end() :]
    if _is_ipv4(host):
        return True
    labels = host.split(".")
    if port and len(labels) == 1 and host.lower() == "localhost":
        return True
    if len(labels) < 2 or not all(_label_ok(lab) for lab in labels):
        return False
    tld = labels[-1]
    case = _ending(tld)
    if case is None or (case == "title" and tld.lower() not in TITLE_CASE_OK):
        return False
    if port or (rest and rest[0] in "/?#"):
        return True
    t = tld.lower()
    return t in TLDS and t not in WORDS


def strip_urls(text: str) -> str:
    """Every word that is an address becomes "[link removed]"; leading brackets or quotes stay."""
    out: list[str] = []
    for part in _SPACE.split(text):
        if part and not part.isspace() and is_address(part):
            lead = part[: len(part) - len(part.lstrip(_LEAD))]
            out.append(lead + REPLACEMENT)
        else:
            out.append(part)
    return "".join(out)
