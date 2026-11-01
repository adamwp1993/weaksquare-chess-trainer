-- puzzles.db v2 (v0.2): the opening filter (FR-3.7). Like 0001, this only ever runs on an empty
-- puzzles.new.db: an older puzzles.db is upgraded by rebuilding it from its own rows (no download).

ALTER TABLE puzzles ADD COLUMN opening_family INTEGER;      -- openings.id of the first OpeningTags tag
ALTER TABLE puzzles ADD COLUMN opening_variation INTEGER;   -- openings.id of the second tag, if any

-- Opening tags as Lichess writes them (e.g. Sicilian_Defense, Sicilian_Defense_Najdorf_Variation).
-- family_id is NULL for a family and points at the family for a variation.
CREATE TABLE openings (
    id        INTEGER PRIMARY KEY,
    tag       TEXT NOT NULL UNIQUE,
    family_id INTEGER,
    count     INTEGER NOT NULL
);
