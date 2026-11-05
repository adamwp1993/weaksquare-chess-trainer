-- user.db v8 (v0.10): the Coach (REQUIREMENTS §10). Never edit this file once applied; add 0009_… instead.

-- Whose games a game counts for (FR-10.3, Adam, v0.10 planning). `subject` is 'me' for your own games
-- (your accounts, imports and pastes), or '<platform>:<lowercase username>' for another player you ran
-- the Coach on. `color` is that subject's color in the game (white, black, both, or NULL when unknown).
-- A game you played against that player is stored once and has both rows. My Games shows 'me' by
-- default; your Suggested mix, puzzles, stats and report trends read 'me' only.
CREATE TABLE game_subjects (
    game_id INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    color   TEXT,
    PRIMARY KEY (game_id, subject)
);

CREATE INDEX game_subjects_subject ON game_subjects (subject, game_id);

-- Every game before v0.10 is yours.
INSERT INTO game_subjects (game_id, subject, color) SELECT id, 'me', user_color FROM games;

-- Habit tags (FR-10.27) per analyzed move, as a JSON list; `themes` (0007) gets the lichess-puzzler
-- themes of a Missed or Allowed line (FR-10.12). Both stay NULL until the move is tagged.
ALTER TABLE game_analysis ADD COLUMN habits TEXT;

-- The quality check for puzzles from your games (FR-10.41), one row per checked mistake. `check_key`
-- records the analysis and generator settings it ran with: a different key means check again.
-- `passed` = 1 keeps `line_json` (the solution in UCI, from the position solved) and `cp`; 0 keeps the
-- `reason` it was rejected. A level change reads this table and runs no engine (FR-10.40).
CREATE TABLE coach_candidates (
    game_id    INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply        INTEGER NOT NULL,
    check_key  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    passed     INTEGER NOT NULL,
    reason     TEXT,
    line_json  TEXT,
    cp         INTEGER,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (game_id, ply)
);

-- Saved Coach reports (FR-10.20). `subject` as in game_subjects; `subject_label` is what the page shows
-- (your accounts, or the other player's name). `source_kind` is puzzles / games / both. `params_json` is
-- the run's settings, `report_json` the free report, `game_ids_json` the games it covered. `llm_json` is
-- the validated AI coaching, when you asked for it (FR-10.21–10.25).
CREATE TABLE coach_reports (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL,
    subject       TEXT NOT NULL,
    subject_label TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    report_json   TEXT NOT NULL,
    game_ids_json TEXT NOT NULL,
    llm_json      TEXT
);

CREATE INDEX coach_reports_subject ON coach_reports (subject, id);

-- One row per graded error of a subject's own moves (ARCHITECTURE §7, v0.8: created with its first
-- reader). The Coach aggregates from it; `color = 'both'` counts both sides' moves.
CREATE VIEW game_errors AS
SELECT s.subject, a.game_id, a.ply, a.mover, a.classification, a.kind, a.phase, a.cp_loss, a.themes,
       a.habits, a.low_clock, g.time_class, g.rated, g.played_at
FROM game_analysis a
JOIN games g ON g.id = a.game_id
JOIN game_subjects s ON s.game_id = a.game_id AND (s.color = a.mover OR s.color = 'both')
WHERE a.classification IN ('inaccuracy', 'mistake', 'blunder');
