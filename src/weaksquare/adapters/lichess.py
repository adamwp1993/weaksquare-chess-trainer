"""`LichessClient` over the shared HTTP client (FR-6.1–6.12, 6.17). Every call goes through
`adapters/http.py`; the token is passed per request and never logged (SR-7)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from weaksquare.adapters.http import HttpClient, HttpError, RateLimited, Unauthorized
from weaksquare.core.lichess import (
    Account,
    ActivityEntry,
    BatchResult,
    Solution,
    batch_body,
    parse_account,
    parse_activity,
    parse_batch,
    valid_angle,
)

BASE = "https://lichess.org"


class LichessHttp:
    def __init__(self, http: HttpClient, base: str = BASE) -> None:
        self._http = http
        self._base = base

    def exchange_code(self, form: dict[str, str]) -> str:
        data: Any = self._http.post_form(f"{self._base}/api/token", form)
        token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise HttpError("Lichess didn't return an access token", retryable=False)
        return token

    def revoke(self, token: str) -> None:
        self._http.delete(f"{self._base}/api/token", token=token)

    def account(self, token: str) -> Account:
        try:
            return parse_account(self._http.get_json(f"{self._base}/api/account", token=token))
        except ValueError:
            raise HttpError("Lichess returned an unexpected account response", retryable=False) from None

    def solve_batch(self, token: str, angle: str, solutions: list[Solution]) -> BatchResult:
        if not valid_angle(angle):
            raise ValueError("invalid angle")
        data = self._http.post_json(
            f"{self._base}/api/puzzle/batch/{angle}",
            batch_body(solutions),
            token=token,
            params={"nb": 0},
            retry=False,  # the sync service backs off itself; never resend a batch here (v0.3-B4)
        )
        try:
            return parse_batch(data)
        except ValueError:
            raise HttpError("Lichess returned an unexpected solve response", retryable=False) from None

    def activity(self, token: str, since_ms: int | None) -> Iterator[ActivityEntry]:
        params = {"since": since_ms} if since_ms else None
        for obj in self._http.stream_ndjson(f"{self._base}/api/puzzle/activity", token=token, params=params):
            entry = parse_activity(obj)
            if entry is not None:
                yield entry


def is_unauthorized(e: BaseException) -> bool:
    """FR-6.4: the token is missing, expired or revoked."""
    return isinstance(e, Unauthorized)


def is_network_error(e: BaseException) -> bool:
    """Lichess couldn't be reached or is having trouble (no response, 429 or 5xx): try again later.
    Other HTTP errors (400, 403, 404…) are real refusals."""
    if isinstance(e, Unauthorized):
        return False
    if isinstance(e, HttpError):
        # A response we couldn't use (retryable=False, e.g. an unexpected body) isn't a network
        # problem: retrying it forever would never help (v0.3-B1).
        return e.retryable and (e.status is None or e.status == 429 or e.status >= 500)
    return isinstance(e, OSError)


def is_rate_limited(e: BaseException) -> bool:
    return isinstance(e, RateLimited)


def retry_after(e: BaseException) -> float | None:
    return e.retry_after_s if isinstance(e, RateLimited) else None
