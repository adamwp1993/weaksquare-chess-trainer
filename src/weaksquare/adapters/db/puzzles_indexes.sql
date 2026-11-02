-- Built once by the importer after the bulk load (see migrations/puzzles/0001_init.sql).
CREATE UNIQUE INDEX puzzles_id ON puzzles (id);
-- Covering index for the live match count: rating first, then every other filter column, so the
-- count never touches the table (v0.2 added popularity and nb_plays for the quality filter).
CREATE INDEX puzzles_filter ON puzzles (rating, length, player_color, t0, t1, t2, popularity, nb_plays);
-- The opening filter (v0.2) is selective, so it drives the query through these instead.
CREATE INDEX puzzles_opening_family ON puzzles (opening_family, rating);
CREATE INDEX puzzles_opening_variation ON puzzles (opening_variation, rating);
