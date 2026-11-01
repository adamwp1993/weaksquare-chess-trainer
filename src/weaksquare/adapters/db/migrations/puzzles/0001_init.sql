-- puzzles.db: the imported Lichess puzzle database. Rebuilt from scratch on every import
-- (FR-2.3), so this file only ever runs on an empty puzzles.new.db. Indexes are created after the
-- bulk load by adapters/db/puzzles_indexes.sql, which is much faster than loading into indexes.

CREATE TABLE puzzles (
    n            INTEGER PRIMARY KEY,   -- dense 1..N, used for fast random sampling
    id           TEXT NOT NULL,         -- Lichess PuzzleId
    fen          TEXT NOT NULL,         -- before the opponent's move (§4.2)
    moves        TEXT NOT NULL,         -- UCI, space-separated; moves[0] is the opponent's
    rating       INTEGER NOT NULL,
    rating_dev   INTEGER NOT NULL,
    popularity   INTEGER NOT NULL,
    nb_plays     INTEGER NOT NULL,
    themes       TEXT NOT NULL,         -- space-separated, as in the CSV
    game_url     TEXT NOT NULL,
    opening_tags TEXT NOT NULL,
    length       INTEGER NOT NULL,      -- player moves = len(moves) // 2
    player_color INTEGER NOT NULL,      -- 0 = white, 1 = black (the side NOT to move in fen)
    t0           INTEGER NOT NULL,      -- theme bitmask, bits 0..61   (theme_bits)
    t1           INTEGER NOT NULL,      -- bits 62..123
    t2           INTEGER NOT NULL       -- bits 124..185
);

-- Theme key -> bit, assigned at import so a theme new to an export gets a bit automatically.
CREATE TABLE theme_bits (
    theme TEXT PRIMARY KEY,
    bit   INTEGER NOT NULL UNIQUE,
    count INTEGER NOT NULL
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
