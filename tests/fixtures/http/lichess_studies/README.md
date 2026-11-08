# Lichess study fixtures (v0.14)

Used by the fake studies client (`tests/fakes/studies.py`) and the study tests.

**Source:** hand-written, invented studies in the shape of `GET /api/study/{id}.pgn` (headers `StudyName`,
`ChapterName`, `ChapterURL`, `ChapterMode`, `Orientation`, `Annotator`) and `GET /api/study/by/{username}` (only `id`,
`name`, `createdAt`, `updatedAt`, as checked on 2026-11-06). No real study text, IDs or usernames (SR-12a): study
content belongs to its authors and is never committed. The author is `player_author`.

- `TestGb01.pgn`: two gamebook chapters for Black, with a covered wrong move as a side line.
- `TestNm02.pgn`: a normal chapter with nested side lines, arrows and highlights (one on an invalid square) and a web
  address in a comment; a chapter with an illegal move; a text chapter on an empty board.
- `by_author.ndjson`: the two studies, plus a malformed entry that must be skipped.
