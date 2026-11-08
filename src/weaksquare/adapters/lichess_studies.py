"""Lichess studies over the shared HTTP client (FR-13.5a, 13.7). Documented API only; the service sends one request at
a time. The token is passed per request, only when the service decides it's needed, and never logged (SR-7)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from weaksquare.adapters.http import HttpClient
from weaksquare.core.study_links import is_study_id

BASE = "https://lichess.org"
MAX_PGN_BYTES = 20_000_000  # a 64-chapter study with heavy analysis is a few MB
MAX_AUTHOR_STUDIES = 300


@dataclass(frozen=True)
class StudyListing:
    """One entry of `GET /api/study/by/{username}`: only ID, name and dates (checked 2026-11-06)."""

    study_id: str
    name: str
    created_ms: int | None
    updated_ms: int | None


class LichessStudies:
    def __init__(self, http: HttpClient, base: str = BASE) -> None:
        self._http = http
        self._base = base

    def study_pgn(self, study_id: str, token: str | None = None) -> str:
        """`GET /api/study/{id}.pgn` with comments, variations and orientation, no clocks."""
        if not is_study_id(study_id):
            raise ValueError("not a study ID")
        return self._http.get_text_limited(
            f"{self._base}/api/study/{study_id}.pgn",
            max_bytes=MAX_PGN_BYTES,
            token=token,
            params={"clocks": "false", "comments": "true", "variations": "true", "orientation": "true"},
            accept="application/x-chess-pgn",
        )

    def studies_by(self, username: str) -> Iterator[StudyListing]:
        """`GET /api/study/by/{username}`: that author's public studies (newline-delimited JSON)."""
        count = 0
        for obj in self._http.stream_ndjson(f"{self._base}/api/study/by/{username}"):
            listing = parse_listing(obj)
            if listing is None:
                continue
            yield listing
            count += 1
            if count >= MAX_AUTHOR_STUDIES:
                return


def parse_listing(obj: object) -> StudyListing | None:
    if not isinstance(obj, dict):
        return None
    sid, name = obj.get("id"), obj.get("name")
    if not is_study_id(sid) or not isinstance(name, str):
        return None

    def ms(v: object) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None

    return StudyListing(str(sid), name[:200], ms(obj.get("createdAt")), ms(obj.get("updatedAt")))
