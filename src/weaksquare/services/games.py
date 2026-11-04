"""The game library (v0.8, REQUIREMENTS §11.1, §11.5): linked accounts, incremental sync from Lichess and
chess.com, and one-off imports (paste, file, Lichess URL, chess.com URL).

**Sync fetches metadata and PGNs only, never analysis** (FR-11.27). It runs as a background job, on app
open (a setting, on by default) and from Refresh:
- **Lichess** (signed in only, FR-11.23): your games since the last sync, with your token.
- **chess.com** (a linked username, FR-11.24): the archives list, then only months on or after the last
  synced one, one request at a time, with ETags (the client enforces both).
- **First sync:** the last 90 days or 200 games per account, whichever is smaller (configurable).

Every import dedupes by platform id or identical moves, so a re-import reuses the stored analysis
(FR-11.7). Your color is detected from your linked usernames, else the UI asks (FR-11.5).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from weaksquare.core.chesscom import archive_month, game_id_from_url, months_to_fetch, parse_archive_game
from weaksquare.core.clock import Clock
from weaksquare.core.errors import AppError, NotFoundError, ValidationError
from weaksquare.core.games import (
    MAX_PGN_BYTES,
    ChesscomClient,
    GameError,
    GameRecord,
    GameRow,
    LibraryFilter,
    LichessGamesClient,
    ParsedGame,
    Skip,
    SyncState,
    detect_color,
    moves_hash,
    parse_chesscom_url,
    parse_lichess_game,
    parse_lichess_url,
    parse_pgn,
    parse_single_pgn,
    record_from_parsed,
    username_from,
    valid_username,
)
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

SYNC_JOB = "games_sync"
URL_JOB = "game_url_import"
CHESSCOM_KEY = "chesscom.username"
SYNC_ON_OPEN_KEY = "games.sync_on_open"
FIRST_DAYS_KEY = "games.first_sync_days"
FIRST_MAX_KEY = "games.first_sync_max"
DEFAULT_FIRST_DAYS = 90
DEFAULT_FIRST_MAX = 200
FIRST_DAYS_RANGE = (1, 3650)
FIRST_MAX_RANGE = (1, 5000)
URL_SEARCH_MONTHS = 6  # chess.com URL import searches this many recent months (plan v0.8)
LATER_SYNC_MAX = 1000  # a safety cap per Lichess sync after the first
PENDING_FILES = 5

ErrorKind = Literal["unauthorized", "network", "not_found", "gone", "other"]


class Account(Protocol):
    def account_id(self) -> str | None: ...

    def token(self) -> str | None: ...

    def mark_expired(self) -> None: ...


class GamesStore(Protocol):
    def add(self, rec: GameRecord, moves_hash: str, user_color: str | None, fetched_at: str) -> tuple[int, bool]: ...

    def get(self, game_id: int) -> GameRow | None: ...

    def list(self, f: LibraryFilter) -> tuple[list[GameRow], int]: ...

    def set_user_color(self, game_id: int, color: str) -> None: ...


class SyncStore(Protocol):
    def get(self, platform: str) -> SyncState | None: ...

    def put(self, s: SyncState) -> None: ...

    def clear(self, platform: str) -> None: ...


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class Choice:
    index: int
    label: str
    error: str | None


@dataclass(frozen=True)
class ImportOutcome:
    """The result of an import. With several games in a file, `choices` lists them and `token` picks one
    (`pick`); otherwise `game_id` is the stored game and `needs_color` asks which side you played."""

    game_id: int | None = None
    created: bool = False
    needs_color: bool = False
    analyzed: bool = False
    choices: tuple[Choice, ...] = ()
    token: str | None = None


@dataclass(frozen=True)
class GamesSettings:
    chesscom_username: str | None
    sync_on_open: bool
    first_sync_days: int
    first_sync_max: int


@dataclass
class _SyncCounts:
    new: int = 0
    seen: int = 0
    notes: list[str] = field(default_factory=list)


def _ms(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except ValueError:
        return None


class GameLibraryService:
    def __init__(
        self,
        repo: GamesStore,
        sync_repo: SyncStore,
        settings: Settings,
        runner: JobRunner,
        clock: Clock,
        account: Account,
        lichess: LichessGamesClient,
        chesscom: ChesscomClient,
        classify_error: Callable[[BaseException], ErrorKind],
        on_new_games: Callable[[int], None] = lambda n: None,
    ) -> None:
        self._repo = repo
        self._sync = sync_repo
        self._settings = settings
        self._runner = runner
        self._clock = clock
        self._account = account
        self._lichess = lichess
        self._chesscom = chesscom
        self._classify = classify_error
        self._on_new_games = on_new_games
        self._lock = threading.Lock()
        self._pending: dict[str, list[ParsedGame | GameError]] = {}
        self._pending_source: dict[str, str] = {}
        self._next_token = 0
        self._url_results: dict[str, ImportOutcome] = {}  # by ticket
        self._url_tickets: dict[str, str] = {}  # job id -> ticket

    # ------------------------------------------------------------ settings and accounts

    def settings(self) -> GamesSettings:
        u = self._settings.get(CHESSCOM_KEY)
        on = self._settings.get(SYNC_ON_OPEN_KEY)
        days = self._settings.get(FIRST_DAYS_KEY)
        mx = self._settings.get(FIRST_MAX_KEY)
        return GamesSettings(
            chesscom_username=u if isinstance(u, str) and u else None,
            sync_on_open=on if isinstance(on, bool) else True,
            first_sync_days=days if isinstance(days, int) and not isinstance(days, bool) else DEFAULT_FIRST_DAYS,
            first_sync_max=mx if isinstance(mx, int) and not isinstance(mx, bool) else DEFAULT_FIRST_MAX,
        )

    def set_settings(
        self, *, sync_on_open: bool | None = None, first_sync_days: int | None = None, first_sync_max: int | None = None
    ) -> GamesSettings:
        if sync_on_open is not None:
            if not isinstance(sync_on_open, bool):
                raise ValidationError("sync_on_open must be true or false")
            self._settings.set(SYNC_ON_OPEN_KEY, sync_on_open)
        for key, value, (lo, hi), what in (
            (FIRST_DAYS_KEY, first_sync_days, FIRST_DAYS_RANGE, "days"),
            (FIRST_MAX_KEY, first_sync_max, FIRST_MAX_RANGE, "games"),
        ):
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
                raise ValidationError(f"the first sync's {what} must be a whole number from {lo} to {hi}")
            self._settings.set(key, value)
        return self.settings()

    def verify_chesscom(self, text: str) -> dict[str, Any]:
        """FR-11.24: the public profile, or a clear error when no such player exists."""
        username = username_from(text)
        if not valid_username(username):
            raise ValidationError("That isn't a chess.com username.")
        try:
            p = self._chesscom.profile(username)
        except Exception as e:
            kind = self._classify(e)
            if kind == "not_found":
                raise NotFoundError(f"There's no chess.com player called {username}.") from None
            if kind == "network":
                raise AppError("Couldn't reach chess.com. Try again.", code="offline", retryable=True) from None
            raise
        return {"username": p.username, "name": p.name, "url": p.url, "joined": p.joined}

    def set_chesscom_username(self, text: str | None) -> str | None:
        """Link (or unlink with None) a chess.com username. It's public data, not a secret (FR-11.24).
        Changing it forgets the other account's sync position; its games stay in the library."""
        username = username_from(text) if text else None
        if username is not None and not valid_username(username):
            raise ValidationError("That isn't a chess.com username.")
        old = self.settings().chesscom_username
        if (old or "").lower() != (username or "").lower():
            self._sync.clear("chesscom")
        self._settings.set(CHESSCOM_KEY, username)
        return username

    def usernames(self) -> list[str]:
        return [u for u in (self._account.account_id(), self.settings().chesscom_username) if u]

    # ------------------------------------------------------------ sync

    def sync_on_open(self) -> str | None:
        return self.start_sync() if self.settings().sync_on_open else None

    def start_sync(self) -> str | None:
        """The background sync job, or None when no account is linked. Never blocks the UI (FR-11.27)."""
        if not (self._account.account_id() and self._account.token()) and not self.settings().chesscom_username:
            return None
        running = self._runner.active(SYNC_JOB)
        if running:
            return running[0].id
        return self._runner.submit(SYNC_JOB, self._run_sync)

    def _run_sync(self, progress: ProgressFn, cancel: CancelToken) -> str:
        counts = _SyncCounts()
        tried = failed = 0
        if self._account.account_id() and self._account.token():
            tried += 1
            try:
                self._sync_lichess(counts, progress, cancel)
            except JobFailed as e:
                failed += 1
                counts.notes.append(e.message)
        if self.settings().chesscom_username:
            tried += 1
            try:
                self._sync_chesscom(counts, progress, cancel)
            except JobFailed as e:
                failed += 1
                counts.notes.append(e.message)
        if tried and failed == tried:
            raise JobFailed("offline", " ".join(counts.notes))
        if counts.new:
            self._on_new_games(counts.new)
        msg = f"{counts.new} new game{'s' if counts.new != 1 else ''}"
        return msg + (" · " + " ".join(counts.notes) if counts.notes else "")

    def _first_cutoff(self) -> datetime:
        return self._clock.now().astimezone(UTC) - timedelta(days=self.settings().first_sync_days)

    def _store(self, rec: GameRecord, counts: _SyncCounts) -> None:
        try:
            parsed = parse_single_pgn(rec.pgn)
        except GameError as e:
            log.info("skipping a synced game: %s", e.reason)
            return
        color = detect_color(rec.white, rec.black, self.usernames())
        _, created = self._repo.add(rec, moves_hash(parsed.start_fen, parsed.moves), color, self._now())
        counts.seen += 1
        counts.new += int(created)

    def _now(self) -> str:
        return self._clock.now().astimezone(UTC).isoformat(timespec="seconds")

    def _fail(self, e: BaseException, platform: str) -> JobFailed:
        kind = self._classify(e)
        if kind == "unauthorized":
            self._account.mark_expired()
            return JobFailed("expired", "Your Lichess sign-in has expired. Sign in again.", retryable=False)
        if kind == "network":
            return JobFailed("offline", f"Couldn't reach {platform}.")
        if kind == "not_found" and platform == "chess.com":
            return JobFailed("not_found", "Your linked chess.com username wasn't found.", retryable=False)
        log.exception("%s sync failed", platform)
        return JobFailed("sync_failed", f"The {platform} sync failed.")

    def _sync_lichess(self, counts: _SyncCounts, progress: ProgressFn, cancel: CancelToken) -> None:
        account, token = self._account.account_id(), self._account.token()
        if not account or not token:
            return
        state = self._sync.get("lichess")
        if state is not None and state.username.lower() != account.lower():
            state = None  # another account signed in: start over for this one
        since = _ms(state.last_sync_at) if state else None
        first = since is None
        if first:
            since = int(self._first_cutoff().timestamp() * 1000)
        limit = self.settings().first_sync_max if first else LATER_SYNC_MAX
        newest = since or 0
        progress(None, "Syncing your Lichess games…")
        try:
            for data in self._lichess.user_games(token, account, since_ms=since, max_games=limit):
                cancel.raise_if_cancelled()
                created = data.get("createdAt")
                if isinstance(created, int) and not isinstance(created, bool):
                    newest = max(newest, created)
                try:
                    rec = parse_lichess_game(data)
                except Skip:
                    continue
                self._store(rec, counts)
                progress(None, f"Syncing your Lichess games… {counts.seen}")
        except (JobFailed, JobCancelled):
            raise
        except Exception as e:
            raise self._fail(e, "Lichess") from None
        last = datetime.fromtimestamp((newest + 1) / 1000, UTC).isoformat(timespec="milliseconds")
        self._sync.put(SyncState("lichess", account, last, None, {}))

    def _sync_chesscom(self, counts: _SyncCounts, progress: ProgressFn, cancel: CancelToken) -> None:
        username = self.settings().chesscom_username
        if not username:
            return
        state = self._sync.get("chesscom")
        if state is not None and state.username.lower() != username.lower():
            state = None
        first = state is None or state.last_archive is None
        cutoff = self._first_cutoff()
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        etags = dict(state.etags) if state else {}
        progress(None, "Syncing your chess.com games…")
        try:
            archives = self._chesscom.archives(username)
            months = months_to_fetch(
                archives, None if first or state is None else state.last_archive, cutoff.strftime("%Y/%m")
            )
            newest_month = state.last_archive if state else None
            collected = 0
            limit = self.settings().first_sync_max
            for url in months:
                cancel.raise_if_cancelled()
                if etags.get(url) == "gone":
                    continue
                try:
                    archive = self._chesscom.archive(url, etags.get(url))
                except Exception as e:
                    if self._classify(e) == "gone":
                        etags[url] = "gone"  # 410 is permanent (FR-10.7)
                        continue
                    raise
                month = archive_month(url)
                if month and (newest_month is None or month > newest_month):
                    newest_month = month
                if archive.etag:
                    etags[url] = archive.etag
                if archive.status == 304:
                    continue
                for data in sorted(archive.games, key=lambda g: -(g.get("end_time") or 0)):
                    try:
                        rec = parse_archive_game(data)
                    except Skip:
                        continue
                    if (
                        first and rec.played_at is not None and rec.played_at < cutoff_iso
                    ):  # undated: its month is in range
                        continue
                    if first and collected >= limit:
                        break
                    self._store(rec, counts)
                    collected += 1
                    progress(None, f"Syncing your chess.com games… {collected}")
                if first and collected >= limit:
                    break
        except (JobFailed, JobCancelled):
            raise
        except Exception as e:
            raise self._fail(e, "chess.com") from None
        self._sync.put(SyncState("chesscom", username, self._now(), newest_month, etags))

    # ------------------------------------------------------------ library

    def list_games(self, f: LibraryFilter) -> tuple[list[GameRow], int]:
        return self._repo.list(f)

    def get(self, game_id: int) -> GameRow:
        g = self._repo.get(game_id)
        if g is None:
            raise NotFoundError("That game isn't in your library.")
        return g

    def set_user_color(self, game_id: int, color: str) -> None:
        if color not in ("white", "black", "both"):
            raise ValidationError("color must be white, black or both")
        self.get(game_id)
        self._repo.set_user_color(game_id, color)

    def online_url(self, game_id: int) -> str:
        url = self.get(game_id).url
        if not url or not url.startswith(("https://lichess.org/", "https://www.chess.com/", "https://chess.com/")):
            raise NotFoundError("This game has no Lichess or chess.com page.")
        return url

    # ------------------------------------------------------------ one-off imports

    def _save(self, rec: GameRecord, parsed: ParsedGame) -> ImportOutcome:
        color = detect_color(rec.white, rec.black, self.usernames())
        gid, created = self._repo.add(rec, moves_hash(parsed.start_fen, parsed.moves), color, self._now())
        row = self.get(gid)
        return ImportOutcome(
            game_id=gid, created=created, needs_color=row.user_color is None, analyzed=row.analysis_status != "none"
        )

    def import_pgn(self, text: str, source: str = "paste") -> ImportOutcome:
        """A pasted PGN or a file's text (FR-11.2). One game is stored at once; several are listed for
        you to pick from. Malformed or illegal games give a clear error (FR-11.6)."""
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Paste a PGN first.")
        try:
            games = parse_pgn(text)
        except GameError as e:
            raise ValidationError(e.reason, code="bad_pgn") from None
        good = [g for g in games if isinstance(g, ParsedGame)]
        if len(games) == 1:
            if not good:
                raise ValidationError(games[0].reason, code="bad_pgn")  # type: ignore[union-attr]
            return self._save(record_from_parsed(good[0], source), good[0])
        if not good:
            raise ValidationError("None of the games in this file can be imported.", code="bad_pgn")
        with self._lock:
            self._next_token += 1
            token = f"pgn-{self._next_token}"
            self._pending[token] = games
            self._pending_source[token] = source
            while len(self._pending) > PENDING_FILES:
                oldest = next(iter(self._pending))
                self._pending.pop(oldest)
                self._pending_source.pop(oldest, None)
        choices = tuple(
            Choice(i, g.label, None) if isinstance(g, ParsedGame) else Choice(i, f"Game {i + 1}", g.reason)
            for i, g in enumerate(games)
        )
        return ImportOutcome(choices=choices, token=token)

    def pick(self, token: str, index: int) -> ImportOutcome:
        with self._lock:
            games = self._pending.get(token)
            source = self._pending_source.get(token, "file")
        if games is None:
            raise NotFoundError("That file's game list has expired. Open the file again.")
        if not isinstance(index, int) or not 0 <= index < len(games):
            raise ValidationError("pick a game from the list")
        g = games[index]
        if isinstance(g, GameError):
            raise ValidationError(g.reason, code="bad_pgn")
        return self._save(record_from_parsed(g, source), g)

    def import_file(self, path: Path) -> ImportOutcome:
        try:
            size = path.stat().st_size
        except OSError:
            raise NotFoundError("That file can't be opened.") from None
        if size > MAX_PGN_BYTES:
            raise ValidationError(f"That file is larger than {MAX_PGN_BYTES // (1024 * 1024)} MB.")
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            raise NotFoundError("That file can't be read.") from None
        return self.import_pgn(text, source="file")

    def start_url_import(self, url: str, chesscom_username: str | None = None) -> str:
        """A Lichess or chess.com game URL (FR-11.3, FR-11.4), as a job: it may take several requests."""
        if not isinstance(url, str):
            raise ValidationError("Paste a game URL.")
        lichess_id = parse_lichess_url(url)
        chesscom = parse_chesscom_url(url)
        if lichess_id is None and chesscom is None:
            raise ValidationError("That isn't a Lichess or chess.com game URL.", code="bad_url")
        username = None
        if chesscom is not None:
            username = username_from(chesscom_username) if chesscom_username else self.settings().chesscom_username
            if not username or not valid_username(username):
                raise ValidationError(
                    "To find a chess.com game, the app needs your chess.com username.", code="chesscom_username_needed"
                )

        with self._lock:
            self._next_token += 1
            ticket = f"url-{self._next_token}"

        def run(progress: ProgressFn, cancel: CancelToken) -> str:
            if lichess_id is not None:
                outcome = self._import_lichess(lichess_id, progress)
            else:
                assert chesscom is not None and username is not None
                outcome = self._import_chesscom(chesscom[1], username, progress, cancel)
            with self._lock:
                self._url_results[ticket] = outcome
            return "Game imported"

        job_id = self._runner.submit(URL_JOB, run)
        with self._lock:
            self._url_tickets[job_id] = ticket
        return job_id

    def url_result(self, job_id: str) -> ImportOutcome | None:
        with self._lock:
            ticket = self._url_tickets.get(job_id)
            return self._url_results.get(ticket) if ticket else None

    def _import_lichess(self, game_id: str, progress: ProgressFn) -> ImportOutcome:
        progress(None, "Fetching the game from Lichess…")
        try:
            data = self._lichess.export_game(self._account.token(), game_id)
        except Exception as e:
            kind = self._classify(e)
            if kind == "not_found":
                raise JobFailed("not_found", "Lichess has no game with that URL.", retryable=False) from None
            if kind == "unauthorized":  # a stale token: the game is public, so try once without it
                try:
                    data = self._lichess.export_game(None, game_id)
                except Exception:
                    raise JobFailed("offline", "Couldn't fetch the game from Lichess.") from None
            elif kind == "network":
                raise JobFailed("offline", "Couldn't reach Lichess.") from None
            else:
                raise
        try:
            rec = parse_lichess_game(data)
            parsed = parse_single_pgn(rec.pgn)
        except Skip:
            raise JobFailed("variant", "Only standard chess games can be reviewed.", retryable=False) from None
        except GameError as e:
            raise JobFailed("bad_pgn", e.reason, retryable=False) from None
        return self._save(rec, parsed)

    def _import_chesscom(self, game_id: str, username: str, progress: ProgressFn, cancel: CancelToken) -> ImportOutcome:
        not_found = JobFailed(
            "not_found",
            f"That game isn't in {username}'s last {URL_SEARCH_MONTHS} months of games. "
            "Paste its PGN instead (on chess.com: Share → PGN).",
            retryable=False,
        )
        try:
            archives = self._chesscom.archives(username)
            months = months_to_fetch(archives, None, None)[:URL_SEARCH_MONTHS]
            for n, url in enumerate(months, 1):
                cancel.raise_if_cancelled()
                progress(n / max(1, len(months)), f"Searching {username}'s chess.com games… month {n} of {len(months)}")
                try:
                    archive = self._chesscom.archive(url, None)
                except Exception as e:
                    if self._classify(e) == "gone":
                        continue
                    raise
                for data in archive.games:
                    if game_id_from_url(data.get("url") if isinstance(data.get("url"), str) else None) != game_id:
                        continue
                    try:
                        rec = parse_archive_game(data)
                        parsed = parse_single_pgn(rec.pgn)
                    except Skip:
                        raise JobFailed(
                            "variant", "Only standard chess games can be reviewed.", retryable=False
                        ) from None
                    except GameError as e:
                        raise JobFailed("bad_pgn", e.reason, retryable=False) from None
                    return self._save(rec, parsed)
        except (JobFailed, JobCancelled):
            raise
        except Exception as e:
            kind = self._classify(e)
            if kind == "not_found":
                raise JobFailed(
                    "not_found", f"There's no chess.com player called {username}.", retryable=False
                ) from None
            if kind == "network":
                raise JobFailed("offline", "Couldn't reach chess.com.") from None
            raise
        raise not_found
