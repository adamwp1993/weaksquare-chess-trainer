# lichess_games fixtures (v0.8)

Responses from the Lichess games export (`/api/games/user/{u}` ndjson) and single-game export (`/game/export/{id}` JSON), used by the fake clients and the adapter tests.

**Source:** hand-written from the API documentation and generated so every PGN is legal (with `%clk`
clocks), until the live recorder captures real ones: `uv run pytest -m live --record-games` (see
docs/DEVELOPER_GUIDE.md). The recorder scrubs and **anonymizes** (SR-12, SR-12a): you become
`player_a`, opponents `opponent_*`, game ids `GAMEID..` (Lichess) or `1000000..` (chess.com), and
no headers, tokens, dates of birth, avatars or real URLs are kept.

Status: hand-written (not yet recorded).
