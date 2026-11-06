-- v0.13: the opening trainer (REQUIREMENTS §18, ARCHITECTURE §7). Never edit this file once applied; add
-- 0014_… instead.

-- The bundled opening book (FR-12.1). Rebuilt when the bundled version changes; nothing of yours lives here.
CREATE TABLE opening_book (
    id        INTEGER PRIMARY KEY,
    eco       TEXT NOT NULL,
    name      TEXT NOT NULL,
    family    TEXT NOT NULL,
    pgn       TEXT NOT NULL,
    moves_uci TEXT NOT NULL,
    final_key TEXT NOT NULL
);

CREATE INDEX opening_book_family ON opening_book (family);
CREATE INDEX opening_book_final ON opening_book (final_key);

-- Every position a book line passes through, for matching by position, not move order (FR-12.1).
-- `move_uci` is the line's next move; it's empty at the line's last position.
CREATE TABLE opening_book_positions (
    line_id      INTEGER NOT NULL REFERENCES opening_book (id) ON DELETE CASCADE,
    ply          INTEGER NOT NULL,
    position_key TEXT NOT NULL,
    move_uci     TEXT NOT NULL,
    PRIMARY KEY (line_id, ply)
);

CREATE INDEX opening_book_positions_key ON opening_book_positions (position_key);

-- The openings you picked, so a session or a stat can name one (FR-12.10, 12.11).
CREATE TABLE repertoire_openings (
    id         INTEGER PRIMARY KEY,
    color      TEXT NOT NULL,
    name       TEXT NOT NULL,
    eco        TEXT NOT NULL,
    root_key   TEXT NOT NULL,
    root_moves TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (color, root_key)
);

-- Your repertoire (FR-12.4): moves are edges between positions, so a transposition reuses its position.
-- `source` has no CHECK so later sources (study, v0.14) need no table rebuild.
CREATE TABLE repertoire_nodes (
    id           INTEGER PRIMARY KEY,
    color        TEXT NOT NULL,
    position_key TEXT NOT NULL,
    move_uci     TEXT NOT NULL,
    san          TEXT NOT NULL,
    source       TEXT NOT NULL,
    is_main      INTEGER NOT NULL DEFAULT 0,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    UNIQUE (color, position_key, move_uci)
);

CREATE INDEX repertoire_nodes_position ON repertoire_nodes (color, position_key);

-- Overviews and move explanations: ask once (FR-12.7). `move_uci` is empty for an overview. `sources_json`
-- lists the Wikibooks pages and revisions the note used (FR-12.15).
CREATE TABLE opening_notes (
    id             INTEGER PRIMARY KEY,
    position_key   TEXT NOT NULL,
    move_uci       TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    prompt_version INTEGER NOT NULL,
    body_json      TEXT NOT NULL,
    sources_json   TEXT NOT NULL DEFAULT '[]',
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd       REAL NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    UNIQUE (position_key, move_uci, kind, provider, model, prompt_version)
);

CREATE INDEX opening_notes_position ON opening_notes (position_key, move_uci, kind);

-- Engine results by position, think time and engine (FR-12.8).
CREATE TABLE opening_engine_cache (
    position_key TEXT NOT NULL,
    think_ms     INTEGER NOT NULL,
    multipv      INTEGER NOT NULL,
    engine       TEXT NOT NULL,
    lines_json   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (position_key, think_ms, multipv, engine)
);

-- Lichess opening explorer responses (FR-12.2).
CREATE TABLE explorer_cache (
    position_key TEXT NOT NULL,
    params       TEXT NOT NULL,
    body_json    TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (position_key, params)
);

-- Wikibooks text, fetched at runtime and kept only on your PC (FR-12.15). `status` is 'ok' or 'missing'.
CREATE TABLE wikibooks_pages (
    title       TEXT PRIMARY KEY,
    revision_id INTEGER,
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);

-- Practice (FR-12.9–12.11). Its own table, so puzzle stats, ratings, sync and the Coach can't see it.
-- `outcome` is 'correct', 'wrong' or 'helped'. The schedule is replayed from these rows (FR-12.10).
CREATE TABLE opening_attempts (
    id           INTEGER PRIMARY KEY,
    session_id   TEXT NOT NULL,
    color        TEXT NOT NULL,
    opening_id   INTEGER,
    position_key TEXT NOT NULL,
    played_uci   TEXT,
    played_san   TEXT,
    outcome      TEXT NOT NULL,
    time_ms      INTEGER,
    finished_at  TEXT NOT NULL
);

CREATE INDEX opening_attempts_position ON opening_attempts (color, position_key, finished_at);

-- FR-12.7b: the recent average response time per model. Null on rows from before v0.13.
ALTER TABLE llm_usage ADD COLUMN duration_ms INTEGER;
