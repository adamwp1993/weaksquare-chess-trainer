"""The one HTTP client for every external call (ARCHITECTURE §3 decision 9).

Descriptive User-Agent with the repo URL as contact, timeouts, retry with backoff on network
errors / 429 / 5xx, resumable downloads, and errors that never carry request headers (SR-7).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from weaksquare.config import APP_VERSION, REPO_URL

log = logging.getLogger(__name__)

USER_AGENT = f"WeakSquare-Chess-Trainer/{APP_VERSION} (+{REPO_URL})"
RETRY_STATUSES = {429, 500, 502, 503, 504}
CHUNK = 1024 * 256


class HttpError(Exception):
    """A failed request. The message names the URL and status only, never headers."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


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

    def _with_retry[T](self, what: str, fn: Callable[[], T]) -> T:
        delay = self._backoff_s
        for attempt in range(self._retries + 1):
            try:
                return fn()
            except HttpError as e:
                if not e.retryable or attempt == self._retries:
                    raise
                log.info("%s failed (%s), retrying in %.1fs", what, e.status, delay)
            except httpx.TransportError as e:
                if attempt == self._retries:
                    raise HttpError(f"Network error while fetching {what}: {type(e).__name__}") from None
                log.info("%s network error (%s), retrying in %.1fs", what, type(e).__name__, delay)
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _check(response: httpx.Response, url: str) -> None:
        if response.status_code >= 400:
            raise HttpError(
                f"{url} returned HTTP {response.status_code}",
                status=response.status_code,
                retryable=response.status_code in RETRY_STATUSES,
            )

    def get_text(self, url: str) -> str:
        def go() -> str:
            r = self._client.get(url)
            self._check(r, url)
            return r.text

        return self._with_retry(url, go)

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
