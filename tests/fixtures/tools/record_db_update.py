"""Record the three database.lichess.org responses the update check uses (FR-2.5), scrubbed.

    uv run python tests/fixtures/tools/record_db_update.py

Dev-only. Writes tests/fixtures/http/lichess_db/: the puzzle line of sha256sums.txt (plus the lines
around it, to keep the format real), the HEAD response's Last-Modified and Content-Length only (every
other header, cookies included, is dropped), and only the Puzzles section of the front page. These are
public files, but the page section goes on to a sample CSV with real game URLs, so only its
introduction is kept and every lichess.org link is blanked (SR-12a). test_fixtures_clean.py checks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from weaksquare import config  # noqa: E402
from weaksquare.adapters.http import HttpClient  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "http" / "lichess_db"
KEEP_HEADERS = ("last-modified", "content-length")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    http = HttpClient()
    try:
        sums = http.get_text(config.PUZZLE_SUMS_URL).splitlines()
        i = next(n for n, line in enumerate(sums) if line.endswith("lichess_db_puzzle.csv.zst"))
        (OUT / "sha256sums.txt").write_text("\n".join(sums[max(0, i - 2) : i + 3]) + "\n", encoding="utf-8")

        r = http._client.head(config.PUZZLE_DB_URL)  # raw headers, then keep only two
        r.raise_for_status()
        head = {"status": r.status_code, "headers": {k: r.headers[k] for k in KEEP_HEADERS if k in r.headers}}
        (OUT / "head.json").write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8")

        page = http.get_text(config.PUZZLE_PAGE_URL)
        m = re.search(r'<section id="puzzles".*?</section>', page, re.S)
        if m is None:
            raise SystemExit("the page has no Puzzles section any more: update parse_count and this recorder")
        # Scrub (SR-12a): the section goes on to a sample CSV with real game URLs. Keep only the
        # introduction (up to the first heading), and blank every lichess.org link.
        section = m.group(0).split("<h3", 1)[0] + "</section>"
        section = re.sub(r"https?://(?:[a-z]+\.)?lichess\.org/[^\"'\s<]*", "#", section)
        (OUT / "page.html").write_text(section + "\n", encoding="utf-8")
    finally:
        http.close()
    print(f"recorded into {OUT}")


if __name__ == "__main__":
    main()
