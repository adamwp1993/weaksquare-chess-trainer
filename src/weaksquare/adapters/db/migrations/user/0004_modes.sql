-- user.db v4 (v0.5): training modes. Never edit this file once applied; add 0005_… instead.
-- New nullable columns on the attempts log only (ARCHITECTURE §3 decision 4).

-- Commit the line (FR-4.2): calculation accuracy, the predicted opponent replies that matched.
ALTER TABLE attempts ADD COLUMN replies_correct INTEGER;
ALTER TABLE attempts ADD COLUMN replies_total INTEGER;

-- Depth ladder (FR-4.5): which theme set the attempt climbed, and at which level (2, 3 or 4 moves).
-- The current level is worked out from these rows; there's no separate store.
ALTER TABLE attempts ADD COLUMN ladder_key TEXT;
ALTER TABLE attempts ADD COLUMN ladder_level INTEGER;

CREATE INDEX attempts_ladder ON attempts (ladder_key, ladder_level);
