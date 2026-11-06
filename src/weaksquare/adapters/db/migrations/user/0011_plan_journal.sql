-- user.db v11 (v0.12, REQUIREMENTS §10.12): training plans, review passes, the journal, and what the daily log
-- and Include my journal need. Never edit this file once applied; add 0012_… instead.

-- FR-10.61-10.66. At most one plan is `current`; a replaced plan stays as history (FR-10.65).
CREATE TABLE training_plans (
    id              INTEGER PRIMARY KEY,
    created_at      TEXT NOT NULL,
    report_id       INTEGER REFERENCES coach_reports(id) ON DELETE SET NULL,
    source          TEXT NOT NULL,          -- deterministic / ai
    ai_run_id       INTEGER REFERENCES coach_ai_runs(id) ON DELETE SET NULL,
    weeks           INTEGER NOT NULL,
    weekdays_json   TEXT NOT NULL,          -- picked weekdays, Monday = 0
    minutes_per_day INTEGER NOT NULL,
    start_date      TEXT NOT NULL,          -- local calendar date
    status          TEXT NOT NULL,          -- current / replaced
    ended_at        TEXT
);
CREATE UNIQUE INDEX training_plans_one_current ON training_plans (status) WHERE status = 'current';

CREATE TABLE plan_days (
    id       INTEGER PRIMARY KEY,
    plan_id  INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    week     INTEGER NOT NULL,              -- 1-based
    position INTEGER NOT NULL,              -- 1-based within the plan
    date     TEXT NOT NULL                  -- local calendar date
);
CREATE INDEX plan_days_plan ON plan_days (plan_id, date);

-- `manual_state` is your hand choice (done / undone), which always beats what the app saw (FR-10.64).
-- `done_at` is when the app first saw the task done. `carried_from` / `swapped_from` point at the task it replaced.
-- A task swapped away stays, marked `removed`, so the sessions it started stay linked.
CREATE TABLE plan_tasks (
    id           INTEGER PRIMARY KEY,
    day_id       INTEGER NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    type         TEXT NOT NULL,             -- puzzles / game_puzzles / retry / review / lesson / reflection
    weakness_key TEXT,
    minutes      INTEGER NOT NULL,
    title        TEXT NOT NULL,
    params_json  TEXT NOT NULL,
    manual_state TEXT,
    skipped_at   TEXT,
    done_at      TEXT,
    carried_from INTEGER REFERENCES plan_tasks(id) ON DELETE SET NULL,
    swapped_from INTEGER REFERENCES plan_tasks(id) ON DELETE SET NULL,
    removed      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX plan_tasks_day ON plan_tasks (day_id, position);
CREATE INDEX plan_tasks_carried ON plan_tasks (carried_from);

-- A puzzle session started from a plan task (FR-10.63, 10.64). NULL for every other session.
ALTER TABLE sessions ADD COLUMN plan_task_id INTEGER;
CREATE INDEX sessions_plan_task ON sessions (plan_task_id) WHERE plan_task_id IS NOT NULL;

-- One pass through a game in Game Review: the moves you visited (FR-10.64, 10.68). A new pass starts once the
-- last one was completed, so a game can be reviewed again and each completion keeps its own date.
CREATE TABLE review_passes (
    id           INTEGER PRIMARY KEY,
    game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    plan_task_id INTEGER,
    plies_json   TEXT NOT NULL DEFAULT '[]',
    started_at   TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX review_passes_game ON review_passes (game_id, id);
CREATE INDEX review_passes_completed ON review_passes (completed_at) WHERE completed_at IS NOT NULL;

-- When a game was last analyzed, for the daily log (FR-10.68). Games analyzed before v0.12 have none.
ALTER TABLE games ADD COLUMN analyzed_at TEXT;

-- Your notes and game reflections (FR-10.67, 10.69). The daily log isn't stored: it's computed when read.
CREATE TABLE journal_entries (
    id           INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    entry_date   TEXT NOT NULL,             -- local calendar date
    kind         TEXT NOT NULL,             -- note / reflection
    text         TEXT NOT NULL,
    game_id      INTEGER REFERENCES games(id) ON DELETE SET NULL,
    ply          INTEGER,                   -- 0-based, with game_id
    weakness_key TEXT,
    plan_day_id  INTEGER REFERENCES plan_days(id) ON DELETE SET NULL,
    plan_task_id INTEGER REFERENCES plan_tasks(id) ON DELETE SET NULL
);
CREATE INDEX journal_entries_date ON journal_entries (entry_date, id);
CREATE INDEX journal_entries_game ON journal_entries (game_id, ply);

-- FR-10.71: whether a run sent your journal, and a hash of exactly what it sent, so a saved answer is reused only
-- while the journal text is unchanged.
ALTER TABLE coach_ai_runs ADD COLUMN include_journal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE coach_ai_runs ADD COLUMN journal_hash TEXT;
