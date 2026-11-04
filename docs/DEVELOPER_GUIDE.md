# WeakSquare Chess Trainer: Developer Guide

How to set up, run, test and change the code. **What** to build is in [REQUIREMENTS.md](../REQUIREMENTS.md), **how it's organized** is in [ARCHITECTURE.md](../ARCHITECTURE.md), and **what's next** is in [ROADMAP.md](../ROADMAP.md). This guide is the single source for commands: CLAUDE.md points here.

`TODO(v0.x)` marks something that version must fill in. `python scripts/check_docs.py --strict` fails if a marker for the current or an earlier version is still here.

## Prerequisites
Windows 10 or 11 with Git for Windows, Python 3.12 or newer (64-bit), Node.js LTS and the Microsoft Edge WebView2 Runtime. `scripts/setup.py` installs [uv](https://docs.astral.sh/uv/) with pip if it's missing, and `pre-commit install` is part of setup. Claude Code is optional, needed only to build with it.

The project's virtual environment uses Python 3.12 (pinned in `.python-version`); uv finds it or downloads it. If setup installed uv with pip, uv's folder may not be on your PATH. Setup says so, and you can then type `python -m uv` wherever this guide says `uv`.

## Commands
Run from the repo root in PowerShell unless noted. Keep this table exact: QA runs every command here as written. Commands use `npm.cmd`, `npx.cmd` and `uv run`, never `.ps1` scripts or venv activation, so they work under any PowerShell execution policy (including AllSigned), in cmd and in Git Bash.

| Task | Command |
|---|---|
| Set up a fresh clone (`scripts/setup.py`) | `python scripts/setup.py` (also installs Stockfish; `--skip-engine` skips it, `--dev` puts the puzzles and Stockfish in the dev data folder). Creates Start-menu and desktop shortcuts with the app icon: add `--no-desktop-shortcut` for the Start menu only, or `--no-shortcut` for neither. Safe to re-run (the shortcuts are replaced, never duplicated). |
| Download and import the puzzle database | `uv run python scripts/fetch_puzzle_db.py --dev` (dev data folder; drop `--dev` for the real one). `--file PATH` imports a `lichess_db_puzzle.csv.zst` you already have. Close the app first. |
| Install or repair Stockfish (`scripts/fetch_stockfish.py`) | `uv run python scripts/fetch_stockfish.py --dev` (dev data folder's `engines\sf_19`; drop `--dev` for the real one). Downloads the release pinned in `src/weaksquare/engine_manifest.json`, checks its SHA-256 before unzipping, extracts only the `.exe`, self-tests it and swaps it into place. Running it again does nothing if the install matches; `--force` reinstalls (close the app first). `python scripts/setup.py` runs it too; `--skip-engine` skips that step. |
| Run the app (dev data folder) | `npm.cmd --prefix web run build` once, then `uv run python -m weaksquare --dev`. The Start-menu shortcut runs the app without `--dev`. |
| Dev mode (hot-reloading front end) | `npm.cmd --prefix web run dev`, then in a second window `uv run python -m weaksquare --dev-server`. For the UI alone in a browser with fixed data: `npm.cmd --prefix web run dev -- --mode mock`, then open http://127.0.0.1:5173 |
| Unit, integration and contract tests | `uv run pytest` |
| End-to-end UI tests (mock client) | `uv run pytest -m e2e` (builds `web/dist-mock` first if it's out of date) |
| Real-app smoke test | `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` (opens and closes the real window several times; stops with that build command if `web/dist` is older than `web/src`) |
| Lint and format | `uv run ruff check .` and `uv run ruff format --check .` (drop `--check` to reformat) |
| Type checks (`mypy`, `tsc --noEmit`, ESLint) | `uv run mypy src`, `npm.cmd --prefix web run typecheck` and `npm.cmd --prefix web run lint` |
| Full-DB tests (needs the imported puzzle DB) | `uv run pytest -m fulldb`. Reads the dev data folder's `puzzles.db` read-only; add `--fulldb-path=PATH` (with `=`: pytest would take a separate PATH as a test path) to use another one. Skips if there isn't one. |
| Real-Stockfish tests | `uv run pytest -m engine`. Uses the dev data folder's managed install (run `uv run python scripts/fetch_stockfish.py --dev` first), read-only; add `--engine-path=PATH` (with `=`) to test another `.exe`. Skips if there's none. The normal suite covers the same crash, timeout and restart handling with a fake UCI engine (`tests/fakes/uci_engine.py`), so it needs no binary. |
| All pre-commit checks | `uv run pre-commit run --all-files` |
| Check the docs | `python scripts/check_docs.py` (add `--strict` before a handoff) |
| Regenerate `web/src/api/types.ts` after changing `bridge/dto.py` | `uv run python scripts/gen_types.py` |
| Regenerate the user-guide screenshots | `uv run pytest -m docs_screenshots` (writes `docs/img/*.png` from the mock client) |
| Rebuild the app icon after changing `assets/icon/weaksquare.svg` | `uv run python scripts/make_icon.py` (commit the `.ico` with the SVG; `--check` tells you if they've drifted, and `uv run pytest -m e2e` runs that check) |
| Re-record the update-check responses (needs the internet) | `uv run python tests/fixtures/tools/record_db_update.py` (writes scrubbed copies to `tests/fixtures/http/lichess_db/`; review the diff before committing) |
| Store the live-test Lichess token (run it yourself, outside Claude Code) | Create a personal access token at https://lichess.org/account/oauth/token with only **puzzle:read** and **puzzle:write**, then run `uv run python scripts/set_test_token.py` in your own PowerShell window and paste it at the hidden prompt. It's stored in Windows Credential Manager as `weaksquare-test`, separate from the app's sign-in. `--delete` removes it. Never run this inside Claude Code. |
| Store the live-test AI key (v0.7; run it yourself, outside Claude Code) | `uv run python scripts/set_test_token.py --llm anthropic` (or `--llm openai`) in your own PowerShell window; paste the key at the hidden prompt. It goes in the same `weaksquare-test` entry, under the provider's name. A key with a low spending limit in the provider's console is a good idea. Add `--delete` to remove it. |
| Live tests (opt-in) | `uv run pytest -m live` (you run it, never Claude Code). It reads the `weaksquare-test` token and sends exactly 3 solves to Lichess with `rated: false` (they appear in your puzzle history, unrated), then checks the response shapes. Add `--record-lichess` to rewrite `tests/fixtures/http/lichess/` from the real responses, scrubbed and anonymized. Review the diff before committing. Skips if there's no token. From v0.7 it also makes **one** real Explain call with the cheapest model of the provider whose key is stored (Anthropic first), with a $0.01 per-run cap, and checks the logged cost is under it; `--record-llm` rewrites that provider's file in `tests/fixtures/http/llm/` (only the fields the parser reads). Skips if there's no AI key. |
| Live game-API checks (v0.8; opt-in, you run it) | `uv run pytest -m live tests/live/test_games_live.py` reads (never writes) the `weaksquare-test` token's account, your newest finished Lichess game (from `/api/games/user` and `/game/export`), and checks them against the app's parsers. Add `--chesscom-user=YOURNAME` to check chess.com too (your profile, archives list and newest month, one request at a time). Add `--record-games` to write scrubbed, **anonymized** `recorded_*` files beside the hand-written fixtures in `tests/fixtures/http/lichess_games/` and `chesscom/` (you become `player_a`, opponents `opponent_*`, ids `GAMEID..`/`1000000..`, dates and ratings fixed). The recorder runs the fixture scrub checks first; review the diff before committing. |
| Build the Windows installer | TODO(v1.0) |

## Where things are
The layer rules and full repo tree are in ARCHITECTURE.md §1–2. Docs:

| File | For | Updated |
|---|---|---|
| `CHANGELOG.md` | what changed in each version, for the user | same commit as the change |
| `docs/USER_GUIDE.md` | how to use the app; shipped features only | same commit as the change |
| `docs/DEVELOPER_GUIDE.md` | this file: commands, data, testing, how-tos | when a command, path or workflow changes |
| `docs/img/` | user-guide screenshots, generated by Playwright | regenerated at every handoff |
| `ARCHITECTURE.md` §7 | decision log | when a technical decision is made or changed |
| `REQUIREMENTS.md` | behavior | when a behavior decision changes |

## Data and configuration
- App data: `%LOCALAPPDATA%\WeakSquare` (from `config.py`), holding `puzzles.db`, `user.db` and, from v0.4, `engines\<tag>\stockfish.exe` with its `install.json` (the tag, the asset and exe SHA-256, the engine name). Each data folder has its own engine, so dev runs need `uv run python scripts/fetch_stockfish.py --dev` once (or the Install button in a dev run).
- Stockfish version: pinned in `src/weaksquare/engine_manifest.json`. To upgrade, change the tag, the asset `name`, `url`, `size`, `sha256` (GitHub's published digest: the release page shows it next to the asset, or `https://api.github.com/repos/official-stockfish/Stockfish/releases/tags/<tag>` has it as `digest`) and `exe_member` (the `.exe`'s path inside the zip), add an ARCHITECTURE.md §7 entry, then run `uv run python scripts/fetch_stockfish.py --dev` and `uv run pytest -m engine`. Installs of the old tag stay in their own `engines\<old tag>` folder until you delete them.
- Engine settings (think time, threads, hash, a custom engine path) live in `user.db`'s `settings` table under `engine.*` keys.
- `WEAKSQUARE_DATA_DIR` overrides the data folder. Dev runs default to `%LOCALAPPDATA%\WeakSquare-dev` and tests use a temp folder, so your real history is never touched (REQUIREMENTS.md NFR-2).
- The Lichess sign-in (v0.3) is in Windows Credential Manager, one entry per data folder: `weaksquare` for the real folder, `weaksquare-dev` for the dev folder, and `weaksquare-<hash>` for any other `WEAKSQUARE_DATA_DIR` (so smoke runs start signed out). Sign out in the app, or delete the entry under Control Panel → Credential Manager → Windows Credentials, to reset it. Tests never touch Credential Manager (only `-m live` reads `weaksquare-test`).
- Backups of `user.db` taken before each migration: `<data folder>\backups\` (last 5 kept). Logs: `<data folder>\logs\`.
- Other settings and environment variables:
  - `python -m weaksquare --dev` uses the dev data folder. `--dev-server` does the same and also loads the front end from the Vite dev server (http://localhost:5173) instead of `web/dist`.
  - `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` with `--remote-debugging-port` is set only by the smoke-test harness. The app refuses to start with it unless `--dev` is given (REQUIREMENTS.md SR-16).
  - `WEAKSQUARE_NO_DIALOGS=1` makes start-up errors print to the console without a message box. Tests set it.
  - `<data folder>\weaksquare.lock` stops a second copy from starting (NFR-1). Windows releases it when the app exits, even after a crash.
- **Fast-forward time** (v0.5, `--dev` runs only): Settings → **Debug** → *Fast-forward* moves the app's clock ahead by whole days, so Spaced-repetition misses come due without waiting. It moves the timestamps of new attempts too, which is why it never exists in the real data folder. It's saved as `debug.time_offset_days` in the dev `user.db`; set it back to 0 to return to today.
- Training settings (v0.5) are in `settings` too: `trainer.mode`, `commit.show_length`, `ladder.threshold`, `ladder.window`, `srs.intervals` and `ui.filters_collapsed`. Spaced-repetition boxes and depth-ladder levels have no table of their own: they're worked out from the `attempts` log each time (ARCHITECTURE.md §7).
- **AI settings** (v0.7) are in `settings` under `llm.*`: `llm.provider` (`none` / `anthropic` / `openai`), `llm.model.anthropic` and `llm.model.openai` (empty: none picked), `llm.reasoning`, `llm.run_cap_usd`, `llm.monthly_budget_usd` and `llm.prices_seed` (which seed of the price table has been added). The API keys are **not** there: they're in Credential Manager, in the same per-data-folder entry as the Lichess sign-in (`weaksquare-dev` for dev runs), under the account names `anthropic` and `openai`. The price table, usage log and Explain cache are the `llm_prices`, `llm_usage` and `llm_cache` tables in `user.db`. To test the budget without spending, add a price row with high prices for a model of your own.
- **Games and Game Review** (v0.8) are in `user.db`: `games` (the library), `account_sync` (where each account's sync got to, with chess.com ETags), `game_analysis` (one row per analyzed move), `custom_puzzles` (My puzzles: saved from games or imported from files) and `retry_attempts`. Their settings keys: `chesscom.username`, `games.sync_on_open`, `games.first_sync_days`, `games.first_sync_max`, `review.think_s`, `review.thresholds`, `review.tolerance_cp` and `review.key_moments`. `reasons.ask` gained `game_review`. To re-sync from scratch, delete the account's `account_sync` row; to re-analyze a game, use **Analyze again** or change `review.think_s` (changing `review.thresholds` regrades every stored game from its stored evals, without the engine).
- The game fixtures under `tests/fixtures/http/lichess_games/` and `chesscom/` are generated from the API docs; the service tests depend on their exact games, so the live recorder writes `recorded_*` files beside them instead of replacing them.
- Reset to a clean state for testing: close the app and delete the dev data folder, `%LOCALAPPDATA%\WeakSquare-dev`. Tests never need this, because each one gets a fresh temp folder.

## Database migrations
Schema changes are **new numbered files** in `adapters/db/migrations/puzzles/` or `adapters/db/migrations/user/`. Never edit a migration that has been applied.

To add one:
1. Create the next file in sequence, e.g. `src/weaksquare/adapters/db/migrations/user/0002_add_rated.sql`: four digits, a lowercase name, no gaps. Separate statements with `;`. New columns on `attempts` must be nullable (ARCHITECTURE.md §3 decision 4).
2. Add a test that migrates a database from the previous version and checks the change.
3. Run the app or the tests. `user.db` is migrated at startup, after a backup to `<data folder>\backups\user-<old version>-<timestamp>.db` (the last 5 are kept). A `user.db` with a newer version than the app knows is refused and left untouched (NFR-3).

`puzzles.db` is never migrated in place. Every import builds a new file from all the puzzle migrations, then creates the indexes in `adapters/db/puzzles_indexes.sql` after the bulk load.

When you add a puzzle migration, an existing `puzzles.db` has an older `schema_version` than the app knows. The app then shows **Upgrade the puzzle database**, which rebuilds the file from its own rows (`ExistingPuzzleDb` in `adapters/db/repos/puzzle_import.py`) through the same import path, with no download. The v0.2 upgrade (schema 1 → 2) adds the opening ids. A new column computed at import (like `opening_family`) needs its value derived from the CSV fields in `PuzzleDbWriter.add`, because the upgrade only replays those fields.

## Testing
Levels and when each runs: ARCHITECTURE.md §6. Rules:
- Tests mock `secret_store`, never `keyring`.
- HTTP fixtures are scrubbed when recorded, and a test fails if one contains a secret pattern. Placeholders: `lip_FAKE…`, `sk-ant-FAKE…`.
- Fixtures are anonymized: no real usernames, game IDs or URLs (SR-12a).
- Full-DB tests are marked `fulldb` and skip when the full puzzle DB isn't imported.
- Real-Stockfish tests are marked `engine` and skip when there's no install. Everything else uses `tests/fakes/engine.py` (in process) or `tests/fakes/uci_engine.py` (a real UCI subprocess that, like Stockfish 19, exits on an invalid position), so `build_services` in tests never starts a real engine.
- Live tests are opt-in (`-m live`) and use a separate `weaksquare-test` token (REQUIREMENTS.md SR-13). Contributors use their own Lichess account and token.

## How-to recipes
Each recipe is written when the first real example exists, using that example.
- Add a puzzle filter. The v0.1 side-to-move filter is the worked example:
  1. **Schema:** add the field to `FilterSpec` in `src/weaksquare/core/filters.py` with a default (usually one that means "no restriction"), plus its type check in `_coerce` and its rule in `validate()`. If the field already exists for a later version, remove it from the `later` dict in `validate()`, which rejects it until then. If its default isn't "no restriction" (like the v0.2 quality thresholds), bump `SAVED_FILTERS_VERSION` and teach `upgrade_saved` to give saved filters the new default once.
  2. **SQL:** add its condition to `build_where` in `src/weaksquare/adapters/db/repos/puzzles.py`. If it needs a new column or index in `puzzles.db`, add a puzzle migration and update `puzzles_indexes.sql`; the app then offers the local upgrade (see *Database migrations*). A filter on your own history joins `attempts` in user.db, which is the main schema of every connection (the v0.2 history filters are the example).
  3. **Tests:** extend `oracle_count` in `tests/integration/test_filter_count.py` with an independent version of the rule (plain SQL on the raw columns, or a set computed in Python), and let `random_spec` generate the field. The 40 random specs then cover it, on the fixture and with `-m fulldb`.
  4. **Bridge and UI:** run `uv run python scripts/gen_types.py`, add the field to `defaultFilters()` in `web/src/state/filters.ts` and to the mock's `matches()` in `web/src/api/mockClient.ts`, and add a control to `web/src/views/MixerView.tsx` (rarely used filters go in its **More filters** section).
  5. **Docs:** the User Guide's *Choosing your puzzles* table, and CHANGELOG.
- Add a training mode. Commit the line (v0.5) and Danger spotting (v0.6) are the worked examples:
  1. **Rules (pure):** a module in `src/weaksquare/core/modes/` with a state dataclass and a mode class that follows the `TrainingMode` protocol in `core/modes/base.py`: `start`, `start_practice` (FR-5.12), `on_move`, `on_help` and `give_up`. The attempt is decided **once** (`AttemptResult`), and help before it's decided is a loss (FR-5.2). A mode that isn't played move by move adds its own entry point and refuses `on_move` with `ConflictError`, as `CommitLineMode.on_submit` and `DangerMode.on_call` do. A mode that adds a step before the usual moves can subclass `StandardMode`, as `NameIdeaMode` does. A mode that only changes *which* puzzles you get, like Spaced repetition, reuses `StandardMode` and needs no class.
  2. **Unit tests:** `tests/unit/test_commit_line_mode.py` is the pattern: a known puzzle, every way the attempt can be decided, help before and after the end, practice and give-up.
  3. **Session:** add the name to `MODES` in `src/weaksquare/services/session.py` (and to `LADDER_MODES` if the depth ladder applies), register its mode object in `self._modes` and start its state in `_start_state`. A mode that needs Stockfish to set a puzzle up uses the interactive engine (`_require_engine`, as Danger spotting does). Anything the mode stores on the attempt goes in a new nullable `attempts` column (a user migration, see *Database migrations*), through `ModeFields` in `adapters/db/repos/user_data.py`. If the mode changes what the player knows in advance, check the angle rule (`angle_for` in `core/scoring.py`, REQUIREMENTS.md §8.3). A mode whose results shouldn't reach Lichess, Spaced repetition or the history filters is excluded the way `danger_spotting` is (`_record`, `srs_rows`, `SOLVED_IDS`/`MISSED_IDS`). Losses get the mistake-reason prompt automatically; if the mode has its own reason rule, add it to `core/reasons.py` and `_reason_base`.
  4. **Bridge:** add the name to `TrainingMode` in `bridge/dto.py`, to `TRAINING_MODES` in `services/ui_settings.py` and to `MODE_LABELS` in `core/stats.py`. A new entry point is a new `@bridge_call` method plus a line in `tests/contract/test_bridge_allowlist.py`. Then run `uv run python scripts/gen_types.py` and implement the method in `web/src/api/mockClient.ts`.
  5. **UI:** add it to the Modes control in `web/src/views/MixerView.tsx` (`MODES` in `web/src/state/modes.ts`) and, if it plays differently, a branch in `web/src/views/TrainerView.tsx`. Integration tests through the bridge (`tests/integration/test_modes_v05.py`, `test_modes_v06.py`) and a Playwright flow (`tests/e2e/test_modes.py`).
  6. **Docs:** the User Guide's *Training modes* chapter, REQUIREMENTS.md §6, and CHANGELOG.
- Add an LLM provider. Anthropic and OpenAI (v0.7) are the worked examples:
  1. **Name and prices:** add the provider to `Provider` and `PROVIDERS` (and `PROVIDER_LABELS`) in `src/weaksquare/core/llm/defaults.py`, its rows to `SEED_PRICES` (check them on the provider's pricing page), its cheapest model to `LIVE_TEST_MODEL`, and bump `SEED_VERSION` so existing installs get the new rows once. This file is the only place model names may appear: `tests/contract/test_no_model_names.py` checks `src/` and `web/src`. If the provider's model IDs don't match that test's pattern, extend the pattern so the test still guards them.
  2. **Adapter:** a module in `src/weaksquare/adapters/llm/` implementing `LLMProvider` (`core/llm/provider.py`), calling the API through `adapters/http.py` only, with the key per request (`token=` for a Bearer key, `headers=` for anything else). `generate` sends `max_tokens`, the reasoning level and the JSON schema as structured output, passes `retry=False` and `timeout=request.timeout_s`, and returns the text, the reported input and output tokens (reasoning included) and `truncated` / `refused` when the answer was cut short or declined. `test_key` must be a free call (a model lookup). Map failures with `llm_error` in `adapters/llm/__init__.py`, adding the provider's error codes there if they differ.
  3. **Key and wiring:** an account name for its key in `adapters/secret_store.py` (the provider's name), the key's prefix in `KEY_PREFIX` in `services/llm_settings.py` and in `scripts/set_test_token.py`'s `KEY_SHAPE` and `--llm` choices, and the adapter in `build_services` (`app.py`).
  4. **Tests:** a hand-written response in `tests/fixtures/http/llm/` (only the fields the parser reads, placeholders like `sk-FAKE…` for anything key-shaped), and the adapter's request shape, usage and error cases in `tests/integration/test_llm_adapters.py` (the parametrized error tests take a new provider class). `tests/fakes/llm.py`'s `fake_providers()` gets an entry, and `tests/live/test_llm_live.py` its `KEEP` and `FILE` entries.
  5. **Bridge and UI:** the provider in the `Literal`s in `bridge/dto.py` and `bridge/api.py` (then `uv run python scripts/gen_types.py`), `LlmProvider` in `web/src/api/ApiClient.ts`, the provider selects in `web/src/components/AiSettingsPanel.tsx` and `PriceTable.tsx`, and the mock's `SEED`, `LABELS` and `PREFIX` in `web/src/api/mockLlm.ts`.
  6. **Docs:** the User Guide's *AI explanations and what they cost* chapter and its privacy section (which host it talks to), REQUIREMENTS.md §2, §9.2 and §16 (prices), an ARCHITECTURE.md §7 entry, and CHANGELOG.

## Dependencies
Add a dependency only when the version plan lists it. Check the exact package name on PyPI or npm first, add it with `uv add` or `npm.cmd --prefix web install`, and commit `uv.lock` or `package-lock.json` with an ARCHITECTURE.md §7 entry. CI installs only from the lockfiles (`uv sync --locked`, `npm.cmd --prefix web ci`).

## Continuous integration
`.github/workflows/ci.yml` runs on every push and pull request on a Windows runner: static checks, unit, integration and contract tests on the small fixture, and `check_docs.py`. The real-app smoke, full-DB and live tests run locally only.

## Contributing
Open an issue first for anything bigger than a fix. Pull requests follow the same rules as the main build: tests with every fix, docs and CHANGELOG in the same commit, no new dependency without discussion. By contributing you agree your work is licensed under AGPL-3.0-or-later.

## Releasing a version
Follow the nine steps in ROADMAP.md and the entry rules at the top of CHANGELOG.md. A release is a git tag plus a GitHub Release with the CHANGELOG notes; there's no packaged executable.
