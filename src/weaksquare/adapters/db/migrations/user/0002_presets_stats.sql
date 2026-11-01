-- user.db v2 (v0.2): presets (FR-3.13) and the puzzle's rating on each attempt (Stats, FR-9.1).

-- Named filter sets. `name_key` is the lower-cased name, so names are unique ignoring case.
CREATE TABLE presets (
    name         TEXT PRIMARY KEY,
    name_key     TEXT NOT NULL UNIQUE,
    filters_json TEXT NOT NULL,          -- FilterSpec JSON
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- The rating the puzzle had when you played it, so Stats' rating bands survive a re-import.
-- Attempts recorded before v0.2 are filled in from puzzles.db at startup where the puzzle still exists.
ALTER TABLE attempts ADD COLUMN puzzle_rating INTEGER;

-- The history filters (FR-3.9) look up wins and latest results per puzzle.
CREATE INDEX attempts_puzzle_win ON attempts (puzzle_source, puzzle_id, win);
