"""The one HTTP client for every external call (ARCHITECTURE §3 decision 9).

Descriptive User-Agent with the repo URL as contact, timeouts, retry with backoff on network
errors / 429 / 5xx, resumable downloads, and errors that never carry request headers (SR-7).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from weaksquare.config import APP_VERSION, REPO_URL

log = logging.getLogger(__name__)

USER_AGENT = f"WeakSquare-Chess-Trainer/{APP_VERSION} (+{REPO_URL})"
RETRY_STATUSES = {429, 500, 502, 503, 504}
CHUNK = 1024 * 256
# An API's machine-readable error code (`insufficient_quota`, `authentication_error`, …): short and
# lower-case, so it can't carry request details. The error's human text is never kept (SR-7).
ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")


class HttpError(Exception):
    """A failed request. The message names the URL and status only, never headers."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = True,
        timeout: bool = False,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.timeout = timeout  # the request timed out (it may still have been processed and billed)
        self.error_code = error_code  # the API's own error code from a JSON error body, if any


def _error_code(response: httpx.Response) -> str | None:
    """`{"error": {"code": …}}` (OpenAI) or `{"error": {"type": …}}` (Anthropic), validated as a short code."""
    try:
        err = response.json().get("error")
    except Exception:
        return None
    if not isinstance(err, dict):
        return None
    for field in ("code", "type"):
        value = err.get(field)
        if isinstance(value, str) and ERROR_CODE.fullmatch(value):
            return value
    return None


class Unauthorized(HttpError):
    """HTTP 401: the token is missing, expired or revoked (FR-6.4)."""


class RateLimited(HttpError):
    """HTTP 429. JSON calls don't retry it here: the caller waits (Lichess asks for a minute)."""

    def __init__(self, message: str, *, retry_after_s: float | None = None, error_code: str | None = None) -> None:
        super().__init__(message, status=429, retryable=True, error_code=error_code)
        self.retry_after_s = retry_after_s


class DownloadCancelled(Exception):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size: int
    last_modified: str | None  # ISO date (YYYY-MM-DD) from the Last-Modified header


@dataclass(frozen=True)
class HeadInfo:
    last_modified: str | None  # ISO date (YYYY-MM-DD)
    size: int | None  # bytes, from Content-Length


@dataclass(frozen=True)
class CachedJson:
    status: int  # 200 (fresh) or 304 (unchanged since the ETag sent)
    data: Any
    etag: str | None


def _iso_date(header: str | None) -> str | None:
    if not header:
        return None
    try:
        return parsedate_to_datetime(header).date().isoformat()
    except (TypeError, ValueError):
        return None


class HttpClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            transport=transport,
        )
        self._retries = retries
        self._backoff_s = backoff_s
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _with_retry[T](
        self, what: str, fn: Callable[[], T], *, retries: int | None = None, retry_429: bool = True
    ) -> T:
        delay = self._backoff_s
        retries = self._retries if retries is None else retries
        for attempt in range(retries + 1):
            try:
                return fn()
            except HttpError as e:
                if not e.retryable or attempt == retries or (isinstance(e, RateLimited) and not retry_429):
                    raise
                log.info("%s failed (%s), retrying in %.1fs", what, e.status, delay)
            except httpx.TransportError as e:
                if attempt == retries:
                    raise HttpError(
                        f"Network error while fetching {what}: {type(e).__name__}",
                        timeout=isinstance(e, httpx.TimeoutException),
                    ) from None
                log.info("%s network error (%s), retrying in %.1fs", what, type(e).__name__, delay)
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _check(response: httpx.Response, url: str) -> None:
        if response.status_code == 401:
            raise Unauthorized(f"{url} returned HTTP 401", status=401, retryable=False)
        if response.status_code == 429:
            after = response.headers.get("retry-after", "")
            raise RateLimited(
                f"{url} returned HTTP 429",
                retry_after_s=float(after) if after.isdigit() else None,
                error_code=_error_code(response),  # OpenAI's insufficient_quota is a 429 too
            )
        if response.status_code >= 400:
            raise HttpError(
                f"{url} returned HTTP {response.status_code}",
                status=response.status_code,
                retryable=response.status_code in RETRY_STATUSES,
                error_code=_error_code(response),
            )

    def get_text(self, url: str) -> str:
        def go() -> str:
            r = self._client.get(url)
            self._check(r, url)
            return r.text

        return self._with_retry(url, go)

    # ---- JSON APIs (Lichess) --------------------------------------------------------------------
    # `token` becomes a per-request Authorization header; it's never a client default, never in a URL,
    # and never in an error message (SR-7). 429 is not retried here (the caller backs off).
    @staticmethod
    def _auth(token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        form: dict[str, str] | None = None,
        retry: bool = True,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """One JSON request. Returns the parsed body, or None for an empty one. `headers` carry per-request
        credentials other than a Bearer token (Anthropic's `x-api-key`); like `token`, they're never a
        client default, never logged and never in an error message."""

        def go() -> Any:
            r = self._client.request(
                method, url, headers={"Accept": "application/json", **self._auth(token), **(headers or {})},
                params=params, json=json_body, data=form,
                timeout=httpx.USE_CLIENT_DEFAULT if timeout is None else httpx.Timeout(timeout, connect=15.0),
            )  # fmt: skip
            self._check(r, url)
            if not r.content.strip():
                return None
            try:
                return r.json()
            except ValueError:
                raise HttpError(f"{url} returned a response that isn't JSON", status=r.status_code) from None

        return self._with_retry(url, go, retries=None if retry else 0, retry_429=False)

    def get_json_cached(self, url: str, etag: str | None, *, retry: bool = True) -> CachedJson:
        """A GET with `If-None-Match` (v0.8, chess.com's ETag caching, FR-10.7): HTTP 304 comes back as
        `status=304` with no data instead of an error. 429 is never retried here; the caller backs off."""

        def go() -> CachedJson:
            headers = {"Accept": "application/json"}
            if etag:
                headers["If-None-Match"] = etag
            r = self._client.get(url, headers=headers)
            if r.status_code == 304:
                return CachedJson(304, None, etag)
            self._check(r, url)
            try:
                data = r.json() if r.content.strip() else None
            except ValueError:
                raise HttpError(f"{url} returned a response that isn't JSON", status=r.status_code) from None
            return CachedJson(r.status_code, data, r.headers.get("etag"))

        return self._with_retry(url, go, retries=None if retry else 0, retry_429=False)

    def get_json(
        self,
        url: str,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry: bool = True,
    ) -> Any:
        return self.request_json("GET", url, token=token, params=params, headers=headers, retry=retry)

    def post_json(
        self,
        url: str,
        body: Any,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        retry: bool = True,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self.request_json(
            "POST", url, token=token, params=params, json_body=body, retry=retry, headers=headers, timeout=timeout
        )

    def post_form(self, url: str, form: dict[str, str], *, retry: bool = False) -> Any:
        return self.request_json("POST", url, form=form, retry=retry)

    def delete(self, url: str, *, token: str | None = None) -> None:
        self.request_json("DELETE", url, token=token, retry=False)

    def stream_ndjson(
        self, url: str, *, token: str | None = None, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Newline-delimited JSON, one object at a time (no retry: the caller restarts from its
        last checkpoint). Blank and malformed lines are skipped."""
        headers = {"Accept": "application/x-ndjson", **self._auth(token)}
        try:
            with self._client.stream("GET", url, headers=headers, params=params) as r:
                self._check(r, url)
                for line in r.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        log.warning("%s: skipped a line that isn't JSON", url)
                        continue
                    if isinstance(obj, dict):
                        yield obj
        except httpx.TransportError as e:
            raise HttpError(f"Network error while fetching {url}: {type(e).__name__}") from None

    def last_modified(self, url: str) -> str | None:
        """The Last-Modified date (YYYY-MM-DD) of `url`, from a HEAD request."""
        return self.head_info(url).last_modified

    def head_info(self, url: str) -> HeadInfo:
        """Last-Modified date and Content-Length of `url`, from one HEAD request (FR-2.5)."""

        def go() -> HeadInfo:
            r = self._client.head(url)
            self._check(r, url)
            length = r.headers.get("content-length")
            return HeadInfo(
                _iso_date(r.headers.get("last-modified")), int(length) if length and length.isdigit() else None
            )

        return self._with_retry(url, go)

    def download(
        self,
        url: str,
        dest: Path,
        *,
        progress: Callable[[int, int | None], None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> DownloadResult:
        """Download `url` to `dest`, resuming a previous partial download (`dest.part`) when the
        server still has the same file (checked with If-Range and the stored ETag)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        meta_file = dest.with_name(dest.name + ".part.json")

        def go() -> DownloadResult:
            meta = json.loads(meta_file.read_text()) if meta_file.exists() and part.exists() else {}
            have = part.stat().st_size if part.exists() and meta.get("validator") else 0
            headers = {}
            if have:
                headers = {"Range": f"bytes={have}-", "If-Range": meta["validator"]}
            with self._client.stream("GET", url, headers=headers) as r:
                self._check(r, url)
                if r.status_code != 206:
                    have = 0  # server sent the whole file (new version or no range support)
                validator = r.headers.get("etag") or r.headers.get("last-modified")
                last_modified = r.headers.get("last-modified") or meta.get("last_modified")
                if validator:
                    meta_file.write_text(json.dumps({"validator": validator, "last_modified": last_modified}))
                length = r.headers.get("content-length")
                total = have + int(length) if length is not None else None
                done = have
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_bytes(CHUNK):
                        if cancelled():
                            raise DownloadCancelled()
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            if total is not None and done != total:
                raise HttpError(f"download of {url} was incomplete ({done} of {total} bytes)")
            part.replace(dest)
            meta_file.unlink(missing_ok=True)
            return DownloadResult(dest, done, _iso_date(last_modified))

        return self._with_retry(url, go)
