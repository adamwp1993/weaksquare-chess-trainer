-- Built once by the importer after the bulk load (see migrations/puzzles/0001_init.sql).
CREATE UNIQUE INDEX puzzles_id ON puzzles (id);
-- Covering index for the live match count: every v0.1 filter column, rating first.
CREATE INDEX puzzles_filter ON puzzles (rating, length, player_color, t0, t1, t2);
