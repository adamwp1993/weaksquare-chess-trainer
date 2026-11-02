"""A fake `LichessClient` (v0.3). Its defaults come from the recorded fixtures in
tests/fixtures/http/lichess, parsed with the same parsers the real client uses."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from weaksquare.adapters.http import HttpError, RateLimited, Unauthorized
from weaksquare.core.lichess import (
    MAX_BATCH,
    Account,
    ActivityEntry,
    BatchResult,
    Round,
    Solution,
    parse_account,
    parse_activity,
    parse_batch,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "lichess"
FAKE_TOKEN = "lip_FAKE" + "token" * 3


def fixture_account() -> Account:
    return parse_account(json.loads((FIXTURES / "account.json").read_text(encoding="utf-8")))


def fixture_batch() -> BatchResult:
    return parse_batch(json.loads((FIXTURES / "batch_solve.json").read_text(encoding="utf-8")))


def fixture_activity() -> list[ActivityEntry]:
    lines = (FIXTURES / "activity.ndjson").read_text(encoding="utf-8").splitlines()
    return [e for e in (parse_activity(json.loads(x)) for x in lines if x.strip()) if e is not None]


@dataclass
class BatchCall:
    token: str
    angle: str
    solutions: list[Solution]


@dataclass
class FakeLichess:
    """Scriptable: set `account_error`, queue `batch_errors`, choose `diffs` per puzzle, `skip_ids`
    (puzzles Lichess no longer has), or a `gate` to hold a batch until the test releases it."""

    account_value: Account = field(default_factory=fixture_account)
    account_error: Exception | None = None
    token: str = FAKE_TOKEN
    exchange_error: Exception | None = None
    revoke_error: Exception | None = None
    batch_errors: list[Exception] = field(default_factory=list)
    diffs: dict[str, int | None] = field(default_factory=dict)  # puzzle id -> ratingDiff (None = missing)
    skip_ids: set[str] = field(default_factory=set)
    activity_entries: list[ActivityEntry] = field(default_factory=fixture_activity)
    activity_error_after: int | None = None  # raise a network error after yielding this many
    gate: threading.Event | None = None
    on_batch: Callable[[BatchCall], None] | None = None
    rating: int = 1834
    provisional: bool = False
    batch_calls: list[BatchCall] = field(default_factory=list)
    exchange_forms: list[dict[str, str]] = field(default_factory=list)
    activity_since: list[int | None] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    account_calls: int = 0

    def exchange_code(self, form: dict[str, str]) -> str:
        self.exchange_forms.append(form)
        if self.exchange_error:
            raise self.exchange_error
        return self.token

    def revoke(self, token: str) -> None:
        if self.revoke_error:
            raise self.revoke_error
        self.revoked.append(token)

    def account(self, token: str) -> Account:
        self.account_calls += 1
        if self.account_error:
            raise self.account_error
        if token != self.token:
            raise Unauthorized("https://lichess.org/api/account returned HTTP 401", status=401, retryable=False)
        a = self.account_value
        return Account(a.id, a.username, self.rating, self.provisional)

    def solve_batch(self, token: str, angle: str, solutions: list[Solution]) -> BatchResult:
        assert 0 < len(solutions) <= MAX_BATCH, "FR-6.9: fewer than 100 per request"
        call = BatchCall(token, angle, list(solutions))
        self.batch_calls.append(call)
        if self.on_batch:
            self.on_batch(call)
        if self.gate is not None:
            self.gate.wait(5)
        if self.batch_errors:
            raise self.batch_errors.pop(0)
        if token != self.token:
            raise Unauthorized("https://lichess.org/api/puzzle/batch returned HTTP 401", status=401, retryable=False)
        rounds = []
        for s in solutions:
            if s.id in self.skip_ids:
                continue
            diff = self.diffs.get(s.id, (8 if s.win else -12) if s.rated else 0)
            if diff:
                self.rating += diff
            rounds.append(Round(s.id, s.win, diff))
        return BatchResult(rounds, self.rating, self.provisional)

    def activity(self, token: str, since_ms: int | None) -> Iterator[ActivityEntry]:
        self.activity_since.append(since_ms)
        if token != self.token:
            raise Unauthorized("https://lichess.org/api/puzzle/activity returned HTTP 401", status=401, retryable=False)
        for i, e in enumerate(e for e in self.activity_entries if since_ms is None or e.date_ms >= since_ms):
            if self.activity_error_after is not None and i >= self.activity_error_after:
                raise HttpError("Network error while fetching https://lichess.org/api/puzzle/activity: ReadTimeout")
            yield e


def network_error() -> HttpError:
    return HttpError("Network error while fetching https://lichess.org/api/puzzle/batch/mix: ConnectError")


def rate_limited(after: float | None = None) -> RateLimited:
    return RateLimited("https://lichess.org/api/puzzle/batch/mix returned HTTP 429", retry_after_s=after)
