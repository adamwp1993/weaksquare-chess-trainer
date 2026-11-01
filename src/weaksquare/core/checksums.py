"""Parse published checksum lists (SR-6)."""

from __future__ import annotations

import re

_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S+)\s*$")


def find_sha256(sums_text: str, filename: str) -> str | None:
    """The hex SHA-256 for `filename` in a `sha256sum`-style list, or None if it isn't listed.

    If the list names the file more than once with different hashes, it's ambiguous: None.
    """
    found = {
        m.group(1).lower()
        for line in sums_text.splitlines()
        if (m := _LINE.match(line.strip())) and m.group(2) == filename
    }
    return found.pop() if len(found) == 1 else None
