-- v1.0: checkpoints and fix tracking (REQUIREMENTS §10.8, ARCHITECTURE §7). Never edit this file once applied;
-- add 0016_… instead.

-- One row per checkpoint (FR-10.33). `trigger` is count / schedule / manual / backfill. A live checkpoint saves a
-- normal Coach report (`report_id`); a backfilled one (`reconstructed` = 1, v1.0 planning) has none. `game_ids_json`
-- is the rolling window it measured, and `newest_played_at` the newest of those games, which is where the count of
-- new eligible games starts for the next one. `health_json` is the overall game health (FR-10.36) and
-- `changes_json` the status changes it made (FR-10.38 notices). `ai_run_id` points at the optional AI summary.
CREATE TABLE coach_checkpoints (
    id               INTEGER PRIMARY KEY,
    number           INTEGER NOT NULL UNIQUE,
    created_at       TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    report_id        INTEGER REFERENCES coach_reports (id) ON DELETE SET NULL,
    reconstructed    INTEGER NOT NULL DEFAULT 0,
    game_ids_json    TEXT NOT NULL,
    games            INTEGER NOT NULL,
    newest_played_at TEXT,
    health_json      TEXT NOT NULL,
    changes_json     TEXT NOT NULL DEFAULT '[]',
    ai_run_id        INTEGER
);

-- Each weakness being tracked, with its frozen baseline (FR-10.34) and current status (FR-10.35). `key` is the
-- report's weakness key ("allowed:fork", "habit:hungPiece", "time:low_clock", …). `themes_json` keeps the puzzle
-- themes that train it, so a Fixed weakness that no longer shows up in reports still gets its maintenance share.
CREATE TABLE weakness_tracking (
    key                 TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    label               TEXT NOT NULL,
    themes_json         TEXT NOT NULL DEFAULT '[]',
    baseline_per10      REAL NOT NULL,
    baseline_games      INTEGER NOT NULL,
    first_checkpoint_id INTEGER NOT NULL REFERENCES coach_checkpoints (id) ON DELETE CASCADE,
    status              TEXT NOT NULL,
    status_since_id     INTEGER NOT NULL REFERENCES coach_checkpoints (id) ON DELETE CASCADE,
    fixed_streak        INTEGER NOT NULL DEFAULT 0
);

-- What each checkpoint measured for each tracked weakness: the line charts' points (FR-10.38). `guarded` = 1 is
-- "not enough data yet" (drawn hollow, no status change made from it).
CREATE TABLE weakness_metrics (
    checkpoint_id    INTEGER NOT NULL REFERENCES coach_checkpoints (id) ON DELETE CASCADE,
    key              TEXT NOT NULL,
    per10            REAL NOT NULL,
    count            INTEGER NOT NULL,
    puzzle_accuracy  REAL,
    puzzle_attempts  INTEGER NOT NULL DEFAULT 0,
    guarded          INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL,
    reasons_json     TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (checkpoint_id, key)
);

CREATE INDEX weakness_metrics_key ON weakness_metrics (key, checkpoint_id);
