-- user.db v9 (v0.11): whole-game coaching (REQUIREMENTS §10.11). Never edit this file once applied; add 0010_… instead.

-- One digest per analyzed game and side (FR-10.52): the deterministic facts the whole-game measures and
-- the AI diagnosis read. `color` is the side the digest is for (a game you played against another player
-- you ran the Coach on has one per side). `analysis_key` records the analysis and digest version it was
-- built from: a different key means build it again. No engine runs to build one.
CREATE TABLE game_digests (
    game_id      INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    color        TEXT NOT NULL,
    analysis_key TEXT NOT NULL,
    digest_json  TEXT NOT NULL,
    built_at     TEXT NOT NULL,
    PRIMARY KEY (game_id, color)
);

-- Every AI coaching answer for a report (Adam, v0.11 planning), so a standard and an Advanced run can be
-- compared. `format` is 'keyed' (the v0.10 answer, one note per weakness key) or 'diagnosis' (v0.11,
-- FR-10.54). `advanced` and `include_notes` are the run's options (FR-10.56, 10.60); `game_cap` is the
-- Advanced game cap. `result_json` is the validated answer, with the G-label → game map it was sent with.
CREATE TABLE coach_ai_runs (
    id            INTEGER PRIMARY KEY,
    report_id     INTEGER NOT NULL REFERENCES coach_reports (id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    format        TEXT NOT NULL,
    advanced      INTEGER NOT NULL DEFAULT 0,
    include_notes INTEGER NOT NULL DEFAULT 0,
    game_cap      INTEGER,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    cost_usd      REAL NOT NULL DEFAULT 0,
    result_json   TEXT NOT NULL
);

CREATE INDEX coach_ai_runs_report ON coach_ai_runs (report_id, id);

-- The v0.10 answers become the reports' first runs. `coach_reports.llm_json` is left as it was.
INSERT INTO coach_ai_runs (report_id, created_at, format, provider, model, cost_usd, result_json)
SELECT id, created_at, 'keyed', COALESCE(json_extract(llm_json, '$.provider'), ''),
       COALESCE(json_extract(llm_json, '$.model'), ''), COALESCE(json_extract(llm_json, '$.cost_usd'), 0), llm_json
FROM coach_reports
WHERE llm_json IS NOT NULL AND json_valid(llm_json);

-- Findings the app can't measure (FR-10.57), noted when they recur across a subject's runs. `topic_key`
-- is the lesson topic the AI picked (FR-10.59), or '' with the category and a normalized title as the key.
CREATE TABLE coach_observations (
    id              INTEGER PRIMARY KEY,
    subject         TEXT NOT NULL,
    topic_key       TEXT NOT NULL,
    category        TEXT NOT NULL,
    title_key       TEXT NOT NULL,
    title           TEXT NOT NULL,
    first_report_id INTEGER,
    last_report_id  INTEGER,
    times_seen      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (subject, topic_key, category, title_key)
);
