"""Lichess studies (v0.14, REQUIREMENTS §19): add, keep, update and work through saved copies.

- **Finding:** a pasted link or ID (FR-13.5), Studies by author (FR-13.5a), the starter list (FR-13.6) and the Lichess
  window (FR-13.3, 13.4) all end in `add`, which checks the address before any request.
- **Downloading** (FR-13.7) runs as a job, one request at a time. It asks without your token first; only if Lichess
  refuses (403) and your sign-in has `study:read` does it ask again with the token. A sign-in from before v0.14 lacks
  that scope, so the error says to sign in again.
- **Your copy** is stored checked (core/study_pgn.py) and re-checked when read. It works offline and stays if the author
  deletes the study. **Check for updates** never replaces it without your OK.
- **Your place, finished chapters and hearts** are local only (FR-13.9, 13.10); nothing is ever sent to Lichess.
- **Study text never goes to an LLM** (FR-13.12): this service has no LLM dependency at all.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Any, Literal, Protocol

import chess

from weaksquare.adapters.db.repos.studies import ChapterRow, StudiesRepo, StudyRow, chapter_key
from weaksquare.core.clock import Clock
from weaksquare.core.errors import AppError, NotFoundError, ValidationError
from weaksquare.core.repertoire import NewMove, check_color, is_your_turn
from weaksquare.core.study_links import StudyRef, clean_username, is_study_id, parse_study_ref, ref_from_ids
from weaksquare.core.study_pgn import (
    ChapterDiff,
    Study,
    diff_chapters,
    fingerprint,
    follow,
    node_from_json,
    node_to_json,
    parse_path,
    parse_study,
)
from weaksquare.core.study_repertoire import Choice, Conflict, plan_add, resolve, study_moves
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

ADD_JOB = "study_add"
UPDATE_JOB = "study_update"
STUDY_READ = "study:read"

Filter = Literal["all", "favorites", "in_progress", "finished"]


class StudiesClient(Protocol):
    def study_pgn(self, study_id: str, token: str | None = None) -> str: ...
    def studies_by(self, username: str) -> Iterator[Any]: ...


class Repertoire(Protocol):
    """The two things FR-13.11 needs from the repertoire (services/repertoire.py)."""

    def edges(self, color: object) -> list[Any]: ...
    def add_study_moves(self, color: object, moves: Sequence[NewMove], mains: Sequence[tuple[str, str]]) -> Any: ...


class Tokens(Protocol):
    def token(self) -> str | None: ...
    def has_scope(self, scope: str) -> bool: ...


@dataclass(frozen=True)
class StarterEntry:
    """FR-13.6: one starter-list entry. Only a link (from the ID), a title, an author and an opening tag."""

    study_id: str
    title: str
    author: str
    opening: str


STARTER_FIELDS = frozenset({"study_id", "title", "author", "opening"})


def load_starter(text: str) -> list[StarterEntry]:
    """The bundled starter list (`study_starter.json`). Strict: any other field, a bad ID or author, or a duplicate is
    an error, so study content can never slip into the shipped file (FR-13.6)."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("the starter list must be a JSON list")
    out: list[StarterEntry] = []
    seen: set[str] = set()
    for i, e in enumerate(data):
        if not isinstance(e, dict) or set(e) != STARTER_FIELDS:
            raise ValueError(f"entry {i}: needs exactly {sorted(STARTER_FIELDS)}")
        if not all(isinstance(e[k], str) and 0 < len(e[k]) <= 120 for k in STARTER_FIELDS):
            raise ValueError(f"entry {i}: every field is a short string")
        if not is_study_id(e["study_id"]) or e["study_id"] in seen:
            raise ValueError(f"entry {i}: bad or repeated study ID")
        if clean_username(e["author"]) != e["author"]:
            raise ValueError(f"entry {i}: bad author")
        seen.add(e["study_id"])
        out.append(StarterEntry(e["study_id"], e["title"], e["author"], e["opening"]))
    return out


@dataclass(frozen=True)
class AddResult:
    study_id: str
    chapter_key: str | None  # the chapter a chapter link pointed at, if it exists
    already_saved: bool


@dataclass(frozen=True)
class PendingUpdate:
    study: Study
    private: bool
    diff: ChapterDiff


