"""The puzzle-database update check (FR-2.5): a background job, at most once a day, silent offline.

It sends only three plain requests to database.lichess.org: `sha256sums.txt`, a HEAD for the puzzle
file, and the front page for the approximate puzzle count. Nothing about you or your training.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.checksums import find_sha256
from weaksquare.core.clock import Clock
from weaksquare.core.db_update import Installed, Offer, Published, due, offer, parse_count
from weaksquare.jobs.runner import CancelToken, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "puzzle_db_update_check"
AUTO_CHECK_KEY = "puzzle_db.auto_check"  # the user's switch (UiSettingsService validates it)
LAST_CHECK_KEY = "puzzle_db.last_check"  # written here only
SKIPPED_KEY = "puzzle_db.skipped_export"  # written here only
FILE_NAME = "lichess_db_puzzle.csv.zst"


class Http(Protocol):
    def get_text(self, url: str) -> str: ...

    def head_info(self, url: str) -> Any: ...


class SettingsStore(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class Urls:
    file: str
    sums: str
    page: str


class UpdateCheckService:
    def __init__(
        self,
        http: Http,
        clock: Clock,
        settings: SettingsStore,
        read_meta: Any,
        runner: JobRunner,
        urls: Urls,
    ) -> None:
        self._http = http
        self._clock = clock
        self._settings = settings
        self._read_meta = read_meta
        self._runner = runner
        self._urls = urls
        self._lock = threading.Lock()
        self._offer: Offer | None = None
        self._dismissed: str | None = None  # "Not now": hidden until the next launch

    # ---- commands -----------------------------------------------------------------------------
    def start_check(self, force: bool = False) -> str:
        """Run the check as a job. The automatic one (force=False) is skipped when it's off or ran
        less than a day ago; "Check for updates" (force=True) always runs."""
        active = self._runner.active(JOB_KIND)
        if active:
            return active[0].id
        return self._runner.submit(JOB_KIND, lambda progress, token: self.run(progress, token, force))

    def dismiss(self, kind: str) -> None:
        """ "not_now" hides the offer until next launch; "skip" stays quiet until a newer export."""
        with self._lock:
            current = self._offer
            if current is None:
                return
            if kind == "skip":
                self._settings.set(SKIPPED_KEY, current.identity)
            self._dismissed = current.identity
            self._offer = None

    # ---- queries ------------------------------------------------------------------------------
    def current_offer(self) -> Offer | None:
        """The offer from the last check, unless you've imported that export since."""
        with self._lock:
            found = self._offer
        if found is None:
            return None
        meta = self._read_meta() or {}
        if found.identity in (f"sha256:{meta.get('sha256')}", f"date:{meta.get('export_date')}"):
            return None
        return found

    # ---- the job --------------------------------------------------------------------------------
    def run(self, progress: ProgressFn, token: CancelToken, force: bool) -> str:
        meta = self._read_meta() or {}
        if not meta:
            return "No puzzle database installed yet."
        now = self._clock.now()
        if not force:
            if self._settings.get(AUTO_CHECK_KEY) is False:
                return "The automatic check is off."
            if not due(self._settings.get(LAST_CHECK_KEY), now):
                return "Checked less than a day ago."
        progress(None, "Checking database.lichess.org…")
        try:
            published = self._fetch()
        except Exception as e:  # offline or a server problem: silent (FR-2.5), logged for support
            log.info("puzzle database update check failed: %s", type(e).__name__)
            return "Couldn't reach database.lichess.org."
        token.raise_if_cancelled()
        self._settings.set(LAST_CHECK_KEY, now.isoformat(timespec="seconds"))
        mine = Installed(
            meta.get("sha256"),
            meta.get("export_date"),
            int(meta["row_count"]) if meta.get("row_count", "").isdigit() else None,
        )
        found = offer(published, mine, self._settings.get(SKIPPED_KEY))
        with self._lock:
            if found is not None and found.identity == self._dismissed and not force:
                found = None
            self._offer = found
        if found is None:
            return "Your puzzle database is up to date."
        log.info("a newer puzzle database is available (exported %s)", found.export_date)
        return f"A newer puzzle database is available (exported {found.export_date})."

    def _fetch(self) -> Published:
        sums = self._http.get_text(self._urls.sums)
        head = self._http.head_info(self._urls.file)
        try:  # best effort: the page can change or lag the file (FR-2.5)
            count = parse_count(self._http.get_text(self._urls.page))
        except Exception:
            count = None
        return Published(find_sha256(sums, FILE_NAME), head.last_modified, head.size, count)
