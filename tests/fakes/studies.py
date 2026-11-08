"""Fakes for v0.14's Lichess studies: the studies client and the Lichess window. Invented studies only (SR-12a).

The default fake serves `tests/fixtures/http/lichess_studies/*.pgn` by study ID and the author listing next to them;
tests can add studies, private studies (403 without a token) and errors.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from weaksquare.adapters.http import HttpError, RateLimited
from weaksquare.adapters.lichess_studies import StudyListing, parse_listing
from weaksquare.core.study_links import StudyRef

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "lichess_studies"


def fixture_pgn(name: str) -> str:
    return (FIXTURES / f"{name}.pgn").read_text(encoding="utf-8")


class FakeLichessStudies:
    def __init__(self) -> None:
        self.public: dict[str, str] = {}
        self.private: dict[str, str] = {}  # served only with a token
        self.errors: dict[str, BaseException] = {}
        self.authors: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, str | None]] = []  # (study id or "by:<name>", token)
        self._lock = threading.Lock()
        for f in FIXTURES.glob("*.pgn"):
            self.public[f.stem] = f.read_text(encoding="utf-8")
        listing = FIXTURES / "by_author.ndjson"
        if listing.exists():
            self.authors["player_author"] = [
                json.loads(line) for line in listing.read_text("utf-8").splitlines() if line
            ]

    def study_pgn(self, study_id: str, token: str | None = None) -> str:
        with self._lock:
            self.calls.append((study_id, token))
        if study_id in self.errors:
            raise self.errors[study_id]
        if study_id in self.public:
            return self.public[study_id]
        if study_id in self.private:
            if token:
                return self.private[study_id]
            raise HttpError(f"https://lichess.org/api/study/{study_id}.pgn returned HTTP 403", status=403,
                            retryable=False)  # fmt: skip
        raise HttpError(f"https://lichess.org/api/study/{study_id}.pgn returned HTTP 404", status=404, retryable=False)

    def studies_by(self, username: str) -> Iterator[StudyListing]:
        with self._lock:
            self.calls.append((f"by:{username}", None))
        if f"by:{username}" in self.errors:
            raise self.errors[f"by:{username}"]
        if username not in self.authors:
            raise HttpError("https://lichess.org/api/study/by/x returned HTTP 404", status=404, retryable=False)
        for obj in self.authors[username]:
            listing = parse_listing(obj)
            if listing is not None:
                yield listing


def rate_limited() -> RateLimited:
    return RateLimited("https://lichess.org/api/study/x.pgn returned HTTP 429")


class FakeLichessWindow:
    """Never starts a process. Tests drive `added`, `page` and `closed` by hand."""

    def __init__(
        self,
        on_add: Callable[[StudyRef], None],
        on_page: Callable[[StudyRef | None], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self.on_add, self.on_page, self.on_closed = on_add, on_page, on_closed
        self.opened = 0
        self.focused = 0
        self._open = False

    def open(self) -> bool:
        if self._open:
            self.focused += 1
            return False
        self._open = True
        self.opened += 1
        return True

    def is_open(self) -> bool:
        return self._open

    def close(self, timeout: float = 10) -> None:
        if self._open:
            self._open = False
            if self.on_closed:
                self.on_closed()
