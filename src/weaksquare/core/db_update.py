"""Is a newer Lichess puzzle export available? (FR-2.5). Pure rules; the fetching is in services/db_update.py.

A newer export exists when the SHA-256 Lichess publishes differs from the one recorded at import.
A database imported from a local file has no hash, so then the file's Last-Modified date is compared
with the export date instead. "Skip this export" stores the export's identity (its hash, or its date
when there's no hash) and stays quiet until a different one appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

CHECK_INTERVAL = timedelta(days=1)
_COUNT = re.compile(r'id="puzzles".*?<strong>\s*([\d,   ]+?)\s*</strong>\s*chess puzzles', re.S | re.I)


@dataclass(frozen=True)
class Published:
    sha256: str | None
    export_date: str | None  # from Last-Modified
    size: int | None  # bytes
    approx_count: int | None  # from the database.lichess.org page; may lag the file


@dataclass(frozen=True)
class Installed:
    sha256: str | None
    export_date: str | None
    count: int | None


@dataclass(frozen=True)
class Offer:
    export_date: str | None
    current_export_date: str | None
    size: int | None
    approx_count: int | None
    approx_new: int | None  # approx_count minus the puzzles you have now
    identity: str  # what "Skip this export" remembers


def parse_count(html: str) -> int | None:
    """The puzzle count on database.lichess.org, e.g. "<strong>6,193,530</strong> chess puzzles"."""
    m = _COUNT.search(html)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def identity(p: Published) -> str | None:
    if p.sha256:
        return f"sha256:{p.sha256}"
    if p.export_date:
        return f"date:{p.export_date}"
    return None


def is_newer(p: Published, mine: Installed) -> bool:
    if p.sha256 and mine.sha256:
        return p.sha256 != mine.sha256
    if p.export_date and mine.export_date:  # a local-file import has no hash: compare dates
        return p.export_date > mine.export_date
    return False


def offer(p: Published, mine: Installed, skipped: str | None) -> Offer | None:
    ident = identity(p)
    if ident is None or ident == skipped or not is_newer(p, mine):
        return None
    approx_new = p.approx_count - mine.count if p.approx_count is not None and mine.count is not None else None
    return Offer(p.export_date, mine.export_date, p.size, p.approx_count, approx_new, ident)


def due(last_check: str | None, now: datetime) -> bool:
    """The automatic check runs at most once a day."""
    if not last_check:
        return True
    try:
        last = datetime.fromisoformat(last_check)
    except ValueError:
        return True
    if (last.tzinfo is None) != (now.tzinfo is None):
        last = last.replace(tzinfo=now.tzinfo)
    return now - last >= CHECK_INTERVAL
