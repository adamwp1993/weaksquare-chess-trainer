"""Name the idea first (FR-4.3): the pickers in web/src/state/ideas.ts match core/themes.py exactly (keys,
order and names), so the UI can't offer a tag the backend refuses."""

from __future__ import annotations

import re
from pathlib import Path

from weaksquare.core.themes import IDEA_PAYOFF, IDEA_SETUP, display_name

IDEAS_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "state" / "ideas.ts"


def _list(name: str) -> list[tuple[str, str]]:
    text = IDEAS_TS.read_text(encoding="utf-8")
    block = re.search(rf"export const {name}: \[string, string\]\[\] = \[(.*?)\];", text, re.S)
    assert block, name
    return re.findall(r'\["([^"]+)", "([^"]+)"\]', block.group(1))


def test_setup_and_payoff_lists_match_the_backend() -> None:
    for name, keys in (("IDEA_SETUP", IDEA_SETUP), ("IDEA_PAYOFF", IDEA_PAYOFF)):
        assert _list(name) == [(k, display_name(k)) for k in keys], name


# Regression test for v0.6-B8 (QA round 1): the User Guide documents shipped features only.
def test_mistake_reasons_chapter_promises_nothing_unshipped() -> None:
    guide = (Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    chapter = guide.split("## Mistake reasons", 1)[1].split("\n## ", 1)[0]
    assert "later version" not in chapter.lower()
