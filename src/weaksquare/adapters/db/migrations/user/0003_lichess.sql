-- user.db v3 (v0.3): Lichess sync (FR-6.8–6.16), rating history (FR-6.11d) and puzzle history (FR-6.17).
-- Never edit this file once applied; add 0004_… instead.

-- Sync state on the attempts log (ARCHITECTURE §3 decision 4: new nullable columns only).
ALTER TABLE attempts ADD COLUMN rated INTEGER;            -- 1/0: the session's Rated toggle (FR-1.9)
ALTER TABLE attempts ADD COLUMN angle TEXT;               -- the angle reported to Lichess (§8.3)
ALTER TABLE attempts ADD COLUMN sync_status TEXT;         -- local | pending | synced | skipped | failed
ALTER TABLE attempts ADD COLUMN sync_account TEXT;        -- the Lichess user signed in when it was solved; NULL = nobody
ALTER TABLE attempts ADD COLUMN already_played INTEGER;   -- 1 if Lichess had seen this puzzle from you already
ALTER TABLE attempts ADD COLUMN rating_diff INTEGER;      -- Lichess's ratingDiff for this solve (FR-6.11b)
ALTER TABLE attempts ADD COLUMN rating_after INTEGER;     -- your puzzle rating after the batch that carried it
ALTER TABLE attempts ADD COLUMN synced_at TEXT;

-- Attempts recorded before v0.3 are never synced (Adam, v0.3 planning): no Rated flag or angle.
UPDATE attempts SET sync_status = 'local';

CREATE INDEX attempts_sync ON attempts (sync_status);

-- Your Lichess puzzle history (GET /api/puzzle/activity) plus what this app has synced. A cache for
-- the signed-in account: re-importable, and cleared when a different account signs in.
CREATE TABLE lichess_history (
    puzzle_id TEXT PRIMARY KEY,
    played_at TEXT,
    win       INTEGER
);
