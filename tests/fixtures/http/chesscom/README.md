# chesscom fixtures (v0.8)

Responses from chess.com's Published-Data API: the player profile, the monthly archives list and two months, used by the fake clients and the adapter tests.

**Source:** hand-written from the API documentation and generated so every PGN is legal (with `%clk`
clocks), and kept as they are, because the service tests depend on their exact games. The live recorder,
`uv run pytest -m live --record-games` (see docs/DEVELOPER_GUIDE.md), writes real responses as
`recorded_*` files beside them, which `test_recorded_game_fixtures_parse` checks. The recorder scrubs and **anonymizes** (SR-12, SR-12a): you become
`player_a`, opponents `opponent_*`, game ids `GAMEID..` (Lichess) or `1000000..` (chess.com), and
no headers, tokens, dates of birth, avatars or real URLs are kept.

Status: hand-written; no `recorded_*` files yet.
