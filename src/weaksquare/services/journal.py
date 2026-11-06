"""The training journal (v0.12, REQUIREMENTS §10.12, FR-10.67–10.71): your notes, game reflections and the
automatic daily log, as one timeline. Entries stay on this PC unless you turn on **Include my journal** for one
AI run (FR-10.71), which gets exactly what `prompt_items` returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.daily_log import DayFacts, DayLog, build_day, top_weakness
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.games import GameError, parse_single_pgn
from weaksquare.core.stats import AttemptRow
from weaksquare.core.themes import display_name
from weaksquare.core.urls import is_address, strip_urls

MAX_ENTRY = 5000  # FR-10.67
MAX_KEY = 200
WINDOW_DAYS = 30  # one page of the timeline
PROMPT_ENTRIES = 30  # FR-10.71
PROMPT_ENTRY_CHARS = 1000
KINDS = ("note", "reflection", "log")
WEAKNESS_KINDS = ("missed", "allowed", "habit", "puzzle", "opening", "endgame", "phase", "time")


class Games(Protocol):
    def get(self, game_id: int) -> Any: ...


class Stats(Protocol):
    def attempt_rows_between(self, since: str, until: str) -> list[tuple[AttemptRow, str]]: ...


@dataclass(frozen=True)
class TimelineItem:
    date: str
    entry: Any = None  # EntryRow
    log: DayLog | None = None


@dataclass(frozen=True)
class Timeline:
    items: tuple[TimelineItem, ...]
    window_start: str  # the oldest date this page covers
    older: bool  # a further page has something
    games: tuple[int, ...] = ()  # every game an entry is on, for the Game filter (FR-10.70)


@dataclass(frozen=True)
class PromptItem:
    """One journal entry as FR-10.71 sends it: no date, no game id."""

    text: str  # cut, with web addresses removed
    kind: str
    game: str | None  # a G label of this report's games, never an id
    ply: int | None  # 1-based
    weakness: str | None


def _date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise ValidationError(f"{field} must be a date.")


def _moves_in(game: Any) -> int:
    try:
        return len(parse_single_pgn(game.pgn).moves)
    except GameError:
        return 0


def _id(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be a whole number.")
    return value


class JournalService:
    def __init__(self, repo: Any, log_repo: Any, games: Games, stats: Stats, clock: Clock) -> None:
        self._repo = repo
        self._log = log_repo
        self._games = games
        self._stats = stats
        self._clock = clock

    def _now(self) -> str:
        return self._clock.now().astimezone(UTC).isoformat(timespec="seconds")

    def _today(self) -> date:
        return self._clock.local_date(self._clock.now())

    @staticmethod
    def _text(text: Any) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Write something first.")
        if len(text) > MAX_ENTRY:
            raise ValidationError(f"An entry can be at most {MAX_ENTRY:,} characters.")
        return text.strip()

    @staticmethod
    def _weakness(key: Any) -> str | None:
        if key is None or key == "":
            return None
        if not isinstance(key, str) or len(key) > MAX_KEY:
            raise ValidationError("Unknown weakness.")
        # QA v0.12-B10: a tag goes to the AI with Include my journal, so it can only be a weakness key.
        kind, _, name = key.partition(":")
        if kind not in WEAKNESS_KINDS or not name or any(is_address(w) for w in name.split()):
            raise ValidationError("Unknown weakness.")
        return key

    # ------------------------------------------------------------ entries (FR-10.67, 10.69)

    def add(
        self, text: Any, *, entry_date: Any = None, weakness_key: Any = None, game_id: Any = None, ply: Any = None,
        plan_day_id: Any = None, plan_task_id: Any = None,
    ) -> int:  # fmt: skip
        body = self._text(text)
        gid, at_ply = _id(game_id, "game_id"), _id(ply, "ply")
        day, task = _id(plan_day_id, "plan_day_id"), _id(plan_task_id, "plan_task_id")
        if at_ply is not None and gid is None:
            raise ValidationError("A note on a move needs its game.")
        game = self._games.get(gid) if gid is not None else None
        if gid is not None and game is None:
            raise NotFoundError("That game isn't in your library.")
        if at_ply is not None and not 0 <= at_ply < _moves_in(game):
            raise ValidationError("That move isn't in this game.")
        # QA v0.12-B8: what an entry links to must exist, and its date can't be in the future.
        if day is not None and not self._repo.day_exists(day):
            raise NotFoundError("That plan day doesn't exist.")
        if task is not None and not self._repo.task_exists(task):
            raise NotFoundError("That plan task doesn't exist.")
        when = _date(entry_date, "The date") or self._today().isoformat()
        if when > self._today().isoformat():
            raise ValidationError("A journal entry can't be dated in the future.")
        return int(
            self._repo.add(
                self._now(), when, "reflection" if gid is not None else "note", body, game_id=gid, ply=at_ply,
                weakness_key=self._weakness(weakness_key), plan_day_id=day, plan_task_id=task,
            )
        )  # fmt: skip

    def edit(self, entry_id: Any, text: Any, weakness_key: Any = None) -> None:
        self._entry(entry_id)
        self._repo.update(entry_id, self._now(), self._text(text), self._weakness(weakness_key))

    def delete(self, entry_id: Any) -> None:
        self._entry(entry_id)
        self._repo.delete(entry_id)

    def plan_day_date(self, day_id: int) -> str | None:
        return self._repo.day_date(day_id)

    def get(self, entry_id: Any) -> Any:
        return self._entry(entry_id)

    def _entry(self, entry_id: Any) -> Any:
        found = self._repo.get(_id(entry_id, "entry_id"))
        if found is None:
            raise NotFoundError("That entry isn't in your journal.")
        return found

    def game_notes(self, game_id: Any) -> list[Any]:
        """FR-10.69: a game's notes, with the moves they're on."""
        return list(self._repo.for_game(_id(game_id, "game_id")))

    # ------------------------------------------------------------ the daily log (FR-10.68)

    def day_logs(self, first: date, last: date) -> dict[str, DayLog]:
        """Each day's log in this range of local dates, computed from what's stored. Days with nothing are
        left out."""
        since, until = (first - timedelta(days=1)).isoformat(), (last + timedelta(days=2)).isoformat()
        wanted = {(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)}

        def local(text: str) -> str | None:
            try:
                t = datetime.fromisoformat(text)
            except ValueError:
                return None
            day = self._clock.local_date(t if t.tzinfo else t.replace(tzinfo=UTC)).isoformat()
            return day if day in wanted else None

        def count(times: list[str]) -> dict[str, int]:
            out: dict[str, int] = {}
            for t in times:
                d = local(t)
                if d is not None:
                    out[d] = out.get(d, 0) + 1
            return out

        played = count(self._log.games_played(since, until))
        synced = count(self._log.games_synced(since, until))
        analyzed = count(self._log.games_analyzed(since, until))
        reviewed = count(self._log.games_reviewed(since, until))
        done = count(self._log.plan_tasks_done(since, until))
        tried: dict[str, int] = {}
        found: dict[str, int] = {}
        for r in self._log.retries(since, until):
            d = local(r.at)
            if d is not None:
                tried[d] = tried.get(d, 0) + 1
                found[d] = found.get(d, 0) + int(r.found)
        runs: dict[str, list[str]] = {}
        for f in self._log.reports(since, until):
            d = local(f.at)
            if d is not None:
                runs.setdefault(d, []).append(top_weakness(f.report))
        rows: dict[str, list[AttemptRow]] = {}
        sources: dict[str, list[str]] = {}
        for row, source in self._stats.attempt_rows_between(since, until):
            d = self._clock.local_date(row.finished_at).isoformat() if row.finished_at is not None else None
            if d in wanted:
                rows.setdefault(str(d), []).append(row)
                sources.setdefault(str(d), []).append(source)
        out: dict[str, DayLog] = {}
        for d in wanted:
            log = build_day(
                d, rows.get(d, []), sources.get(d, []), display_name,
                DayFacts(synced.get(d, 0), analyzed.get(d, 0), reviewed.get(d, 0), tried.get(d, 0), found.get(d, 0),
                         done.get(d, 0), tuple(runs.get(d, ())), played.get(d, 0)),
            )  # fmt: skip
            if not log.empty:
                out[d] = log
        return out

    # ------------------------------------------------------------ the timeline (FR-10.70)

    def timeline(self, filters: Any = None) -> Timeline:
        """Your notes, reflections and the daily log, newest first, one window of days at a time. The log
        has no text, game or weakness of its own, so those filters show entries only."""
        f = dict(filters or {})
        known = {"kinds", "game_id", "weakness_key", "date_from", "date_to", "query", "before"}
        if not isinstance(filters or {}, dict) or set(f) - known:
            raise ValidationError("Unknown journal filter.")
        kinds = f.get("kinds") or []
        if not isinstance(kinds, list) or set(kinds) - set(KINDS):
            raise ValidationError("Unknown entry type.")
        query = f.get("query")
        if query is not None and not isinstance(query, str):
            raise ValidationError("The search must be text.")
        query = (query or "").strip() or None
        gid = _id(f.get("game_id"), "game_id")
        weakness = self._weakness(f.get("weakness_key"))
        date_from = _date(f.get("date_from"), "The start date")
        date_to = _date(f.get("date_to"), "The end date")
        before = _date(f.get("before"), "before")
        today = self._today()
        last = min(date.fromisoformat(date_to), today) if date_to else today  # QA v0.12-B19: nothing is dated later
        if before is not None:
            last = min(last, date.fromisoformat(before) - timedelta(days=1))
        want = set(kinds) or set(KINDS)
        entry_kinds = [k for k in ("note", "reflection") if k in want]
        floor = date.fromisoformat(date_from) if date_from else None
        games = tuple(self._repo.games_with_entries())
        # QA v0.12-B7: a search or a filter that only entries can match looks at all of them. Only the daily log,
        # which is computed day by day, comes a window at a time.
        if gid or weakness or query or "log" not in want:
            # QA v0.12-B17: with only the daily log picked, no entry qualifies (an empty list means "any" to the repo).
            found = (
                self._repo.search(
                    kinds=entry_kinds, game_id=gid, weakness_key=weakness, date_from=date_from,
                    date_to=last.isoformat(), query=query,
                )
                if entry_kinds
                else []
            )  # fmt: skip
            return Timeline(tuple(TimelineItem(e.entry_date, entry=e) for e in found), date_from or "", False, games)
        first = last - timedelta(days=WINDOW_DAYS - 1)
        if floor is not None and first < floor:
            first = floor
        older = self._has_older(first, floor)
        items: list[TimelineItem] = []
        if first <= last and entry_kinds:
            for e in self._repo.search(
                kinds=entry_kinds, game_id=gid, weakness_key=weakness, date_from=first.isoformat(),
                date_to=last.isoformat(), query=query,
            ):  # fmt: skip
                items.append(TimelineItem(e.entry_date, entry=e))
        if first <= last and "log" in want:
            for d, log in self.day_logs(first, last).items():
                items.append(TimelineItem(d, log=log))
        # Newest day first; within a day, your own words above the log, newest entry first.
        items.sort(key=lambda i: (i.date, i.log is None, i.entry.id if i.entry is not None else 0), reverse=True)
        return Timeline(tuple(items), first.isoformat(), older, games)

    def _has_older(self, first: date, floor: date | None) -> bool:
        """Is there anything before this window to page back to? (QA v0.12-B7.)"""
        if floor is not None and first <= floor:
            return False
        entry = self._repo.earliest_date()
        if entry is not None and entry < first.isoformat():
            return True
        logged = self._log.earliest()  # a stored time: QA v0.12-B19, sorted onto your local day like the log itself
        if logged is None:
            return False
        try:
            t = datetime.fromisoformat(logged)
        except ValueError:
            return False
        return self._clock.local_date(t if t.tzinfo else t.replace(tzinfo=UTC)) < first

    # ------------------------------------------------------------ Include my journal (FR-10.71)

    def prompt_items(self, labels: dict[int, str], since: str | None) -> list[PromptItem]:
        """Exactly what a run with Include my journal sends, and what its preview shows. `labels` maps the
        report's games to their G labels; a game outside the report goes with no reference."""
        out: list[PromptItem] = []
        for e in self._repo.for_prompt(list(labels), since, PROMPT_ENTRIES):
            text = strip_urls(e.text).strip()[:PROMPT_ENTRY_CHARS].strip()
            if not text:
                continue
            label = labels.get(e.game_id) if e.game_id is not None else None
            out.append(
                PromptItem(text, e.kind, label, e.ply + 1 if label and e.ply is not None else None, e.weakness_key)
            )
        return out
