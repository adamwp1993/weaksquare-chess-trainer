-- user.db v7 (v0.8): the game library, Game Review analysis, your own puzzles and Retry mode
-- (REQUIREMENTS §4.3, §10.10, §11). Never edit this file once applied; add 0008_… instead. New tables only.

-- The game library (§11.5), shared by Game Review and, from v0.10, the Coach. `source` is lichess,
-- chesscom, paste or file. `source_game_id` is the platform's game id (NULL for paste/file without one).
-- `moves_hash` is a SHA-256 of the start FEN and the UCI move list, so a re-import with identical moves
-- finds the same row and its analysis (FR-11.7). `user_color` is white, black or both (review both sides);
-- NULL means not known yet. `analysis_status` is none / analyzed (ai_reviewed from v0.9).
-- `analysis_think_s` and `analysis_engine` record the settings the stored analysis used (FR-11.31).
-- `extra_json` holds optional platform data such as Lichess's `division`.
CREATE TABLE games (
    id                     INTEGER PRIMARY KEY,
    source                 TEXT NOT NULL,
    source_game_id         TEXT,
    url                    TEXT,
    pgn                    TEXT NOT NULL,
    moves_hash             TEXT NOT NULL,
    played_at              TEXT,
    time_control           TEXT,
    time_class             TEXT,
    rated                  INTEGER,
    white                  TEXT,
    black                  TEXT,
    white_rating           INTEGER,
    black_rating           INTEGER,
    user_color             TEXT,
    result                 TEXT,
    eco                    TEXT,
    opening                TEXT,
    platform_accuracy_white REAL,
    platform_accuracy_black REAL,
    lichess_analyzed       INTEGER NOT NULL DEFAULT 0,
    analysis_status        TEXT NOT NULL DEFAULT 'none',
    analysis_think_s       REAL,
    analysis_engine        TEXT,
    extra_json             TEXT,
    fetched_at             TEXT NOT NULL
);

CREATE UNIQUE INDEX games_source_id ON games (source, source_game_id) WHERE source_game_id IS NOT NULL;
CREATE INDEX games_moves_hash ON games (moves_hash);
CREATE INDEX games_played_at ON games (played_at);

-- Incremental sync state per linked account (FR-11.27). `last_archive` is chess.com's last synced month
-- (YYYY/MM); `etag_json` maps archive URLs to their ETags.
CREATE TABLE account_sync (
    platform     TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    last_sync_at TEXT,
    last_archive TEXT,
    etag_json    TEXT
);

-- One row per analyzed move (FR-11.9). Evals are JSON {"cp": n} or {"mate": n}, from the mover's view.
-- `multipv_json` holds the top lines from `fen_before` (UCI, White-relative scores as the engine gives
-- them). `kind` is missed / allowed / other for the user's mistakes, NULL otherwise. `themes` stays NULL
-- until the v0.10 tagger (Adam, v0.8 planning).
CREATE TABLE game_analysis (
    game_id        INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply            INTEGER NOT NULL,
    fen_before     TEXT NOT NULL,
    move_uci       TEXT NOT NULL,
    move_san       TEXT NOT NULL,
    mover          TEXT NOT NULL,
    eval_before    TEXT NOT NULL,
    eval_after     TEXT NOT NULL,
    best_move      TEXT,
    multipv_json   TEXT NOT NULL,
    cp_loss        INTEGER NOT NULL,
    classification TEXT NOT NULL,
    kind           TEXT,
    phase          TEXT NOT NULL,
    low_clock      INTEGER,
    clock_s        REAL,
    themes         TEXT,
    PRIMARY KEY (game_id, ply)
);

-- Your own puzzles (FR-3.15): saved from Game Review (origin manual, FR-11.16) or imported from a file
-- (origin import, §10.10); coach arrives in v0.10. `fen` is the position you solve, and the side to move
-- is you. `solution_uci` is the space-separated line, ending on your move. `strict` = 1 checks moves
-- exactly like a Lichess puzzle (imports, FR-10.49); 0 uses the engine tolerance (FR-10.43).
-- Attempts are stored in `attempts` with puzzle_source 'my' and puzzle_id = this id.
CREATE TABLE custom_puzzles (
    id           INTEGER PRIMARY KEY,
    game_id      INTEGER REFERENCES games (id) ON DELETE SET NULL,
    ply          INTEGER,
    fen          TEXT NOT NULL,
    solution_uci TEXT NOT NULL,
    length       INTEGER NOT NULL,
    player_color TEXT NOT NULL,
    themes       TEXT,
    origin       TEXT NOT NULL,
    set_label    TEXT,
    name         TEXT,
    strict       INTEGER NOT NULL,
    kind         TEXT,
    severity     TEXT,
    cp_loss      INTEGER,
    phase        TEXT,
    time_class   TEXT,
    game_date    TEXT,
    solve_as     TEXT NOT NULL DEFAULT 'you',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL
);

CREATE UNIQUE INDEX custom_puzzles_game_ply ON custom_puzzles (game_id, ply) WHERE game_id IS NOT NULL;
CREATE UNIQUE INDEX custom_puzzles_import ON custom_puzzles (set_label, fen, solution_uci) WHERE origin = 'import';
CREATE INDEX custom_puzzles_status ON custom_puzzles (status, origin);

-- Retry mode results (FR-11.15): local only, never synced. `found` = the move was within the tolerance.
CREATE TABLE retry_attempts (
    id         INTEGER PRIMARY KEY,
    game_id    INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply        INTEGER NOT NULL,
    played_uci TEXT NOT NULL,
    found      INTEGER NOT NULL,
    cp_loss    INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX retry_attempts_game ON retry_attempts (game_id, ply);
