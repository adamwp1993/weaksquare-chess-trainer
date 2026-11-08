"""user.db repository for saved Lichess studies, your place and finished chapters (v0.14, FR-13.1, 13.7, 13.9, 13.10)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.study_pgn import Chapter, Study, node_to_json


def chapter_key(chapter: Chapter) -> str:
    return chapter.chapter_id or f"idx:{chapter.index}"


@dataclass(frozen=True)
class StudyRow:
    id: str
    title: str
    author: str | None
    pgn_hash: str
    private: bool
    hearted: bool
    added_at: str
    updated_at: str
    checked_at: str | None
    last_opened_at: str | None
    chapters: int  # all chapters
    playable: int  # chapters that weren't rejected
    done: int  # finished chapters that still exist
    place_key: str | None
    place_path: str


@dataclass(frozen=True)
class ChapterRow:
    study_id: str
    idx: int
    key: str
    title: str
    mode: str
    orientation: str
    start_fen: str
    text_only: bool
    rejected: str | None
    move_count: int
    tree: Any  # parsed JSON; re-checked by the service before use
    done: bool


_STUDY_SELECT = """
SELECT s.id, s.title, s.author, s.pgn_hash, s.private, s.hearted, s.added_at, s.updated_at, s.checked_at,
       s.last_opened_at,
       (SELECT COUNT(*) FROM study_chapters c WHERE c.study_id = s.id),
       (SELECT COUNT(*) FROM study_chapters c WHERE c.study_id = s.id AND c.rejected IS NULL),
       (SELECT COUNT(*) FROM study_chapters_done d JOIN study_chapters c
           ON c.study_id = d.study_id AND c.chapter_key = d.chapter_key AND c.rejected IS NULL
         WHERE d.study_id = s.id),
       p.chapter_key, COALESCE(p.path, '')
FROM studies s LEFT JOIN study_progress p ON p.study_id = s.id
"""


def _study(r: Any) -> StudyRow:
    return StudyRow(
        str(r[0]), str(r[1]), r[2], str(r[3]), bool(r[4]), bool(r[5]), str(r[6]), str(r[7]), r[8], r[9],
        int(r[10]), int(r[11]), int(r[12]), r[13], str(r[14]),
    )  # fmt: skip


def _chapter(r: Any) -> ChapterRow:
    return ChapterRow(
        str(r[0]), int(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), str(r[6]), bool(r[7]), r[8],
        int(r[9]), json.loads(r[10]), bool(r[11]),
    )  # fmt: skip


class StudiesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- studies -----------------------------------------------------------------------------------------------
    def all(self) -> list[StudyRow]:
        with self._db.session() as conn:
            rows = conn.execute(
                _STUDY_SELECT + " ORDER BY COALESCE(s.last_opened_at, s.added_at) DESC, s.title"
            ).fetchall()
        return [_study(r) for r in rows]

    def get(self, study_id: str) -> StudyRow | None:
        with self._db.session() as conn:
            r = conn.execute(_STUDY_SELECT + " WHERE s.id = ?", (study_id,)).fetchone()
        return _study(r) if r else None

    def save(self, study: Study, at: str, *, private: bool) -> None:
        """Add a study, or replace your copy with a newer one (an accepted update). Hearts, the date added, your place
        and finished chapters are kept where the chapter still exists; the rest are dropped."""
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO studies (id, title, author, pgn_hash, private, added_at, updated_at, checked_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET title = excluded.title, author = excluded.author,
                       pgn_hash = excluded.pgn_hash, private = excluded.private, updated_at = excluded.updated_at,
                       checked_at = excluded.checked_at""",
                (study.study_id, study.title, study.author, study.pgn_hash, int(private), at, at, at),
            )
            conn.execute("DELETE FROM study_chapters WHERE study_id = ?", (study.study_id,))
            seen: set[str] = set()
            for c in study.chapters:
                key = chapter_key(c)
                if key in seen:  # Lichess IDs are unique; guard anyway so one odd export can't fail the insert
                    key = f"idx:{c.index}"
                seen.add(key)
                conn.execute(
                    """INSERT INTO study_chapters (study_id, idx, chapter_key, title, mode, orientation, start_fen,
                           text_only, rejected, move_count, tree) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        study.study_id, c.index, key, c.title, c.mode, c.orientation, c.start_fen, int(c.text_only),
                        c.rejected, c.move_count, json.dumps(node_to_json(c.root), separators=(",", ":")),
                    ),
                )  # fmt: skip
            conn.execute(
                "DELETE FROM study_chapters_done WHERE study_id = ? AND chapter_key NOT IN "
                "(SELECT chapter_key FROM study_chapters WHERE study_id = ?)",
                (study.study_id, study.study_id),
            )
            conn.execute(
                "DELETE FROM study_progress WHERE study_id = ? AND chapter_key NOT IN "
                "(SELECT chapter_key FROM study_chapters WHERE study_id = ? AND rejected IS NULL)",
                (study.study_id, study.study_id),
            )

    def touch_checked(self, study_id: str, at: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE studies SET checked_at = ? WHERE id = ?", (at, study_id))

    def delete(self, study_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM studies WHERE id = ?", (study_id,))

    def set_heart(self, study_id: str, hearted: bool) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE studies SET hearted = ? WHERE id = ?", (int(hearted), study_id))

    # ---- chapters ----------------------------------------------------------------------------------------------
    def chapters(self, study_id: str) -> list[ChapterRow]:
        with self._db.session() as conn:
            rows = conn.execute(
                """SELECT c.study_id, c.idx, c.chapter_key, c.title, c.mode, c.orientation, c.start_fen, c.text_only,
                          c.rejected, c.move_count, c.tree, d.done_at IS NOT NULL
                   FROM study_chapters c LEFT JOIN study_chapters_done d
                     ON d.study_id = c.study_id AND d.chapter_key = c.chapter_key
                   WHERE c.study_id = ? ORDER BY c.idx""",
                (study_id,),
            ).fetchall()
        return [_chapter(r) for r in rows]

    # ---- your place and finished chapters ------------------------------------------------------------------------
    def set_place(self, study_id: str, key: str, path: str, at: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO study_progress (study_id, chapter_key, path, updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(study_id) DO UPDATE SET chapter_key = excluded.chapter_key, path = excluded.path,
                       updated_at = excluded.updated_at""",
                (study_id, key, path, at),
            )
            conn.execute("UPDATE studies SET last_opened_at = ? WHERE id = ?", (at, study_id))

    def clear_place(self, study_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM study_progress WHERE study_id = ?", (study_id,))

    def set_done(self, study_id: str, key: str, done: bool, at: str) -> None:
        with self._db.transaction() as conn:
            if done:
                conn.execute(
                    "INSERT OR IGNORE INTO study_chapters_done (study_id, chapter_key, done_at) VALUES (?,?,?)",
                    (study_id, key, at),
                )
            else:
                conn.execute("DELETE FROM study_chapters_done WHERE study_id = ? AND chapter_key = ?", (study_id, key))

    def clear_done(self, study_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM study_chapters_done WHERE study_id = ?", (study_id,))
