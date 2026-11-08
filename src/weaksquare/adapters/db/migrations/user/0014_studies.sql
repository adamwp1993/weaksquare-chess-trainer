-- v0.14: Lichess studies (REQUIREMENTS §19, ARCHITECTURE §7). Never edit this file once applied; add 0015_… instead.

-- Your saved copy of each study (FR-13.7). It stays if its author deletes it, and changes only when you accept an
-- update. `pgn_hash` is the SHA-256 of the downloaded PGN, so Check for updates can tell nothing changed.
-- `private` is 1 when Lichess only gave it to your sign-in (FR-13.7), so updates send the token again.
CREATE TABLE studies (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    author         TEXT,
    pgn_hash       TEXT NOT NULL,
    private        INTEGER NOT NULL DEFAULT 0,
    hearted        INTEGER NOT NULL DEFAULT 0,
    added_at       TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    checked_at     TEXT,
    last_opened_at TEXT
);

-- Each chapter as parsed and checked (core/study_pgn.py). `tree` is the move tree as JSON, re-checked when read.
-- A rejected chapter keeps its title and reason and has an empty tree. `chapter_key` is Lichess's chapter ID, or
-- `idx:<n>` when Lichess sent none; your place and finished chapters refer to it, so they survive an update.
CREATE TABLE study_chapters (
    study_id    TEXT NOT NULL REFERENCES studies (id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    chapter_key TEXT NOT NULL,
    title       TEXT NOT NULL,
    mode        TEXT NOT NULL,
    orientation TEXT NOT NULL,
    start_fen   TEXT NOT NULL,
    text_only   INTEGER NOT NULL DEFAULT 0,
    rejected    TEXT,
    move_count  INTEGER NOT NULL DEFAULT 0,
    tree        TEXT NOT NULL,
    PRIMARY KEY (study_id, idx),
    UNIQUE (study_id, chapter_key)
);

-- Your place in each study (FR-13.10): the chapter and the moves from its start (UCI, space-separated).
CREATE TABLE study_progress (
    study_id    TEXT PRIMARY KEY REFERENCES studies (id) ON DELETE CASCADE,
    chapter_key TEXT NOT NULL,
    path        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);

-- Chapters you've finished (FR-13.1's "Chapter 3 of 8" and the finished filter).
CREATE TABLE study_chapters_done (
    study_id    TEXT NOT NULL REFERENCES studies (id) ON DELETE CASCADE,
    chapter_key TEXT NOT NULL,
    done_at     TEXT NOT NULL,
    PRIMARY KEY (study_id, chapter_key)
);