@dataclass(frozen=True)
class RepertoirePreview:
    """FR-13.11: what Add to my repertoire would do. Nothing is saved until you confirm."""

    id: str
    study_id: str
    color: str
    side_lines: bool
    chapters: list[str]  # the chapters whose moves were looked at
    skipped: list[str]  # chapters that can't add moves (text, or rejected), with why
    yours: int  # new moves for your side
    theirs: int  # new replies for the other side
    already: int  # moves you already have
    unreachable: int  # moves that can't join a repertoire starting from the first move
    conflicts: list[Conflict]
    candidates: list[NewMove]


@dataclass(frozen=True)
class StudyErrors:
    """The HTTP adapter's error types and helpers (kept out of this module's imports)."""

    status_of: Callable[[BaseException], int | None]
    is_network_error: Callable[[BaseException], bool]
    is_rate_limited: Callable[[BaseException], bool]


class StudiesService:
    def __init__(
        self,
        repo: StudiesRepo,
        client: StudiesClient,
        tokens: Tokens,
        runner: JobRunner,
        clock: Clock,
        errors: StudyErrors,
        starter: Callable[[], list[StarterEntry]] = list,
        repertoire: Repertoire | None = None,
    ) -> None:
        self._starter = starter
        self._repertoire = repertoire
        self._previews: dict[str, RepertoirePreview] = {}
        self._next_preview = 0
        self._repo = repo
        self._client = client
        self._tokens = tokens
        self._runner = runner
        self._clock = clock
        self._errors = errors
        self._net = threading.Lock()  # one request to Lichess at a time (FR-13.7)
        self._lock = threading.Lock()
        self._results: dict[str, dict[str, AddResult]] = {}
        self._pending: dict[str, PendingUpdate] = {}

    def _now(self) -> str:
        return self._clock.now().astimezone(UTC).isoformat(timespec="seconds")

    # ---- adding (FR-13.4, 13.5, 13.5a, 13.6) -------------------------------------------------------------------------
    @staticmethod
    def parse(text: object) -> StudyRef:
        """A pasted link, chapter link or ID. Anything else is refused here, before any request (FR-13.5)."""
        ref = parse_study_ref(text)
        if ref is None:
            raise ValidationError(
                "That isn't a Lichess study link. Paste an address like https://lichess.org/study/AbCd1234, or just "
                "its 8-character ID.",
                code="not_a_study",
            )
        return ref

    def add(self, ref: StudyRef) -> str:
        """Download and save a study in a job. A study you already have isn't downloaded again; use Check for updates."""
        holder: dict[str, AddResult] = {}
        if self._repo.get(ref.study_id) is not None:
            job = self._runner.submit(ADD_JOB, lambda p, c: self._already_saved(ref, holder))
        else:
            job = self._runner.submit(ADD_JOB, lambda p, c: self._add_job(ref, p, c, holder))
        with self._lock:  # filed before the UI can ask: it only learns the job ID from this return
            self._results[job] = holder
            while len(self._results) > 50:
                self._results.pop(next(iter(self._results)))
        return job

    def add_text(self, text: object) -> str:
        return self.add(self.parse(text))

    def add_ids(self, study: object, chapter: object = None) -> str:
        ref = ref_from_ids(study, chapter)
        if ref is None:
            raise ValidationError("That isn't a Lichess study ID.", code="not_a_study")
        return self.add(ref)

    def add_result(self, job_id: str) -> AddResult | None:
        """The study an add job saved (or found already saved), once it's done."""
        with self._lock:
            holder = self._results.get(job_id)
        return holder.get("result") if holder else None

    def _already_saved(self, ref: StudyRef, holder: dict[str, AddResult]) -> str:
        holder["result"] = AddResult(ref.study_id, self._chapter_key(ref), True)
        return "Already in My studies"

    def _add_job(self, ref: StudyRef, progress: ProgressFn, cancel: CancelToken, holder: dict[str, AddResult]) -> str:
        progress(None, "Downloading the study from Lichess…")
        pgn, private = self._download(ref.study_id)
        cancel.raise_if_cancelled()
        progress(None, "Checking every move…")
        study = self._parse(ref.study_id, pgn)
        self._repo.save(study, self._now(), private=private)
        holder["result"] = AddResult(study.study_id, self._chapter_key(ref), False)
        rejected = len(study.chapters) - len(study.usable)
        n = len(study.chapters)
        msg = f"Added “{study.title}” ({n} chapter{'s' if n != 1 else ''})"
        if rejected:
            msg += f"; {rejected} couldn't be used"
        log.info("study %s added: %d chapters, %d rejected, private=%s", study.study_id, n, rejected, private)
        return msg

    def _chapter_key(self, ref: StudyRef) -> str | None:
        if ref.chapter_id is None:
            return None
        rows = self._repo.chapters(ref.study_id)
        return ref.chapter_id if any(r.key == ref.chapter_id and r.rejected is None for r in rows) else None

    def _download(self, study_id: str) -> tuple[str, bool]:
        """The PGN, and whether it needed your sign-in (FR-13.7: never the token unless Lichess refuses without it)."""
        with self._net:
            try:
                return self._client.study_pgn(study_id), False
            except Exception as e:
                status = self._errors.status_of(e)
                if status != 403:
                    raise self._job_error(e) from None
            token = self._tokens.token()
            if not token:
                raise JobFailed(
                    "study_private",
                    "This study is private. If it's yours, or you're a member, sign in with Lichess and try again. "
                    "Otherwise its author needs to make it public or unlisted.",
                    retryable=False,
                )
            if not self._tokens.has_scope(STUDY_READ):
                raise JobFailed(
                    "study_scope",
                    "This study is private. Sign in again to allow reading your private studies: your current "
                    "sign-in is from before WeakSquare could read studies.",
                    retryable=False,
                )
            try:
                return self._client.study_pgn(study_id, token=token), True
            except Exception as e:
                if self._errors.status_of(e) in (401, 403):
                    raise JobFailed(
                        "study_forbidden",
                        "Lichess won't share this study with your account. Only its owner and members can read a "
                        "private study.",
                        retryable=False,
                    ) from None
                raise self._job_error(e) from None

    def _job_error(self, e: BaseException) -> JobFailed:
        status = self._errors.status_of(e)
        if status == 404:
            return JobFailed("study_not_found", "Lichess has no study with that ID. It may have been deleted.", False)
        if self._errors.is_rate_limited(e):
            return JobFailed("rate_limited", "Lichess asked WeakSquare to slow down. Try again in a minute.")
        if status is not None and status >= 500:
            return JobFailed("lichess_trouble", "Lichess is having trouble right now. Try again later.")
        if self._errors.is_network_error(e):
            return JobFailed("offline", "Lichess couldn't be reached. Check your connection and try again.")
        log.warning("study download failed (%s, HTTP %s)", type(e).__name__, status)
        return JobFailed("study_download_failed", "The study couldn't be downloaded from Lichess. Try again later.")

    @staticmethod
    def _parse(study_id: str, pgn: str) -> Study:
        try:
            study = parse_study(study_id, pgn)
        except ValueError:
            raise JobFailed(
                "study_empty", "Lichess sent a study with no chapters WeakSquare could read.", False
            ) from None
        if not study.usable:
            raise JobFailed(
                "study_unusable",
                "None of this study's chapters could be used (only standard chess with legal moves is supported).",
                False,
            )
        return study

    def starter_list(self) -> list[StarterEntry]:
        """FR-13.6: shipped with the app; a study is downloaded only when you pick it."""
        try:
            return self._starter()
        except (OSError, ValueError):
            log.exception("the starter list couldn't be read")
            return []

    # ---- Studies by author (FR-13.5a) -------------------------------------------------------------------------
    def studies_by(self, text: object) -> list[dict[str, Any]]:
        name = clean_username(text)
        if name is None:
            raise ValidationError("That isn't a Lichess username.", code="bad_username")
        saved = {s.id for s in self._repo.all()}
        try:
            with self._net:
                found = list(self._client.studies_by(name))
        except Exception as e:
            status = self._errors.status_of(e)
            if status == 404:
                raise NotFoundError(f"Lichess has no user called {name}.", code="user_not_found") from None
            if self._errors.is_rate_limited(e):
                raise AppError("Lichess asked WeakSquare to slow down. Try again in a minute.", code="rate_limited",
                               retryable=True) from None  # fmt: skip
            if self._errors.is_network_error(e):
                raise AppError("Lichess couldn't be reached. Check your connection.", code="offline",
                               retryable=True) from None  # fmt: skip
            raise AppError("Lichess couldn't list that author's studies. Try again later.", code="author_failed",
                           retryable=True) from None  # fmt: skip
        return [
            {
                "study_id": s.study_id,
                "name": s.name,
                "created_ms": s.created_ms,
                "updated_ms": s.updated_ms,
                "saved": s.study_id in saved,
            }
            for s in found
        ]

    # ---- My studies (FR-13.1, 13.9) ---------------------------------------------------------------------------------
    def list_studies(self, which: Filter = "all") -> list[StudyRow]:
        rows = self._repo.all()
        if which == "favorites":
            return [r for r in rows if r.hearted]
        if which == "in_progress":
            return [r for r in rows if _in_progress(r)]
        if which == "finished":
            return [r for r in rows if _finished(r)]
        return rows

    def get(self, study_id: str) -> tuple[StudyRow, list[ChapterRow]]:
        row = self._repo.get(self._id(study_id))
        if row is None:
            raise NotFoundError("That study isn't in My studies.", code="study_not_found")
        return row, self._repo.chapters(row.id)

    def heart(self, study_id: str, hearted: bool) -> None:
        self.get(study_id)
        self._repo.set_heart(study_id, bool(hearted))

    def delete(self, study_id: str) -> None:
        self.get(study_id)
        self._repo.delete(study_id)
        with self._lock:
            self._pending.pop(study_id, None)

    # ---- one chapter, your place (FR-13.8, 13.10) ---------------------------------------------------------------------
    def chapter(self, study_id: str, key: str) -> tuple[ChapterRow, dict[str, Any]]:
        """A chapter and its move tree, re-checked move by move (a damaged row can't put an illegal move on the board)."""
        _, chapters = self.get(study_id)
        row = next((c for c in chapters if c.key == key), None)
        if row is None:
            raise NotFoundError("That chapter isn't in this study any more.", code="chapter_not_found")
        if row.rejected is not None:
            raise ValidationError(f"This chapter {row.rejected}.", code="chapter_rejected")
        if row.text_only:
            return row, {"comment": row.tree.get("comment", "")} if isinstance(row.tree, dict) else {}
        try:
            tree = node_to_json(node_from_json(row.tree, chess.Board(row.start_fen)))
        except ValueError:
            log.error("study %s chapter %s failed its re-check", study_id, key)
            raise AppError("This chapter's saved copy is damaged. Delete the study and add it again.",
                           code="chapter_damaged") from None  # fmt: skip
        return row, tree

    def set_place(self, study_id: str, key: str, path: object) -> None:
        row, tree = self.chapter(study_id, key)
        moves = parse_path(path)
        if moves is None:
            raise ValidationError("bad path", code="bad_path")
        if not row.text_only and follow(node_from_json(tree, chess.Board(row.start_fen)), moves) is None:
            raise ValidationError("That move isn't in this chapter.", code="bad_path")
        self._repo.set_place(study_id, key, " ".join(moves), self._now())

    def set_done(self, study_id: str, key: str, done: bool) -> None:
        self.chapter(study_id, key)
        self._repo.set_done(study_id, key, bool(done), self._now())

    def restart(self, study_id: str) -> None:
        """Restart the study: your place and finished chapters are cleared (FR-13.10)."""
        self.get(study_id)
        self._repo.clear_place(study_id)
        self._repo.clear_done(study_id)

    def continue_target(self, study_id: str) -> tuple[str, str]:
        """Where **Continue** goes: your saved place, else the first unfinished usable chapter, else the first one."""
        row, chapters = self.get(study_id)
        usable = [c for c in chapters if c.rejected is None]
        if not usable:
            raise ValidationError("None of this study's chapters can be used.", code="study_unusable")
        if row.place_key and any(c.key == row.place_key for c in usable):
            return row.place_key, row.place_path
        nxt = next((c for c in usable if not c.done), usable[0])
        return nxt.key, ""

    # ---- Add to my repertoire (FR-13.11) -----------------------------------------------------------------------
    def repertoire_preview(
        self, study_id: str, chapter_key: str | None, color: object, side_lines: object
    ) -> RepertoirePreview:
        """The moves a chapter (or the whole study, with no chapter) would add for `color`, conflicts with your moves,
        and what can't join. Nothing is saved."""
        if self._repertoire is None:  # pragma: no cover - always wired in the app
            raise AppError("The repertoire isn't available.")
        c = check_color(color)
        if not isinstance(side_lines, bool):
            raise ValidationError("bad side_lines")
        _, rows = self.get(study_id)
        picked = [r for r in rows if chapter_key is None or r.key == chapter_key]
        if chapter_key is not None and not picked:
            raise NotFoundError("That chapter isn't in this study any more.", code="chapter_not_found")
        candidates: list[NewMove] = []
        seen: set[tuple[str, str]] = set()
        used, skipped = [], []
        for r in picked:
            if r.rejected is not None:
                skipped.append(f"{r.title} (it {r.rejected})")
                continue
            if r.text_only or r.move_count == 0:
                skipped.append(f"{r.title} (no moves)")
                continue
            root = node_from_json(r.tree, chess.Board(r.start_fen))
            for m in study_moves(root, r.start_fen, side_lines):
                if (m.position_key, m.move_uci) not in seen:
                    seen.add((m.position_key, m.move_uci))
                    candidates.append(m)
            used.append(r.title)
        plan = plan_add(self._repertoire.edges(c), candidates, c)
        yours = sum(1 for m in plan.new if is_your_turn(m.position_key, c))
        with self._lock:
            self._next_preview += 1
            pid = f"study-rep-{self._next_preview}"
            preview = RepertoirePreview(
                pid, study_id, c, side_lines, used, skipped, yours, len(plan.new) - yours, plan.already,
                plan.unreachable, plan.conflicts, candidates,
            )  # fmt: skip
            self._previews = {pid: preview}  # one open preview at a time
        return preview

    def repertoire_save(self, preview_id: object, choices: object) -> Any:
        """Store the previewed moves with `source = study`, applying your choice at each conflict ("mine", the default,
        or "study"). The moves are drilled in Practice like any other line (FR-12.9)."""
        if self._repertoire is None:  # pragma: no cover
            raise AppError("The repertoire isn't available.")
        with self._lock:
            preview = self._previews.pop(preview_id, None) if isinstance(preview_id, str) else None
        if preview is None:
            raise ValidationError("That preview has expired. Open Add to my repertoire again.", code="no_preview")
        if not isinstance(choices, dict):
            raise ValidationError("bad choices")
        keys = {cf.position_key for cf in preview.conflicts}
        picked: dict[str, Choice] = {}
        for k, v in choices.items():
            if k not in keys or v not in ("mine", "study"):
                raise ValidationError("bad choice")
            picked[k] = v
        to_add, mains = resolve(self._repertoire.edges(preview.color), preview.candidates, preview.color, picked)
        result = self._repertoire.add_study_moves(preview.color, to_add, mains)
        log.info("study %s: %d repertoire moves added for %s", preview.study_id, len(to_add), preview.color)
        return result

    def discard_repertoire_preview(self) -> None:
        with self._lock:
            self._previews.clear()

    # ---- Check for updates (FR-13.7) -----------------------------------------------------------------------------
    def check_updates(self, study_id: str) -> str:
        row, _ = self.get(study_id)
        return self._runner.submit(UPDATE_JOB, lambda p, c: self._check_job(row, p, c))

    def _check_job(self, row: StudyRow, progress: ProgressFn, cancel: CancelToken) -> str:
        progress(None, "Downloading the latest version from Lichess…")
        pgn, private = self._download(row.id)
        cancel.raise_if_cancelled()
        study = self._parse(row.id, pgn)
        self._repo.touch_checked(row.id, self._now())
        if study.pgn_hash == row.pgn_hash:
            with self._lock:
                self._pending.pop(row.id, None)
            return "No changes: your copy is up to date"
        old = [(c.key, c.title, _row_fingerprint(c)) for c in self._repo.chapters(row.id)]
        new = [(chapter_key(c), c.title, _study_fingerprint(c)) for c in study.chapters]
        diff = diff_chapters(old, new)
        with self._lock:
            self._pending[row.id] = PendingUpdate(study, private, diff)
        if not diff.any and study.title == row.title:
            return "Only small changes: review them before updating"
        return "Changes found: review them before updating"

    def pending_update(self, study_id: str) -> PendingUpdate | None:
        with self._lock:
            return self._pending.get(study_id)

    def apply_update(self, study_id: str) -> None:
        """Replace your copy with the version Check for updates found. Your place is kept if its chapter still exists."""
        with self._lock:
            pending = self._pending.pop(study_id, None)
        if pending is None:
            raise ValidationError("Check for updates first.", code="no_update")
        self._repo.save(pending.study, self._now(), private=pending.private)

    def discard_update(self, study_id: str) -> None:
        with self._lock:
            self._pending.pop(study_id, None)

    @staticmethod
    def _id(study_id: object) -> str:
        if not is_study_id(study_id):
            raise ValidationError("bad study id", code="bad_study_id")
        return str(study_id)


def _in_progress(r: StudyRow) -> bool:
    return (r.place_key is not None or r.done > 0) and not _finished(r)


def _finished(r: StudyRow) -> bool:
    return r.playable > 0 and r.done >= r.playable


def _row_fingerprint(c: ChapterRow) -> str:
    return fingerprint(c.tree, c.mode, c.orientation, c.start_fen, c.text_only, c.rejected)


def _study_fingerprint(c: Any) -> str:
    return fingerprint(node_to_json(c.root), c.mode, c.orientation, c.start_fen, c.text_only, c.rejected)
