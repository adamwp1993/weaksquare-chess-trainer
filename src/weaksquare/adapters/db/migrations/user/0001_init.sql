-- user.db: everything the user creates. Never edit this file once applied; add 0002_… instead.

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL            -- JSON. Non-secret values only (SR-1).
);

CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,
    mode         TEXT NOT NULL,
    filters_json TEXT NOT NULL,
    queue_size   INTEGER            -- NULL = endless
);

-- Append-only event log (ARCHITECTURE §3 decision 4). Later versions add nullable columns.
CREATE TABLE attempts (
    id                 INTEGER PRIMARY KEY,
    puzzle_source      TEXT NOT NULL,          -- PuzzleRef.source, e.g. 'lichess'
    puzzle_id          TEXT NOT NULL,          -- PuzzleRef.id
    session_id         INTEGER REFERENCES sessions(id),
    mode               TEXT NOT NULL,
    started_at         TEXT NOT NULL,
    finished_at        TEXT NOT NULL,
    win                INTEGER NOT NULL,
    help_used          TEXT NOT NULL DEFAULT 'none',
    first_move_correct INTEGER NOT NULL,
    line_correct       INTEGER NOT NULL,
    time_ms            INTEGER NOT NULL
);

CREATE INDEX attempts_puzzle ON attempts (puzzle_source, puzzle_id);
CREATE INDEX attempts_session ON attempts (session_id);
