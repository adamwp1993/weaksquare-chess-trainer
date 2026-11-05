# Lichess API responses (fixtures)

Used by the fake Lichess client and the parser tests (v0.3).

**Source:** hand-written from the lichess-org/api spec schemas (`PuzzleBatchSolveResponse`,
`PuzzleActivity`, the `/api/account` `perfs.puzzle` object) until the live test records real ones.
Re-record with `uv run pytest -m live --record-lichess` (see docs/DEVELOPER_GUIDE.md). The recorder
scrubs and anonymizes (SR-12, SR-12a): the username becomes `player_a`, dates are fixed, and no
headers or tokens are kept.

Status: recorded from live responses (scrubbed and anonymized), except `dashboard.json` (v0.10), which is
hand-written from the `PuzzleDashboard` schema with made-up numbers; it has no username, date or id.
