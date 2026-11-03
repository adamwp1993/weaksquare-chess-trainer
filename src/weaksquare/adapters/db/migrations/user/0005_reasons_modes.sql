-- user.db v5 (v0.6): Name the idea first, Danger spotting and mistake reasons. Never edit this file once
-- applied; add 0006_… instead. New nullable columns on the attempts log only (ARCHITECTURE §3 decision 4).

-- Name the idea first (FR-4.3): your tags as JSON {"setup": [...], "payoff": [...]}, and their score
-- against the puzzle's motif themes (NULL found/total/extra: the puzzle had no motif themes).
ALTER TABLE attempts ADD COLUMN idea_tags TEXT;
ALTER TABLE attempts ADD COLUMN idea_found INTEGER;
ALTER TABLE attempts ADD COLUMN idea_total INTEGER;
ALTER TABLE attempts ADD COLUMN idea_extra INTEGER;

-- Danger spotting (FR-4.4): the highlighted move (UCI), whether it was the Stockfish-verified safe move
-- (1) or the real blunder (0), and your call ('safe' / 'unsafe'; NULL if you moved on before calling).
ALTER TABLE attempts ADD COLUMN danger_candidate TEXT;
ALTER TABLE attempts ADD COLUMN danger_safe INTEGER;
ALTER TABLE attempts ADD COLUMN danger_call TEXT;

-- Why you missed it (§7.3, FR-5.6). Append-only: choosing another reason adds a row, and the latest row
-- per (source, ref_id) counts. `source` is 'puzzle' or 'danger' (v0.6); 'game' and 'retry' come in v0.8.
-- For puzzles `ref_id` is the attempts row id, as text.
CREATE TABLE mistake_reasons (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL,
    ref_id           TEXT NOT NULL,
    reason           TEXT NOT NULL,
    suggested_reason TEXT,
    note             TEXT,
    created_at       TEXT NOT NULL
);

CREATE INDEX mistake_reasons_ref ON mistake_reasons (source, ref_id, id);
