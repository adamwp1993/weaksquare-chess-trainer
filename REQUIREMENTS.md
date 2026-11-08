# WeakSquare Chess Trainer: Requirements

**Owner:** Adam
**Status:** Requirements agreed, ready to build
**Last updated:** 2026-10-31

---

## 1. Purpose

A single-user Windows desktop app for chess tactics training, built on the public Lichess puzzle database. It's open source (AGPL-3.0-or-later, §15). It solves three problems Lichess's own puzzle trainer doesn't:

1. **Full control over the puzzle set.** Mix any combination of themes, ratings, lengths and other filters. Lichess only allows one theme at a time or its own "healthy mix."
2. **Training calculation, not just pattern-spotting.** Modes that force you to see the whole line ahead, recognize multi-step combinations ("the fork square is guarded, so remove the defender, then fork") and spot the opponent's tactics before they happen.
3. **Understanding why.** When stuck: a hint, then the answer with Stockfish refuting your wrong move, then an optional plain-English LLM explanation drawn on the board.
4. **Knowing what to train.** A Coach analyzes your own games (Lichess and/or chess.com) and your puzzle history. Stockfish finds the tactics you **missed** and the tactics you **allowed**, and the Coach recommends puzzle sets to fix them. The Coach's findings set the **suggested default puzzle mix**, so training starts at your actual level. Every 10 games it runs a **checkpoint** and tracks whether each weakness is actually shrinking in your games. Advanced multi-step combinations (e.g. deflection into fork) are always available but are only mixed in when your games call for them. LLM coaching is optional and capped by a budget.
5. **Reviewing a single game.** Link your Lichess and chess.com accounts, and your games show up in an in-app library. You can also import any game by PGN or link. Stockfish grades every move, and the AI optionally explains what the better moves were and why. Key moments can be retried or saved as your own puzzles.

Solves sync to the user's Lichess account so they count toward their real puzzle rating and history.

### Non-goals
- Writing a chess engine. Stockfish does the analysis, and a rules library handles legality.
- Mobile or multi-user support. macOS and Linux are out of scope **until v1.1** (ROADMAP.md).
- BSD and other Unix systems: no official Stockfish builds, so not planned.
- A packaged installer or signed `.exe`. The app runs from source: clone, run `scripts/setup.py`, launch from the shortcut it creates (§15, §17).
- Online play of any kind.

---

## 2. Platform and stack

| Layer | Choice | Notes |
|---|---|---|
| OS | **Windows** (10/11, x64) | Only target through v1.0. macOS and Linux are planned for v1.1 (ROADMAP.md); until then, OS-specific code stays in adapters and new features don't assume Windows |
| App shell | **pywebview** window using **WebView2** (Chromium-based Edge) | Native window, web UI inside |
| Backend | **Python** (3.12+) | Thin: data, auth, engine, sync, LLM calls |
| Database | **SQLite** (`sqlite3`) | Puzzle DB + all user data, local |
| Rules / engine bridge | **python-chess** | Legality, SAN/UCI, attack maps, UCI engine control |
| Engine | **Stockfish 19**, native Windows binary, downloaded and hash-checked at setup, never committed | Run by the backend over UCI. Not WebAssembly |
| Board UI | **chessground** (Lichess's board) | Drag/drop, animation, SVG arrows and circles |
| Front-end legality | **chess.js** | Legal-move destinations for chessground |
| Secrets | **keyring** → Windows Credential Manager | Lichess token, LLM API key |
| HTTP | `httpx` (or `requests`) | Lichess API, LLM APIs |
| LLM providers | **Anthropic** and **OpenAI** | Behind one small provider interface |
| Mistake tagging | **lichess-puzzler** tagger (Python, AGPL-3.0) | Lichess's own puzzle theme tagger, so game mistakes get the same theme names as the puzzle DB |
| Game sources | Lichess API; chess.com Published-Data API | Read-only, used by the Coach |

**Decided:** front end = React + TypeScript + Vite + Mantine (see ARCHITECTURE.md §3). **Decided:** runs from source, no packaged `.exe` (NFR-8; ARCHITECTURE.md §7). **Decided (v0.7 planning, Adam):** no default model is pre-selected; you pick one from the price table's models (FR-1.3).

---

## 3. Application flow

### 3.1 Startup page
Shown when the app launches.

- **FR-1.1** "Sign in with Lichess" button runs the OAuth PKCE flow (§8.1). Shows status: *Not signed in* / *Signed in as `<username>`* / *Sign-in failed (reason)*.
- **FR-1.2** LLM provider dropdown: *None*, *Anthropic*, *OpenAI*.
- **FR-1.3** Model field for the selected provider: a dropdown of every model in the price table (`llm_prices`) for that provider, each with its rough cost per Explain, and you can also type any other model ID. **Nothing is pre-selected** (Adam, v0.7 planning): until you pick a model, Test key checks only the key and Explain asks you to pick one. A model with no row in the price table can't be used until you add its prices (FR-8.9). Model names must not be hard-coded anywhere outside the provider defaults module (`core/llm/defaults.py`), which also seeds the price table.
- **FR-1.4** API key field (optional, masked) with a **Test key** button that makes a minimal API call and reports success or the error. The call is the provider's free model lookup (`GET /v1/models/{model}`, or `/v1/models` when no model is picked), so testing a key costs nothing. The FR-1.6 silent test uses the same call.
- **FR-1.5** **Continue** button goes to the main page.
- **FR-1.6** **Fast path:** if a stored Lichess token validates against `GET /api/account`, and either no LLM is configured or the stored key passes a silent test, the page shows a single **Continue as `<username>`** button, listing the linked chess.com username if there is one. A link expands the full form.
- **FR-1.11** **Linked accounts panel:** Lichess (the signed-in account, FR-1.1) and an optional **chess.com username** with a **Verify** button (§11.5). Either account can be unlinked here or in the gear settings.
- **FR-1.7** **Offline / sign-in failure:** the user can always continue without being signed in. Solves are recorded locally and queued for sync (§8.4). The main page shows an "Offline: N solves waiting to sync" indicator.

### 3.2 Main page
- Puzzle filters and queue controls (§5), training-mode selector (§6), board, the stuck ladder (§7.2), **Coach** button (§10), **Import game** button (§11), stats (§12).
- **FR-1.8** **Gear icon** opens the same settings as the startup page (linked Lichess and chess.com accounts, game-sync options, LLM provider/model/key, engine settings) plus the **LLM price table and budget** (§9.3), without leaving the main page.
- **FR-1.10** A small **LLM spend indicator** (this month's spend vs. budget) appears whenever an LLM is configured.
- **FR-1.15** **A model per AI feature** (Adam, 2026-11-03, during the v0.7 manual test; built in **v0.9**, when the second AI feature arrives). Cheap, frequent requests and rare, demanding ones need different models: for example Haiku for puzzle Explain and Opus for the Coach. v0.7 has one provider and model for everything (FR-1.2, FR-1.3).
  - **Each AI feature gets its own provider and model:** puzzle **Explain** (§9.2), **Game Review** (Explain this move and Explain my game, FR-11.17, FR-11.18) and, from v0.10, the **Coach** (§10.6, §10.11). Each picker works like FR-1.3: the price table's models with their rough cost for that feature, typed IDs allowed, and a model with no price row can't be used.
  - **Shared, not per feature:** API keys stay one per provider (one key serves every feature that uses that provider), along with the price table and the monthly budget (FR-8.13). The per-run cap (FR-8.12) applies to each request. The usage log already records the feature (FR-8.10), so Settings can show this month's spend per feature.
  - **Caching** already includes the model (FR-8.6, FR-11.20), so changing a feature's model never shows another model's saved answer.
  - **Decided at v0.9 planning (Adam, 2026-11-04):**
    - A feature without its own choice uses **Explain's provider and model** ("Same as Explain"). The Review page also has a model dropdown that sets Game Review's model (the same setting as Settings → AI).
    - **Reasoning (FR-8.15) is per feature**; the per-run cap (FR-8.12) and the monthly budget are shared.
    - The startup page's short form shows **both pickers**: Explain's model and Game Review's ("Same as Explain" by default).
- **FR-1.9** **Rated toggle** (session-level, default ON). When off, every solve this session syncs as `rated: false`.
- **FR-1.14** **Collapsible filters panel** (Adam, v0.5 planning). A **Hide filters** button at the top of the left panel collapses it to a slim strip, so the filters stay out of the way while you play. The strip shows **Show filters**, the training mode, a one-line summary of the filters with the match count, and the Rated state, and the trainer widens into the space. Expanding brings the panel back exactly as it was. The collapsed/expanded state is saved in `user.db` through the bridge (never browser storage) and survives a relaunch; the default is expanded. Starting a session doesn't collapse it by itself. The **F** key toggles it.
- **FR-1.12** **Appearance: dark mode.** A color-scheme setting with **Light** / **Dark** / **Match system** (default **Light**), reachable from the main menu (and from the gear settings once FR-1.8 exists). It applies immediately to every screen (filters, trainer, dialogs, importer, About, Stats) without a restart, and is saved in `user.db` through the bridge (never browser storage, ARCHITECTURE.md §3), so it survives a relaunch. The app starts in the saved scheme without flashing the other one first where WebView2 allows. *Match system* follows the operating system's light/dark setting (the Windows app theme today) and updates if it changes while the app is open. The name is OS-neutral so it carries over to v1.1. The board and pieces stay readable in both schemes, and text keeps at least WCAG AA contrast.
- **FR-1.13** **Move sounds.** Short sound effects on the board, for your moves and the opponent's alike:
  - **Events:** move, capture, check, checkmate (a checkmate plays only the mate sound), castling (uses the move sound unless the set has its own), puzzle solved and puzzle failed.
  - **Setting:** a **Sounds** on/off toggle, a volume slider and a **sound set** picker, reachable from the main menu (and the gear settings once FR-1.8 exists). The default is **on**, at 70% volume, with the **sfx** set. *(Decided at v0.2 planning: the four Lichess sets by Enigmahack, **sfx**, **piano**, **nes** and **futuristic**, which lila's `COPYING.md` lists as AGPLv3+. Lichess's "standard" set is a non-free exception there and isn't used. None of the four has a castling sound, so castling plays the move sound. Their `Checkmate` file is a symlink to `Check` in lila, so a mate plays the check sound file, still as the only sound for that move. In the sfx set, "puzzle solved" plays its `GenericNotify` instead of `Victory`, which Adam found too loud in the v0.2 manual test.)* The setting applies immediately, without a restart, and is saved in `user.db` through the bridge (never browser storage).
  - **Behavior:**
    - Sounds play from local files bundled with the front end. No CDN, no network.
    - A sound never delays the board or the next puzzle.
    - Rapid moves cut the previous sound off rather than queueing.
    - Off means fully silent; nothing is loaded or played.
    - The opponent's first move plays a sound even before you've clicked anything; WebView2's autoplay policy has to allow this.
  - **Assets must be licensed for an AGPL project** (§15): CC0 or another AGPL-compatible license, or sounds made for this project. **Never** copy sounds from chess.com or any other proprietary app. Lichess's sound sets are a candidate only after their license is checked in the plan. The source and license of every file are recorded in `web/public/sounds/CREDITS.md` and in ARCHITECTURE.md §7.

---

## 4. Puzzle data

### 4.1 Source
- Lichess open puzzle database: `lichess_db_puzzle.csv.zst` from database.lichess.org. Public domain, ~6M puzzles as of the 2026-07-29 export.
- **FR-2.1** First-run importer: download (or accept a local file path), decompress the zstd stream, and import into SQLite with a progress bar. It must be **resumable or restartable** and must not block the UI.
  - **FR-2.1a** The importer page states plainly that **Download from Lichess** fetches the **entire** Lichess puzzle database (every puzzle, not a sample or a starter set): about 300 MB compressed, about 6 million puzzles, roughly 1.5 GB on disk once imported. After the import, the match count with no filters equals the imported puzzle count. The User Guide uses the same wording.
- **FR-2.2** Read the CSV **by header name, not column position**, and tolerate extra columns. The current export documents a `DailyDate` field in addition to the classic columns:
  `PuzzleId, FEN, Moves, Rating, RatingDeviation, Popularity, NbPlays, Themes, GameUrl, OpeningTags`
- **FR-2.3** Re-import of a newer export **never touches user data** (attempts, SRS, presets, cache). It builds a new `puzzles.new.db` and swaps it in only when the import finishes and passes a row-count and integrity check. A failed or cancelled import leaves the current database untouched, and restarting simply starts the new file over.
- **FR-2.4** A newer export can drop puzzle IDs you've already attempted. Stats, SRS, history and the Coach treat a missing puzzle as "no longer in the database" (left joins, no crash), and the queue skips it.
- **FR-2.5** **Update check and prompt.**
  - **How it checks:** a background check, never blocking startup and silent when offline. It fetches `sha256sums.txt` and sends a `HEAD` request for the puzzle file (`Last-Modified`, `Content-Length`), all through `adapters/http.py`. A newer export exists when the published SHA-256 differs from the `sha256` in `puzzles.db`'s `meta`. If `meta` has no hash (a local-file import), it compares `Last-Modified` with `export_date` instead.
  - **When:** automatically at launch at most once a day (injected `Clock`, last check time saved in `user.db`), plus a **Check for updates** button in the update dialog. A setting turns the automatic check off. It's on by default.
  - **The prompt:** a non-blocking banner, never a modal mid-puzzle. Example: *"A newer puzzle database is available (exported 2026-11-01, yours is from 2026-10-02). Download about 295 MB?"* It offers **Update now** (starts the FR-2.3 import), **Not now** (asks again next launch) and **Skip this export** (stays quiet until a newer one than the skipped hash appears).
  - **Puzzle count before downloading:** the database.lichess.org page lists a count, which the app reads best-effort as *"about N puzzles (+M)"*. The page can lag the file, so the count is labeled approximate. If it's missing or can't be read, the line is left out and the check still works.
  - **Exact numbers after the import:** before the swap, the import compares puzzle IDs between the old and new database. The finish message reports the exact numbers: *"6,201,004 puzzles: 44,112 new, 450 removed."* Removed puzzles you'd attempted are handled as in FR-2.4.
  - **What it sends:** only these plain requests to database.lichess.org. Nothing about you or your training.

### 4.2 Semantics (critical)
- `FEN` is the position **before the opponent's move**. The first move in `Moves` is the opponent's. Apply it, animated, then the player solves from move 2 onward.
- **Player color** is the side **not** to move in the FEN.
- `Moves` are in UCI notation.
- **Puzzle length** (player moves) = `len(Moves) // 2`. Map 1 → one-move, 2 → short, 3 → long, ≥4 → very long. Compute from moves instead of trusting the tags.
- All player moves in a solution are "only moves," **except mate-in-one**. If the solution's next player move delivers checkmate, **any** checkmating move is accepted.
- `OpeningTags` is only populated for puzzles starting before move 20.
- `Themes` is space-separated. Display names and groups come from Lichess's theme list (`translation/source/puzzleTheme.xml` in the lila repo).

### 4.3 Schema (suggested)
- `puzzles(n PK, id UNIQUE, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url, opening_tags, length, player_color, t0, t1, t2)`. `t0`–`t2` are theme bitmasks (62 bits each), with the bit for each theme in `theme_bits(theme, bit, count)`. A covering index on `(rating, length, player_color, t0, t1, t2, popularity, nb_plays)` serves the live count. The opening filter (v0.2) uses `opening_family` and `opening_variation`, integer ids into `openings(id, tag, family_id, count)` built at import, each with an index on `(opening_…, rating)`. *(Decided in v0.1 instead of a `puzzle_themes(puzzle_id, theme)` table, which was too large and slow for ALL counts; see ARCHITECTURE.md §7.)*
- `meta(key, value)` in `puzzles.db`: row count, rating range, export date, SHA-256, import time.
- `attempts(id, puzzle_id, mode, started_at, finished_at, win, help_used, first_move_correct, line_correct, time_ms, puzzle_rating, rated, angle, sync_status, synced_at, rating_diff)`. `puzzle_rating` (v0.2) is the puzzle's rating when you played it, so Stats' rating bands survive a re-import.
- `lichess_history(puzzle_id PK, win, played_at)`, imported from Lichess (§8.4).
- `srs(puzzle_id PK, box, due_at)`
- `presets(name PK, filters_json, created_at, updated_at)`
- `llm_cache(key PK, provider, model, response_json, input_tokens, output_tokens, created_at)`
- `settings(key PK, value)`. **Non-secret only.**
- `llm_usage(id, ts, feature, provider, model, input_tokens, output_tokens, cost_usd)`, used for the budget (§9.3)
- `llm_prices(provider, model, input_per_m, output_per_m, long_ctx_threshold, long_input_per_m, long_output_per_m, as_of)`, editable
- `games(id PK, source, source_game_id, url, pgn, played_at, time_control, time_class, rated, user_color, user_rating, opponent, opponent_rating, result, eco, opening, platform_accuracy_user, platform_accuracy_opp, has_evals, analysis_status, fetched_at)`: the game library (§11.5), shared by Game Review and the Coach. `analysis_status` is none / analyzed / ai_reviewed.
- `account_sync(platform PK, username, last_sync_at, last_archive, etag_json)`: incremental sync state per linked account
- `coach_checkpoints(id PK, created_at, trigger, games_total, new_games, window_size, report_id, suggested_preset_json, ai_summary_json, cost_usd)`: one row per checkpoint (§10.8)
- `weaknesses(id PK, key, kind, label, first_seen_checkpoint, baseline_rate, baseline_games, status, status_changed_at, related_themes)`. `key` is a theme or simple-tag key; `kind` is missed / allowed / habit, plus opening / endgame / phase / time from v0.11 (FR-10.57).
- `weakness_metrics(weakness_id, checkpoint_id, window_games, occurrences, game_rate, puzzle_attempts, puzzle_first_try_accuracy)`: the trend data for each weakness at each checkpoint
- `game_analysis(game_id, ply, fen_before, move_uci, mover, eval_before, eval_after, best_move, multipv_json, cp_loss, classification, themes, kind, phase, low_clock)`: one row per analyzed move. Shared by Game Review (§11) and the Coach (§10). `kind` is missed / allowed / other for mistakes.
- `game_errors`: a **view** over `game_analysis`, containing the user's mistakes only, used by the Coach
- `custom_puzzles(id PK, game_id, ply, fen, solution_uci, themes, origin, kind, severity, cp_loss, phase, time_control, game_date, solve_as, status, created_at, UNIQUE(game_id, ply))`: puzzles from your own games. `origin` is manual (Save as puzzle, FR-11.16) or coach (FR-10.39). `kind` is missed / allowed. `severity` is inaccuracy / mistake / blunder. `solution_uci` holds the full line. `solve_as` is you / opponent. `status` is active / archived. They live in `user.db`, never `puzzles.db`, which is replaced on every re-import (FR-2.3). Their attempts are stored in `attempts` with ids prefixed `my:`.
- `mistake_reasons(id PK, source, ref_id, reason, suggested_reason, note, created_at)`: why you missed something (§7.3). `source` is puzzle / game / retry / danger; `ref_id` points to an `attempts` row or a `game_analysis` (game_id, ply).
- `coach_reports(id, created_at, sources_json, params_json, report_json, provider, model, cost_usd)`
- `game_digests(game_id PK, analysis_key, digest_json, built_at)`: one game digest (FR-10.52), rebuilt when the analysis changes (v0.11)
- `coach_ai_runs(id, report_id, created_at, advanced, include_notes, game_cap, provider, model, cost_usd, result_json)`: every AI coaching answer for a report, so a standard and an Advanced run can be compared (v0.11 planning)
- `coach_observations(id, subject, topic_key, category, title, first_report_id, last_report_id, times_seen)`: findings that can't be measured, noted when they recur across runs (FR-10.57)
- `training_plans(id, created_at, report_id, source, ai_run_id, weeks, weekdays_json, minutes_per_day, start_date, status, ended_at)`, `plan_days(id, plan_id, week, position, date)` and `plan_tasks(id, day_id, position, type, weakness_key, minutes, title, params_json, manual_state, manual_at, skipped_at, done_at, carried_from, swapped_from, removed)`: training plans (FR-10.61–10.66, v0.12). At most one plan is `current`; old plans stay as history. `sessions.plan_task_id` links a session to the puzzle task that started it.
- `review_passes(id, game_id, plan_task_id, plies_json, started_at, completed_at)`: each pass through a game in Game Review and the moves you visited, for the review task and the daily log (FR-10.64, 10.68, v0.12). `games.analyzed_at` records when a game was analyzed (v0.12; older games have none).
- `journal_entries(id, created_at, updated_at, entry_date, kind, text, game_id, ply, weakness_key, plan_day_id, plan_task_id)`: your notes and game reflections (FR-10.67, 10.69, v0.12). `coach_ai_runs` gains `include_journal` and `journal_hash` (FR-10.71).

---

## 5. Puzzle selection: full user control

Every control changes the pool, and the **live match count** updates as you edit (debounced; target under 500 ms on the full DB).

| ID | Control | UI | Behavior |
|---|---|---|---|
| FR-3.1 | **Themes** | Dropdown with grouped checkboxes (Phases, Motifs, Advanced, Mates, Mate patterns, Special moves, Goals, Origin), a search box, and **Select all / Clear** | Match mode toggle: **ANY** (OR) or **ALL** (AND) |
| FR-3.2 | **Excluded themes** | Same picker, separate list | Puzzles with any excluded theme are removed |
| FR-3.3 | **Rating** | Two-handle range slider plus numeric min/max inputs | Bounds come from the dataset (~400 to ~3,400) |
| FR-3.4 | **Number of moves** | Dropdown checkboxes: 1 / 2 / 3 / 4+ and **All** | Uses the computed `length` |
| FR-3.5 | Side to move | White / Black / Either | Player color |
| FR-3.6 | Phase / goal / origin | Covered by the theme picker groups | e.g. endgame, mate, crushing, master games |
| FR-3.7 | Opening | Searchable multi-select from `OpeningTags` | e.g. Italian Game, Caro-Kann, London |
| FR-3.8 | Quality | Min popularity, min plays | On by default at **popularity ≥ 50** (Lichess popularity runs from -100 to 100) and **≥ 100 plays**; both adjustable, and clearing a box turns that threshold off. Measured on the 2026-11-01 export: the defaults leave out 21.9% of puzzles (mostly the plays minimum); kept as is by Adam after seeing that number. The puzzles stay in the database; this only narrows the selection |
| FR-3.9 | History | Checkboxes: exclude solved here / exclude played on Lichess / **only my misses** | Uses `attempts` and `lichess_history`. *Exclude solved here* (**on by default**) hides puzzles you've **won at least once** in this app; ones you only failed can still come up. *Only my misses* (off by default) keeps only puzzles whose **latest** attempt here was a loss, so a miss drops out once you solve it. *Exclude played on Lichess* (**on by default**, decided at v0.3 planning) hides puzzles in your imported Lichess history (FR-6.17) and those you've synced from here, because Lichess never changes your rating for a puzzle you've already played; with no imported history it changes nothing. Danger-spotting results (FR-4.4) don't count for these filters (Adam, v0.6 planning). |
| FR-3.10 | **Ratios** (optional) | Weighted buckets, e.g. 50% fork, 30% capture-the-defender, 20% one-move | Draws from each bucket by weight |
| FR-3.11 | Order | Random / easy → hard / grouped by theme / **depth ladder** | Depth ladder (FR-4.5, added as an order at v0.5 planning) works in Standard and Commit the line. It sets the move count itself, so the Number-of-moves control is disabled while it's chosen, and it can't be combined with ratios. |
| FR-3.12 | Queue size | Fixed N or endless | |
| FR-3.13 | **Presets** | Save / load / rename / delete named filter sets. *(Adam, 2026-11-04, during the v0.11 build:)* **Update** a loaded preset with the current filters; **Manage presets** lists every preset (unusable ones too) to overwrite, rename or delete without loading it; a Coach preset saved under a name you already use offers **Replace it** or another name | Stored as JSON |
| FR-3.14 | Hidden labels | Themes are **not shown** while solving | Revealed after the puzzle ends |
| FR-3.15 | Puzzle source | Lichess DB / **My puzzles** / Both | "My puzzles" = `custom_puzzles`: saved from Game Review (§11), imported from your own files (§10.10) or created by the Coach (§10.9). These never sync to Lichess. Extra filters for My puzzles: origin, set label, Missed / Allowed, phase, time control; severity level (FR-10.40) from v0.10. Themes, rating, openings, quality, played on Lichess, ratios and the orders other than Random (easy → hard, by theme, depth ladder) apply only to Lichess puzzles: with My puzzles or Both, the order is random. *(v0.10 planning: ratios also work with **Both**, where each ratio group is a Lichess pool and My puzzles fill a fixed share of the slots, `my_share`, used by the Suggested mix, FR-10.44. Without a share, Both mixes by pool size as before.)* Number of moves, side to move and the history filters apply to both. **Both** mixes the two pools in proportion to their sizes. In v0.8 My puzzles works in Standard, Commit the line and Spaced repetition; Name the idea and Danger spotting stay Lichess-only. A custom puzzle starts from the position you solve (no opponent move first). *(Adam, v0.8 planning: renamed from "My games".)* |

---

## 6. Training modes

All of these ship in version 1. You pick a mode per session from the **Modes** control at the top of the filters panel on the main page (the last one used is remembered through the bridge; Standard on a fresh install). Switching the mode while a session is running starts a new session in that mode, with the current filters and Rated toggle, the same as pressing Start. Modes from later versions don't appear in the control until they ship. *(Adam, v0.5 planning: Depth ladder became an **order** (FR-3.11) that works in Standard and Commit the line, rather than a mode of its own.)*

| ID | Mode | How it works | Win condition | Syncs to Lichess |
|---|---|---|---|---|
| FR-4.1 | **Standard** | Lichess-style: you move, the opponent's reply plays automatically | Every player move correct, no help used | Yes |
| FR-4.2 | **Commit the line** | Plan mode: you play **both sides** of the full line on the board (your moves plus the replies you expect), with nothing validated (legal moves only, no feedback, no automatic replies; Undo and Clear), then press **Submit**. The line is then graded against the solution, move by move by position in the line. **The solution's length is hidden by default**, so you decide where your line ends: missing moves of yours count as wrong, and moves past the end of the solution are ignored. A **Show move count** switch (this mode only, saved through the bridge) shows "Find N moves" and stops the entry at the solution's length; because you then know the length in advance, the angle is the puzzle's length theme when the themes are All (§8.3). Where every earlier move matched, any mating move is accepted where the solution mates (§4.2). Before Submit, Hint (the piece that makes your first move) and Show answer count as a loss, as in Standard; after it they're free. The result shows your line with each move marked right or wrong. *(Adam, v0.5 planning.)* | Every **player** move matches. Predicted opponent replies are scored separately as "calculation accuracy" (replies predicted ÷ the solution's replies, stored on the attempt) and don't affect the win. | Yes |
| FR-4.3 | **Name the idea first** | Before moving, you tag the idea: setup motif(s) and payoff motif(s), at least one tag and at most 3 per slot. The board takes moves once you press **Start solving**. Then you solve normally. Afterwards your tags are compared to the puzzle's **motif themes** (its themes in the Motifs, Advanced, Mate patterns and Special moves groups), whichever slot you put them in, since Lichess doesn't record which role a theme plays: "Ideas found 2 of 3 · 1 extra". A puzzle with no motif themes has no tag score. *(Adam, v0.6 planning: the target square / defender tag was dropped, because Lichess puzzles carry no data to grade it.)* | Same as Standard. Tag accuracy is a separate stat: **ideas found** (named ∩ puzzle ÷ the puzzle's motifs) and **tags right** (named ∩ puzzle ÷ named). | Yes |
| FR-4.4 | **Danger spotting** | Shows the **pre-blunder position** (the raw FEN) from the side that's **about to blunder**, with a candidate move highlighted. You answer **Safe** or **Unsafe**. If Unsafe and the move really is the blunder, it's played, the board turns to the punishing side and you play **the first move of the refutation** (the puzzle's first solution move, or any mating move where the solution mates); the rest of the line is in the answer. Candidates are about 50% the real blunder and 50% a **Stockfish-verified safe move**, so the answer is never always "Unsafe." A move is **safe** if Stockfish (MultiPV 5 from the blunderer's side, your think time) rates it at most **50 cp** worse than its best line and it doesn't allow a mate; it's never the real blunder. One is picked at random among the safe moves (the best move included). If none qualifies, that puzzle shows the blunder and the next one is owed a safe candidate. The mode needs Stockfish: without it, Start is disabled. Stockfish looks at **every** position before it appears, safe or not, and each one appears no sooner than the engine think time, so the wait never gives the answer away (v0.6-B1, B9). After a correct Unsafe, evals are worded from the punishing side, the side you then play (v0.6-B5). Before your call, Hint isn't offered and Show answer counts as a loss; while you play the refutation, help works as in Standard. The real blunder is never sent to the front end before the puzzle ends. Results are **local only**: they show in Stats and mistake reasons, but don't enter Spaced repetition (FR-4.6) or the history filters (FR-3.9). *(Adam, v0.6 planning.)* | Correct Safe/Unsafe call, plus the correct refutation when Unsafe | **No** (local stats only; this doesn't correspond to solving the Lichess puzzle as served) |
| FR-4.5 | **Depth ladder** (an **order**, FR-3.11) | For the selected themes (All is allowed), serves short puzzles (2 moves), then long (3), then very long (4+), moving up a level once accuracy is at least the threshold over a rolling window of attempts at the current level (default 80% over the last 20; both configurable in the settings). Your level is kept per theme set (the selected themes, match mode and excluded themes) and worked out from the attempts log, so it carries over between sessions; it never drops. Try-again practice runs never count. On a level-up the session continues at the new level. Levels with no puzzles under the current filters are skipped: you start at the first level that has puzzles, moving up goes to the next one that has, and the last one is the top (v0.5 QA, B2). | Same as the mode it's used in | Yes. The ladder sets the move count, so the angle is the matched theme, or the length theme when the themes are All (FR-6.14). |
| FR-4.6 | **Spaced repetition** | Missed puzzles come back on a Leitner schedule (default boxes: 1, 3, 7, 14, 30 days; editable in the settings, 2–10 boxes, increasing). **A loss in any mode** except Danger spotting (misses from before v0.5 included) puts the puzzle in box 1. A loss later tagged Misclick (FR-5.10) still counts here. Only a **win in this mode** moves it up a box; a win from the last box **graduates** it (no longer scheduled), and a later loss anywhere puts it back in box 1. Due dates are by local calendar day (a miss in the evening is due the next morning, not 24 hours later). A session serves the puzzles that are due, most overdue first; the filters don't apply (they're greyed out, and the panel shows how many are due and when the next one is). With nothing due, Start is disabled. The angle is `mix`. Moves work as in Standard. For testing, `--dev` runs have a **fast-forward time** setting that moves the app's clock ahead by N days, with a banner while it's on; it isn't available in the real data folder. *(Adam, v0.5 planning.)* | Same as Standard | Yes. Lichess won't change your rating for a puzzle you've already played, so the app shows an "already played: rating unaffected" badge. |

---

## 7. Scoring and the "stuck" ladder

### 7.1 Scoring rules
- **FR-5.1** A **win** means the full line was solved with no wrong move and **no help used**. This matches Lichess's definition.
- **FR-5.2** **Any help before completion counts as a loss:** Hint, Show answer or Explain.
- **FR-5.3** A wrong move is a loss. The puzzle then continues so you can see the solution, with nothing more to lose.
- **FR-5.4** After a puzzle ends (win or loss), Show answer and Explain are free. Show answer stays available after the end: clicking it again closes the analysis board and any line being shown, and goes back to the start of the solution. On the analysis board, **Close** reads **Back to the answer** when there's an answer to go back to. (Adam, v0.4 manual test.)
- **FR-5.12** **Try again (not scored):** after a puzzle ends, **Try again** resets the board to the puzzle's start and lets you solve it again with the usual feedback and replies. It's practice: nothing is recorded, nothing is sent to Lichess, and the result shown for the puzzle stays the one from your first attempt. Hint and Show answer are free while practising. The engine stays hidden until the practice run ends, as in any puzzle (FR-7.3). (Adam, v0.4 manual test; chosen over letting Reset clear the result, because the first result may already be on Lichess.)
- **FR-5.5** Record per attempt: `first_move_correct`, `line_correct`, `help_used` (none / hint / answer / explain), and `time_ms`.

### 7.2 Stuck ladder (each step unlocks the next)
1. **Hint**: highlights the piece that moves next. Counts as a loss.
2. **Show answer**: plays the solution step by step with back/forward controls. If you played a wrong move earlier, **Stockfish's refutation** of that move (the best reply line, 3–5 plies, with eval) appears above the answer as *Why <move> fails*, with its own **Show me** to step through it on the board. The answer itself is always the correct solution (Adam, v0.4 manual test: it used to start with the refutation). Counts as a loss.
3. **Explain** (only if an LLM is configured): see §9. Counts as a loss. In practice it's available once the puzzle is over (like the engine, FR-7.3), and it comes after Show answer, which already decided the attempt, so Explain itself never changes a result (v0.7 planning).

---

### 7.3 Mistake reasons (why you missed it)
Habit tags (FR-10.27) and themes describe **what** went wrong. Mistake reasons record **why**, so the app can tell a *knowledge* gap (learn the pattern) from a *process* gap (you knew it but didn't look). The two need different training.

- **FR-5.6** **Reason set** (pick one; an optional short note can be added):

  | Key | Label | Gap type |
  |---|---|---|
  | `didntLook` | Didn't look for it | Process |
  | `missedResource` | Missed their reply / defense / threat | Process |
  | `miscalculated` | Saw the idea, calculated it wrong | Calculation |
  | `unknownPattern` | Didn't know this pattern | Knowledge |
  | `rushed` | Rushed / time pressure | Time |
  | `misclick` | Misclick | Noise |

- **FR-5.7** **Where it's asked:**
  - after a **failed puzzle** (wrong move, or any help used), in every mode
  - on each of **your mistakes** in Game Review (key moments and the move list)
  - after a **Retry-mode miss** (FR-11.15)
  - after a **Danger-spotting miss**
- **FR-5.8** **One click, never blocking:** a row of 6 reason chips below the board, with keyboard shortcuts **1–6** and a Skip option. The next puzzle loads as normal, and the chips stay available on the result panel until you move on. A setting controls how often you're asked: *Always* / *Game Review only* / *Off*. Until Game Review ships (v0.8) it offers *Always* / *Off* (v0.6 planning); v0.8 adds *Game Review only*. Practice runs (FR-5.12) never ask. You can change the reason until you move on; the latest choice counts.
- **FR-5.9** **Suggested reason:** the app pre-highlights a likely reason, but it's only saved when you click it.
  - `rushed`: move made in under 3 s (configurable), or a game move made with a low clock
  - `miscalculated`: first move correct, later move wrong (puzzles), or the right idea's first move was played but the continuation failed (games)
  - `missedResource`: your move was refuted by an opponent reply that is a check, capture or tactic
  - `unknownPattern`: in Name-the-idea mode, your tags didn't include any of the puzzle's motif themes (FR-4.3)
  - Danger spotting: calling the real blunder Safe suggests `missedResource` (v0.6 planning)
  - When several match, the first in this list wins. `rushed` is measured from when the position appeared to the deciding move, Submit or call. `missedResource` uses Stockfish's refutation (a first reply that's a check or capture, or a mate against you), so it's only suggested when the engine is installed.
  - No suggestion otherwise
- **FR-5.10** **Misclick handling:** a `misclick` attempt is **excluded** from local accuracy stats and weakness metrics, and counted separately: the Stats page, the session bar's accuracy and the depth-ladder window (FR-4.5) leave it out; Spaced repetition still schedules the puzzle (Adam, v0.6 planning). If an unusually high share of your misses are tagged misclick (at least 25% of at least 8 tagged misses), the app says so. **It still counts as a loss on Lichess:** no take-backs, and the sync isn't changed.
- **FR-5.11** **What it feeds:**
  - **Stats:** reason breakdown overall, per theme, per habit tag and per mode (FR-9.7)
  - **Coach:** reason breakdown per weakness (FR-10.38), and drill-mode choice in the Suggested mix (FR-10.29)
  - **LLM coaching:** reason counts only, never your notes, unless you explicitly include them with the per-run **Include my notes** option (FR-10.60, v0.11)

## 8. Lichess integration

### 8.1 Authentication: OAuth 2.0 with PKCE
- **FR-6.1** Authorize at `GET https://lichess.org/oauth` with `response_type=code`, an arbitrary unique `client_id` (Lichess supports unregistered public clients), `redirect_uri`, `code_challenge_method=S256`, `code_challenge = BASE64URL(SHA256(code_verifier))`, `scope=puzzle:read puzzle:write study:read`, and a random `state`. *(Adam, v0.14 planning: `study:read` was added so the app can read private studies you own or belong to (FR-13.7). It's read-only. A token granted before v0.14 lacks it and keeps working for everything else; the first time a private study is refused, the app asks you to sign in again.)*
- **FR-6.1a** The authorization URL opens in the user's **default system browser**, never inside the app window, so their password manager and 2FA work (the native-app pattern in RFC 8252). The callback page tells them to return to the app, and the app brings its window to the front.
- **FR-6.2** `redirect_uri` is a **temporary loopback listener** at `http://127.0.0.1:<random port>/callback`. It accepts exactly one request, verifies `state`, and shuts down after the callback or a 5-minute timeout.
- **FR-6.3** Exchange the code at `POST https://lichess.org/api/token` with `grant_type=authorization_code`, `code`, `code_verifier`, `redirect_uri` and `client_id`.
- **FR-6.4** Tokens are long-lived (about one year) and **there are no refresh tokens**. On a 401, discard the token and show "Sign in again."
- **FR-6.5** Store the token **only** in Windows Credential Manager via `keyring`.
- **FR-6.6** **Sign out** calls `DELETE https://lichess.org/api/token` (revokes it on Lichess) and then deletes the local copy.
- **FR-6.7** Handle tokens of at least 512 characters (Lichess says token length can grow without notice).

### 8.2 Submitting solves
- **FR-6.8** Endpoint: `POST https://lichess.org/api/puzzle/batch/{angle}` (scope `puzzle:write`). Body: `{"solutions":[{"id":"…","win":true,"rated":true}, …]}`.
- **FR-6.9** **Fewer than 100 solutions per request** (the server rejects 100 or more).
- **FR-6.10** **Rate limit** (from Lichess server source, Oct 2026): 400 cost per hour per IP, and an authenticated solve costs 2, so about **200 solves per hour**. Send in batches and back off on HTTP 429.
- **FR-6.11** Use `rating_diff` and `glicko` from the response to update the local display of the Lichess puzzle rating. (Check the exact response field names against a live response in v0.3 and record them in the fake client.)
  - **FR-6.11a** **Your rating, always visible when signed in:** the main page header shows your current Lichess puzzle rating, with `?` while it's provisional. It's read from `GET /api/account` (`perfs.puzzle`) at sign-in, then updated from every sync response. It's never computed or estimated locally (never inflate ratings). When you're not signed in, it isn't shown.
  - **FR-6.11b** **Change per puzzle:** after a puzzle ends, the result panel shows its rating change, e.g. **+8** in green or **−12** in red, as soon as Lichess returns it.
    - Solves sync right away when online (FR-6.16), so this normally appears within a second or two.
    - Until Lichess replies it shows *Syncing…*. Offline it shows *Will sync later*, and the number fills in on the attempt once the queue drains.
    - When Lichess doesn't rate the solve, it says why instead of showing a number: *Unrated (Rated is off)*, *Already played: rating unaffected* (FR-4.6), or *Not rated by Lichess* for a 0 or missing change.
    - A tooltip explains that themed angles count for less than `mix` (§8.3), so a small change after a themed session is expected.
  - **FR-6.11c** **Session total:** the session bar shows the net rating change for this session (e.g. *+34 this session*), summed only from changes Lichess actually returned.
  - **FR-6.11d** **History:** each returned change and the new rating are saved with the attempt in `user.db` (new migration), and feed the rating trend (FR-9.4).
- **FR-6.12** Puzzles no longer on Lichess are silently skipped by the server. Mark them `sync_status = skipped`, not as an error.

### 8.3 Angle reporting (rating integrity)
Lichess weights rating changes by the reported `angle`, because a theme that's known in advance hints at the answer. `mix` gives full weight, and specific motifs give much less (e.g. a win on `fork` counts 20%). Report truthfully:
- **FR-6.13** `angle = mix` **only when** the theme filter is **All** *and* the move-count filter is **All**.
- **FR-6.14** Otherwise, `angle` is the **selected theme that this puzzle matched**. If several selected themes match, use the first one in a fixed priority order (motif themes before phase/goal themes).
  - *(Decided at v0.3 planning.)* The priority order is: the Motifs, Advanced, Mates, Mate patterns and Special moves groups first, then Phases, Goals and Origin, then the length themes. With ratios, the selected themes are every group's themes, in group order.
  - When the themes are **All** but the move-count filter isn't, the angle is the puzzle's **length theme** (`oneMove`, `short`, `long`, `veryLong` for 1, 2, 3 and 4+ moves), since that's what you knew in advance.
  - Excluded themes, openings, rating, side, quality and history filters don't change the angle.
  - *(v0.5 planning.)* Anything else that tells you the length in advance counts as a narrowed move count: the **depth ladder** order (FR-4.5) and Commit the line's **Show move count** switch (FR-4.2). **Spaced repetition** sessions ignore the filters and report `mix`.
- **FR-6.15** If the session **Rated** toggle is off, send `rated: false`.

### 8.4 Sync queue and history
- **FR-6.16** Every finished attempt in a syncing mode goes into the sync queue. It syncs right away when signed in, otherwise on the next successful sign-in. Sync never blocks solving.
  - *(Decided at v0.3 planning.)* Attempts recorded before v0.3 are **never** synced: they had no Rated flag or angle. They stay local and still count in Stats.
  - A solve made while signed in as one Lichess account only ever syncs to that account. A solve made while signed out syncs to the next account that signs in.
- **FR-6.16a** **Delivery is at-least-once.** If a batch times out after Lichess may have received it, the batch is resent. That's acceptable because Lichess only rates the first attempt at a puzzle; a resend records a replay. Never mark a batch synced without a success response.
- **FR-6.17** On sign-in, import puzzle history from `GET /api/puzzle/activity` (ndjson, scope `puzzle:read`). Import incrementally using `since` set to the last import time. This feeds the "exclude played on Lichess" filter and the "already played" badge.

---

## 9. Engine and LLM

### 9.1 Stockfish
- **FR-7.1** Native Windows x64 Stockfish, run by the backend over UCI using python-chess. Use the official **universal** build (`stockfish-windows-x86-64-universal.zip` from the `sf_19` GitHub release). It detects the CPU's instruction set by itself, so the app never picks between AVX2, BMI2 and other builds.
- **FR-7.2** Uses: refuting wrong moves, checking that "safe" candidates in Danger spotting really are safe, MultiPV top lines (default 3), and evals. **Evals are shown from your side** (the side you played in the puzzle): "+3.2 for you", "−1.4 for you", "You mate in 3", "You're mated in 2" (Adam, v0.4 planning).
- **FR-7.3** **No eval bar or engine lines are visible while a puzzle is in progress.** They appear after the puzzle ends: the line is complete, or Show answer was used. A puzzle you've already lost with a wrong move but are still playing through is still in progress. The backend enforces this: engine requests for a puzzle that isn't finished are refused.
- **FR-7.4** Settings: think time (default 1 s), threads (default CPU cores − 1), hash (default 256 MB).
- **FR-7.5** **Engine install.** The binary is gitignored, so an installer fetches it. One implementation, `services/engine_install.py`, is used by `scripts/fetch_stockfish.py`, `scripts/setup.py`, the in-app Install button and the v1.0 first-run wizard.
  - **Pinned, never "latest":** `engine_manifest.json` records the release tag, asset name, URL and SHA-256 (taken from the digest GitHub publishes for the asset). Assets are **keyed by OS and CPU architecture** (e.g. `windows-x86_64`) from the start. Through v1.0 only the Windows entry exists, and on any other platform the installer refuses with a clear message. v1.1 adds the macOS and Linux entries without changing the format. Upgrading Stockfish means editing the manifest, with an ARCHITECTURE.md §7 decision-log entry.
  - **Verify before extracting:** download over HTTPS through `adapters/http.py` to a temp file and check the SHA-256. On a mismatch, delete the file and stop with a clear error.
  - **Extract safely:** take only the expected `.exe`. Reject absolute paths and `..` entries.
  - **Install location:** `<data folder>\engines\<tag>\stockfish.exe`, outside the repo: `%LOCALAPPDATA%\WeakSquare\engines\…` for the app, `WeakSquare-dev\engines\…` for dev runs, and a temp folder in tests (NFR-2; Adam, v0.4 planning). `fetch_stockfish.py` and `setup.py` take `--dev` like `fetch_puzzle_db.py`. Install into a temp folder and rename it into place, so a failed install leaves nothing half-written.
  - **Smoke test:** after installing, `uci` must answer `uciok` and a short search from the start position must return a legal move. If not, remove the install and report the error.
  - **Idempotent:** if the installed engine already matches the manifest, do nothing. `--force` reinstalls.
  - **In the app:** when no engine is installed, engine features show *Stockfish isn't installed* with an **Install** button. It runs the same installer as a background job with progress.
  - **Advanced setting:** a path to the user's own Stockfish `.exe`, which overrides the managed install after passing the same smoke test.
- **FR-7.6** **Stockfish 19 exits on invalid input.** An invalid FEN, an illegal move in a move list, or another malformed command makes it print `info string CRITICAL ERROR …` and terminate. So:
  - validate every position and move list with python-chess before sending it;
  - if the engine process dies anyway, `EngineClient` logs the CRITICAL ERROR line, restarts the engine once, and fails that one request with a clear error. It never hangs.
- **FR-7.7** **After the puzzle (v0.4; Adam, v0.4 planning).** Once the puzzle ends, an engine panel shows:
  - the eval of the puzzle's start position, pinned at the top;
  - the eval and top 3 lines of whichever position is on the board, following you as you step through Show answer;
  - an **Analyze** button that turns the board into a free **analysis board**: you move pieces for either side (legal moves only), and after each move the engine re-analyzes and shows the eval, the top 3 lines and an arrow for its best move. Back, Forward, Reset (to the puzzle position) and Close. Nothing on the analysis board is ever scored.
  - **Show me** next to each engine line (in the panel and on the analysis board): the line goes on the board at its starting position, read-only, and you step through it yourself with Back / Forward (or ← / →); nothing moves until you do. **Done** returns to the position you were on. (Adam, during the v0.4 manual test.)

### 9.2 LLM "Explain"
- **FR-8.1** Optional. The button only appears when a provider and key are configured. Providers: **Anthropic** and **OpenAI**, behind one interface (`explain(context) -> ExplainResult`). **Explain requires Stockfish** (Adam, v0.7 planning): without it the button is disabled and the install banner shows. It's enabled once the puzzle is over (FR-7.3), in every mode including Danger spotting.
- **FR-8.2** **The LLM explains; it doesn't calculate.** It receives grounded context:
  - FEN, side to move, the full solution line (SAN and UCI)
  - Puzzle themes (revealed at this point)
  - The user's attempted moves, and Stockfish's refutation of any wrong move
  - Stockfish MultiPV lines and evals
  - Attack/defense facts computed by python-chess for the key squares and pieces (what attacks and defends the target, what each solution move changes)
  - In Danger spotting (Adam, v0.7 planning): the highlighted candidate, your call (Safe / Unsafe) and whether it was safe, so the explanation covers why that move was safe or was the blunder

  The prompt tells it to use only the moves provided and never invent moves or pieces.
- **FR-8.3** **Structured output** (JSON): a short summary, then one step per solution move containing an explanation and annotations (`arrow from→to`, `circle square`, color), then key ideas (e.g. "deflection," "overloaded defender").
- **FR-8.4** **Validation before display:** every move must be legal in sequence from the puzzle position, and every square must be valid. Drop invalid annotations and show a small "some annotations were discarded" note.
- **FR-8.5** **"Show me":** steps through the solution on the board, drawing each step's arrows and circles with chessground's shape API.
- **FR-8.6** **Cost control:** only runs on an explicit button press. Results are cached by `(puzzle_id, user move path, provider, model)`. A cached result costs nothing and is shown even when the budget is used up. All guardrails in §9.3 apply.
- **FR-8.7** LLM text is rendered as **escaped text / sanitized markdown**, never raw HTML (prevents injection into the web view).
- **FR-8.8** Timeouts and readable errors (bad key, quota, network).

### 9.3 LLM cost guardrails (apply to Explain and Coach)
- **FR-8.9** **Editable price table** (`llm_prices`), seeded with the prices in §16 (as of 2026-10-31), including long-context price tiers (e.g. Claude Haiku 5.5 charges more above a 100k-token prompt). Every cost figure in the app is computed from this table and the token counts the provider actually reports.
- **FR-8.10** **Usage log:** every request records feature, provider, model, input and output tokens, and cost.
- **FR-8.11** **Pre-run estimate:** manually started Coach runs always show estimated input/output tokens and cost, with a **Confirm** button. Automatic checkpoint runs follow FR-10.37. Explain shows its estimate inline (no confirm needed, since it's cents at most).
- **FR-8.12** **Per-run cap** (default **$0.50**). A request estimated above the cap is blocked unless the user raises the cap. The estimate checked against the cap is the worst case: estimated input plus the full `max_tokens` of output.
- **FR-8.13** **Monthly budget** (default **$5.00**). Warn at 80%. At 100%, Explain and Coach are disabled until the next month or until the budget is raised. Requests go through until the month's logged spend reaches the budget, so the last one can take you slightly over (Adam, v0.7 planning). The month is the local calendar month.
- **FR-8.14** **Hard `max_tokens`** on every request. Defaults: Explain 1,500; Game Review's Explain this move 1,500 and Explain my game 4,000 (v0.9 planning); Coach Summary 7,500; Coach Detailed 10,000 (raised from 2,500 and 5,000 for the AI plan, FR-10.66; Adam, v0.12 planning).
- **FR-8.15** **Reasoning / thinking effort** setting: **Low** (default), **Medium** or **High**. Hidden reasoning is billed as output and can multiply cost 2–5×. If enabled, the estimate accounts for it: Medium and High raise the request's `max_tokens` to 2× and 4× the defaults, so thinking can't cut the answer short, and the estimate and cap use the raised limit. There's no Off: current Claude models such as Opus 5.5 refuse to turn thinking off, so Low is the floor on both providers (v0.7 planning).
- **FR-8.16** Prompts stay compact by design. The app never sends raw PGNs to the LLM: no headers, player names, dates, URLs, clocks or comments, ever. Game text is allowed only in these cases, always anonymized as You / Opponent:
  - a **single game's SAN move list**, for the Game Review narrative (FR-11.19)
  - from v0.11, the Coach's **game digests** (FR-10.52), which carry SAN only for the opening and the key moments
  - from v0.11, with **Advanced analysis** switched on and confirmed (FR-10.56), the SAN move lists of the games in that run, up to its game cap

  - from v0.12, with **Include my journal** switched on and previewed (FR-10.71), your journal notes and reflections for the report's period, as written

  Otherwise the Coach sends aggregates and example positions (§10), and from v0.12 the current training plan's progress as aggregates (FR-10.66). (Rule changed by Adam, 2026-11-03, for whole-game coaching; journal added 2026-11-04.)

---

## 10. Coach: weakness analysis and recommendations

**Principle:** Stockfish and python-chess do the analysis locally, for free. The LLM gets only a compact summary and does the coaching. By default, LLM cost grows only slowly with the number of games: aggregates, plus one short digest per game from v0.11. Advanced analysis (FR-10.56) is the one opt-in exception. Without an LLM key, the Coach still produces a full weakness report and recommended presets.

### 10.1 Sources and settings
- **FR-10.1** A **Coach** button on the main page opens the Coach page.
- **FR-10.2** **Source picker:** *Puzzle history* / *Games* / *Both*, with a usage note on each:

  | Source | Engine time | LLM tokens | What it shows |
  |---|---|---|---|
  | Puzzle history | None | Lowest | Themes you fail when you know it's a puzzle |
  | Games | Minutes (local CPU) | Low (summary) | What actually costs you games, including tactics you **allowed** |
  | Both | Minutes | Low | Gaps between puzzles and games (e.g. solving forks in puzzles but walking into them in games) |

- **FR-10.3** **Accounts:** defaults to your **linked accounts** (§11.5), and you can override them per run. Lichess username and/or chess.com username. Accept either a plain username or a profile URL (`lichess.org/@/<user>`, `chess.com/member/<user>`).
  - **Another player** (Adam, v0.10 planning): you can enter any Lichess or chess.com username and run the Coach on that player's public games. Their games are stored once and tagged with that player (a game you played against them counts for both of you). They stay out of My Games unless you pick them with the **Player** filter. Their run saves a report labeled with their name, and **Load preset** works from it. It never changes your Suggested mix (§10.7), creates no My puzzles (§10.9) and never counts in your stats or report trends. Optional AI coaching works for their report with the same guardrails (§9.3); the prompt never contains a username.
- **FR-10.4** **Game filters:** count **25 / 50 / 100 / 200 (default 50)**; rated only (default on); time controls (default **rapid + classical**, since bullet and blitz mistakes come from the clock, not from tactics); color.
- **FR-10.5** **Detail level** for LLM coaching: **Summary** (~5k input tokens: aggregates plus 10–15 example positions) or **Detailed** (~20k input tokens: aggregates plus your 20 worst moments with context).

### 10.2 Fetching games
- **FR-10.6** **Lichess:** `GET /api/games/user/{username}` with `max`, `rated`, `perfType`, `evals=true`, `accuracy=true`, `opening=true`, as ndjson. Use the token when signed in (own-game export is faster). Documented rates: 20 games/s anonymous, 30 games/s authenticated, 60 games/s for your own games. Back off on 429.
- **FR-10.7** **chess.com:** Published-Data API. List the monthly archives, then fetch months newest-first **strictly one request at a time** (parallel requests get 429). Send a descriptive `User-Agent` with contact info (the project's repository URL, never a personal email), use ETag caching, and stop once N matching games are collected. Treat 410 as permanent.
- **FR-10.8** Cache games locally (`games`). Re-runs fetch only newer games.

### 10.3 Finding and tagging mistakes (local, free)
- **FR-10.9** The Coach reports on **the player's own moves** only. The analysis itself is the shared Game Review pipeline (§11.2, FR-10.26) at its think time (default 0.3 s per position), run locally even when Lichess already has evals (FR-11.3), so every game the Coach analyzed opens in Game Review without a re-analysis. *(Adam, v0.10 planning: replaces the earlier quick 0.15 s pass and the use of Lichess's evals.)*
- **FR-10.10** **Thresholds** (configurable): mistake = eval drop of at least 100 cp; blunder = at least 200 cp or a mate swing. The Coach skips the first 6 moves (opening book) and positions already decided (beyond ±500 cp) when it aggregates and when it makes puzzles (§10.9); Game Review's grading is unchanged (v0.10 planning).
- **FR-10.11** Each mistake is classified as:
  - **Missed:** you had a winning tactic. Its line comes from Stockfish's principal variation from your position.
  - **Allowed:** your move let the opponent win material or mate. Its line comes from Stockfish's principal variation after your move.
  - **Other:** a positional or untaggable mistake.
  - *(v0.10-B2:)* a move that walks into a forced mate counts as **Allowed** even when you had a winning tactic before it.
- **FR-10.12** Tag the Missed and Allowed lines with the **lichess-puzzler tagger**, so the themes match the puzzle DB exactly (`fork`, `capturingDefender`, `deflection`, and so on).
- **FR-10.13** Also record the phase (opening / middlegame / endgame), low clock (under 10% of time remaining, when clock data exists), and color.
- **FR-10.14** Show progress and estimated time remaining, and allow cancel. Analysis runs in the background without blocking solving.
- **FR-10.27** **Habit tags** (plain python-chess checks, applied alongside the lichess-puzzler themes). These are the most common mistake types at club level and are tracked as weaknesses of kind `habit`:
  - `hungPiece`: your move left a piece that the opponent can win outright
  - `missedFreeCapture`: the opponent left material hanging and you didn't take it
  - `ignoredThreat`: the opponent's last move created a check, capture or fork threat that your move didn't address
  - `movedDefender`: your moved piece was the only defender of something that then fell

  They map to puzzle drills: `hungPiece` and `ignoredThreat` → Danger spotting + `hangingPiece` / `fork` themes; `missedFreeCapture` → `hangingPiece`; `movedDefender` → `capturingDefender` / `deflection`.

### 10.4 Puzzle-history source
- **FR-10.15** Local `attempts` plus Lichess `GET /api/puzzle/dashboard/{days}` (scope `puzzle:read`). Per theme, the dashboard gives `nb`, `firstWins`, `replayWins`, `performance`, `puzzleRatingAvg`.

### 10.5 Report (free, no LLM)
- **FR-10.16** Weakest themes ranked separately for **Missed** and **Allowed**, with counts, rates and severity (average eval lost).
- **FR-10.17** Every example can be clicked to open its position on the board and step through what was missed or allowed (Stockfish line).
- **FR-10.18** When the source is Both, show a **puzzles vs. games gap table**.
- **FR-10.19** **Deterministic recommended preset:** theme weights proportional to frequency × severity; rating band centered on the user's Lichess puzzle rating (or estimated from first-try accuracy); a suggested mode (e.g. Danger spotting when Allowed dominates).
- **FR-10.20** Reports are saved (`coach_reports`) and can be compared over time (trend per theme).

### 10.6 LLM coaching (optional)
- **FR-10.21** **Input:** the aggregated report JSON (including **mistake-reason counts** per weakness, §7.3) plus example positions (FEN, played move, best line, themes, eval swing), per the detail level. **Anonymized:** no player names, game URLs or dates.
- **FR-10.22** **Output (JSON):** a short summary; the top 3–5 weaknesses, each with evidence counts, an explanation and drill advice; and 1–3 **recommended presets** using the filter schema from §5 (themes, rating range, move counts, mode, session size).
- **FR-10.23** **Validation:** theme keys must exist and ranges must be valid. Invalid fields are dropped, and the deterministic preset is the fallback.
- **FR-10.24** One-click **Load preset** into the filters, or **Save as preset**.
- **FR-10.25** The pre-run estimate, per-run cap, budget and `max_tokens` from §9.3 all apply.
- **FR-10.26** The Coach **reuses the Game Review analysis pipeline** (§11.2) and its stored `game_analysis`. Games that were already reviewed aren't re-analyzed, and any game the Coach analyzed opens in Game Review with one click.

### 10.7 Suggested default puzzle mix
- **FR-10.28** **First run:** after the first Coach run, the app builds a **Suggested** preset, and it becomes the default puzzle selection on the main page, labeled *"Suggested — from checkpoint #N, <date>"*. Until checkpoints arrive (v1.0) the label reads *"Suggested — from Coach run #N, <date>"*, and weaknesses are ranked by game rate × severity without statuses (v0.10 planning). Before any Coach run exists, the default is a broad mix (all themes, all lengths, rating band around your Lichess puzzle rating or 1500).
- **FR-10.29** **How the mix is built** (deterministic; the LLM may refine it, validated as in FR-10.23):
  - **Priority:** Regressed weaknesses first, then New/Training weaknesses ranked by game rate × severity, then Improving ones. Fixed weaknesses keep a small **maintenance share** (default 10%).
  - Each weakness contributes its related themes and drill mode (e.g. `ignoredThreat` → Danger spotting).
  - **Mistake reasons pick the drill mode** for each weakness (needs at least 5 tagged misses; otherwise the default mode is used):
    - mostly `didntLook` / `missedResource` (process) → **Danger spotting** and **Name the idea first**
    - mostly `miscalculated` → **Commit the line** and **Depth ladder**
    - mostly `unknownPattern` → that theme's puzzles at a **lower rating band** (−200, configurable), with **Explain** encouraged, before returning to the normal band
    - mostly `rushed` → flagged in "Why this mix" as a time-use issue rather than a pattern issue
  - **Length mix follows the evidence:** one-move and short puzzles dominate while habit-type leaks are high. **Long and very long combinations** (e.g. deflection → fork) get a share proportional to how often multi-move tactics appear in your Missed list, plus a small exploration share (default 10%). They're never excluded.
  - **Rating band:** centered on your puzzle rating, targeting about 75% first-try accuracy.
- **FR-10.30** **"Why this mix":** a short plain-English explanation next to the preset (e.g. *"You allowed 2.8 knight forks per 10 games, your #1 leak"*). Generated deterministically from the numbers, or by the LLM if AI coaching is enabled.
- **FR-10.31** **Never overwrite your choices:** if you've changed the filters by hand, a new suggestion appears as a banner (*"New suggested mix from checkpoint #N — Apply / Compare / Dismiss"*) instead of replacing your settings. **Compare** shows the old and new mix side by side.

### 10.8 Checkpoints and fix tracking
- **FR-10.32** **Trigger:** a checkpoint runs automatically after every **10 new eligible games** across your linked accounts (eligible = matches the Coach game filters, FR-10.4; default rated rapid + classical). There's also a **Run checkpoint now** button. Both numbers are configurable, so you can choose every 50 games, for example. *(Adam, 2026-11-06:)* You can also set a **time schedule** (every N days or a chosen weekday, default off). It runs only while the app is open, or the next time you open it if one came due while it was closed; the app installs no Windows scheduled task. A scheduled checkpoint with no new eligible games does nothing.
- **FR-10.33** **What a checkpoint does:** syncs and analyzes the new games in the background (§11.2 pipeline; local CPU only, free), recomputes every weakness metric, updates statuses, saves a `coach_checkpoints` row, and rebuilds the Suggested preset (§10.7). *(Adam, 2026-11-06:)* It also saves a **normal Coach report** on the rolling window (FR-10.34), linked by `report_id`, so you can read it and compare it under **Since last report** (FR-10.73) like any other. It never creates or replaces your training plan: that still takes your confirmation (FR-10.65).
- **FR-10.34** **Metrics** (per weakness, stored in `weakness_metrics`):
  - **Game rate:** occurrences per 10 games over a **rolling window of the last 30 eligible games** (configurable), compared to the **baseline**, which is the rate when the weakness was first identified (from the first Coach run's window, default 50 games). Baselines are frozen.
  - **Puzzle accuracy:** first-try accuracy on the weakness's related themes, from local attempts and the Lichess dashboard.
  - **Sample-size guard:** if the window has fewer than 5 occurrences *and* the baseline expected at least 5, the metric is still shown but marked *"not enough data yet"*, and no status change is made from it.
- **FR-10.35** **Statuses** (thresholds configurable):
  - **New:** just detected
  - **Training:** included in the current Suggested mix
  - **Improving:** window rate ≤ 75% of baseline
  - **Fixed:** window rate ≤ 50% of baseline at **2 consecutive checkpoints**, *and* puzzle first-try accuracy ≥ 75% over at least 20 attempts. **Puzzle accuracy alone never marks a weakness Fixed. The game rate decides.**
  - **Regressed:** a Fixed or Improving weakness whose window rate climbs back to ≥ 90% of baseline. It's reopened and given top priority in the next Suggested mix.

  New weaknesses can appear at any checkpoint, ranked the same way.
- **FR-10.36** **Overall game health per checkpoint** (context, not statuses): blunders, mistakes and inaccuracies **per 10 games** over the rolling window (FR-10.34); average centipawn loss overall and by phase; habit-tag rates; **mistake-reason mix** (share of process / calculation / knowledge / time, from §7.3); results; and rating on each platform.
- **FR-10.37** **AI at checkpoints:** the engine and statistics part always runs automatically and is free. An optional setting, **Auto AI checkpoint summary** (default **off**), adds an LLM commentary on what improved, what didn't and why the mix changed, using the Summary detail level. When it's on, it runs without a Confirm prompt **only if** the estimate is under the per-run cap and within the monthly budget (§9.3). Otherwise it waits behind a **Get AI take** button with the usual estimate and Confirm. A Summary costs about $0.001 (Claude Haiku 5.5) to $0.07 (GPT-5.5) per checkpoint.
- **FR-10.38** **Progress page:** one card per weakness, showing status, baseline vs. current game rate, a trend line across checkpoints (game rate and puzzle accuracy on the same chart), the **mistake-reason breakdown** for that weakness (e.g. *"Knight forks: 70% didn't look, 20% miscalculated"*), and click-through to the latest game examples. Plus a checkpoint history with the overall game-health trends, and an optional notification when a weakness changes status (*"Allowed forks: Improving → Fixed"*).
  - **How the trends are drawn** (Adam, 2026-11-03):
    - The game-health trends are **line charts**: blunders, mistakes and inaccuracies per 10 games on one chart, and average centipawn loss on its own.
    - Every rate on the page, per weakness and overall, is **per 10 games**, never per game.
    - Each line has **one point per checkpoint**, measured over the rolling window (the last 30 eligible games by default), not one point per game, so a single off game can't swing it.
    - **A falling line means you're improving.** Each chart says so in its title or axis label.
    - The weakness charts show the frozen baseline as a flat reference line.
    - Points marked *not enough data yet* (FR-10.34) are drawn hollow.

---

### 10.9 Puzzles from your games
- **FR-10.39** **Created by the analysis:** when the Coach analyzes your games (default your last 50, up to 200, FR-10.4; checkpoints add only new games), it turns qualifying mistakes into puzzles in `custom_puzzles` with `origin = coach`. It's part of the same background job and the same pipeline (FR-10.26). Games already analyzed aren't analyzed again. Re-runs never create duplicates (one puzzle per game and ply). Everything stays local and never syncs to Lichess.
  - *(Adam, v0.10 planning:)* puzzles are made after **any** analysis of your games (Coach runs, Analyze selected and Review), since it's one pipeline. Games analyzed before v0.10 get a one-time backfill from their stored analysis. Another player's games (FR-10.3) never make puzzles. A puzzle you saved by hand at the same ply is kept, and no Coach puzzle is added there.
- **FR-10.40** **Severity level (user setting):** which mistakes become puzzles. **Blunders only** / **Mistakes and blunders** (default) / **Inaccuracies, mistakes and blunders**. The levels use the shared thresholds (FR-11.9).
  - Changing the level rebuilds the set from the stored `game_analysis`, with no new engine pass over the games. Only new candidates get the quality check (FR-10.41).
  - Narrowing the level **archives** the puzzles outside it, never deletes them, so their attempt history is kept. Widening restores them.
  - The same three choices are also a filter when training the My puzzles source (FR-3.15).
- **FR-10.41** **Quality check:** a mistake becomes a puzzle only if it has a clear answer.
  - The rules are **ported from lichess-puzzler's generator** (`generator/generator.py`; Adam, v0.10 planning). The generator itself can't be reused, since it needs MongoDB, a tablebase server and 30-second searches. The best move must beat the second best by more than **0.7 in win chances** (Lichess's margin, configurable), or be the only move. Mate in one follows Lichess's mate-in-one rules.
  - The position must not already be decided (beyond ±500 cp before the move).
  - The line extends while the solver's move stays the only good one, the way Lichess builds multi-move puzzles: it's trimmed to end on the solver's move, and one-move advantage puzzles are dropped. Each extension position gets about 1 s on the background engine (configurable), not Lichess's 30 s.
  - Inaccuracies are kept only when they pass the same check, so the inaccuracy level may add few puzzles. The setting says so.
- **FR-10.42** **Missed and Allowed:**
  - **Missed** (you had a tactic and didn't play it): you solve from your own position, as the side you played.
  - **Allowed** (your move let your opponent in): you solve **as your opponent**, from the position after your mistake, finding the punishment. The board is oriented for the side to move, and the puzzle is labelled *"Find what your opponent could have played."*
  - Danger spotting (FR-4.4) stays Lichess-only for My puzzles (FR-3.15), so Allowed positions don't feed it yet (v0.10 planning).
- **FR-10.43** **Solving rules:** these come from engine analysis, not a verified single solution, so any move within 30 cp of the best (configurable, shared with Retry mode FR-11.15) counts. *(Built in v0.8 for puzzles saved from Game Review, FR-11.16; without Stockfish they fall back to the stored line.)* The interactive engine then continues the line from the move you played. Themes come from the lichess-puzzler tagger and stay hidden until the puzzle ends (FR-3.14). Any help before completion is a loss, as everywhere (§7.1).
- **FR-10.44** **Training them:**
  - **My puzzles** works as a source on its own or mixed with Lichess puzzles, in every mode that supports it, including **Spaced repetition** (FR-4.6).
  - The Suggested mix (§10.7) may include a share of your own-game puzzles (default 20%) linked to your top weaknesses, and "Why this mix" says so. *(v0.10: the share is the Coach's puzzles from your games, in the modes that take My puzzles: Standard and Commit the line.)*
  - Each puzzle links back to its game in Game Review. You can archive any puzzle you don't want.
- **FR-10.45** **Progress:** accuracy on your own-game puzzles appears on each weakness card (FR-10.38) next to Lichess-puzzle accuracy. It's a secondary signal only. A weakness's status is still decided by its game rate (§10.8), never by puzzle accuracy.

### 10.10 Importing puzzles from your own files (v0.8; Adam, 2026-11-02)
- **FR-10.46** **Import puzzles** from a file you already have: PGN (a `FEN` header and the solution as the moves; several games per file), EPD (`bm` or `pv` as the solution) or a simple CSV (FEN, solution in UCI or SAN, optional name). You give the set a label (e.g. the book's title). The app ships, links to and downloads **no** puzzle collections: copyrighted sets (for example published problem books) are yours to import only if you have them.
- **FR-10.47** **Stored with your other puzzles:** imported puzzles go into `custom_puzzles` with `origin = import` and the set label, and train through the **My puzzles** source (FR-3.15; renamed from "My games" at v0.8 planning), on their own or mixed with Lichess puzzles, in every mode that supports custom puzzles, Stats and Spaced repetition included. Filter by set label. They never sync to Lichess.
- **FR-10.48** **Validated on import:** python-chess checks every position and every solution move; bad entries are skipped and listed in an import report (entry number and reason). Re-importing the same file adds nothing twice (one puzzle per set and position + solution). The import runs as a job with progress and cancel.
- **FR-10.49** **Solving rules:** a book problem has one verified solution, so it's checked strictly like Lichess puzzles (§4.2), including "any mate counts" for mate-in-1, not with FR-10.43's 30 cp tolerance. If the file gives only the first move, the puzzle is that one move. The engine refutation and the post-puzzle panel (FR-7.2, 7.7) work as for any puzzle. Imported files usually carry no themes: they stay untagged until the lichess-puzzler tagger arrives (v0.10), which then tags them locally.
- **FR-10.50** **Privacy:** the file is read on your PC and never sent anywhere; the User Guide says so.

### 10.11 Whole-game coaching (v0.11; Adam, 2026-11-03)
The Coach looks at your games the way a tutor would: tactics, but also strategy, openings, endgames and how you use your time. The engine and python-chess measure the facts, and the LLM diagnoses from them. The areas below are **examples, not a closed list**.
- **FR-10.51** **Goal:** find your tactical, strategic and practical weaknesses across a set of games, including ones nobody listed in advance (e.g. *"you attack before castling"*, *"you trade into lost king-and-pawn endgames"*).
- **FR-10.52** **Game digest** (local, deterministic, built from the v0.8 `game_analysis` with no new engine pass where the data already exists). One short record per game:
  - your color, the result and the opening (ECO code and name)
  - the eval timeline, compressed to the key moments, each with the position (FEN), your move, the best move and the eval swing
  - king safety and development: the move each side castled (or didn't), your moves before castling, minor pieces developed by move 10, and early queen moves
  - the pawn structure when the opening ends (e.g. isolated queen pawn, doubled pawns), and trades made while ahead or behind
  - the endgame type, if the game reached one, from the material signature (king and pawn, rook, minor piece, queen, mixed)
  - time use: your clock at each key moment, summarised (not the clock on every move), and mistakes made under 10% of your time
  - the mistake reasons you tagged on this game's moves (§7.3)
  
  Digests are stored locally and reused across runs.
- **FR-10.53** **Whole-game measures** (free, shown in the report without an LLM, each with the sample-size guard of FR-10.34):
  - **Openings:** per opening, your score, average eval when the opening ends (around move 15), and errors in the first 15 moves
  - **Phases and conversion:** errors per phase, how often you win from +2 or better, and how often you save the game from −2 or worse
  - **Endgame types:** results and errors per endgame type
  - **Time use:** your blunder rate under 10% of your time vs. the rest of the game
  - **King safety and development:** how often you castle late or never, and how your results change when you do
  - *(Adam, v0.11 planning:)* each group (an opening family, an endgame type, …) needs at least **5 games**; below that it's shown as *not enough data yet* and never becomes a weakness. "From +2" means you **held** +2 or better for a full move (your move and the reply), so a one-ply blip doesn't count; the same for −2. The opening family is the opening name before its first `:`, or the ECO code when there's no name.
- **FR-10.54** **Open-ended diagnosis (LLM):**
  - **Input:** the digests of the games in the run, the whole-game measures, and the aggregates of FR-10.21.
  - **The prompt** asks the LLM to find weaknesses across tactics, strategy and practical play, *including but not limited to* openings, phases, endgame types, king safety and time use.
  - **Output (JSON):** for each weakness, a category (tactical / strategic / opening / endgame / time / other), a plain-language explanation, practical advice, a suggested topic (FR-10.59), and **evidence**, which is a list of game references and plies.
  - **Game references:** games are sent as local labels (G1, G2, …) that the app maps back to its own games on your PC. No game IDs or URLs are sent. *(v0.11 planning:)* plies are sent 1-based (half-move numbers) next to the SAN with its move number, and the example positions of FR-10.21 carry the same game label and ply, so there's one citation format. A cited ply must be a key moment of that game's digest, or, in an Advanced run, any ply of a game whose move list was sent.
  - *(v0.11 planning:)* this diagnosis replaces the v0.10 AI coaching prompt for reports that include games; a puzzle-history-only report keeps the v0.10 prompt. The answer has 3–8 weaknesses. One whose key matches a measured weakness that was sent is a tracked weakness; the rest are observations (FR-10.57).
- **FR-10.55** **Evidence rule** (validated like FR-10.23):
  - Every cited game and ply must exist in the data that was sent, and citations that don't are dropped. A weakness left with no valid evidence is dropped.
  - A weakness that cites fewer than 3 games is shown as **tentative**.
  - Every citation opens that game in Game Review at that ply.
  - The LLM's text is rendered escaped, and any move it names is validated before it's drawn (FR-8.4).
- **FR-10.56** **Advanced analysis** (a per-run option, **off by default**):
  - **What it adds:** the SAN move list of every game in the run, on top of the digests. Headers, names, dates, URLs, comments and clocks are still stripped.
  - **Game cap:** 30 by default, adjustable from 10 to 50.
  - **Before Confirm:** the usual estimate (FR-8.11) plus how it compares with a standard run, e.g. *"Advanced: about 4× the tokens of a standard run, ~$0.40 (8% of this month's budget), about 2 minutes. It takes longer and uses more API tokens."* The per-run cap and the monthly budget apply as usual.
  - **Never automatic:** checkpoint summaries (FR-10.37) never use it. *(v0.11 planning:)* Advanced and Include my notes (FR-10.60) are chosen for each AI run, are off every time you open the Coach, and are never saved as defaults, so no automatic path can turn them on. The time estimate uses a typical output speed, and Coach requests get a 180-second timeout.
  - **Every answer is kept** (Adam, v0.11 planning): each AI run of a report (standard, Advanced, with notes) is stored with its model and cost, a picker switches between them, and findings new in a run are labeled. The same options and model reuse the stored answer.
- **FR-10.57** **Findings become tracked weaknesses** when they can be measured:
  - A finding that matches a whole-game measure (FR-10.53) or a habit check becomes a weakness of kind `opening`, `endgame`, `phase`, `time` or `habit`, with statuses decided by its **game rate** (§10.8), as for every weakness.
  - A finding that can't be measured stays an **observation**: it's shown with the report and noted when it recurs across runs, but it has no status.
  - The new kinds and the digest storage are a new migration, designed at v0.11 planning.
  - *(v0.11 planning:)* how each kind counts an occurrence, ranked by game rate × severity like the v0.10 weaknesses until statuses arrive (v1.0):
    - `opening:<family>`: you leave the opening (move 15) at −1.00 or worse, or make a mistake or blunder in the first 15 moves
    - `endgame:<type>`: a mistake or blunder in the endgame phase of that endgame type
    - `phase:conversion`: a game where you held +2 or better and didn't win
    - `time:low_clock`: a mistake or blunder under 10% of your time, a weakness only when that error rate is above your rate the rest of the time
    - `habit:castledLate`: castling after move 12, or never, while the opponent's queen is on the board (king safety uses the habit kind)
- **FR-10.58** **Something to do for each weakness:**
  - tactical → a puzzle preset (FR-10.22)
  - opening → the games where it happened, and the opening trainer once it exists (v0.13)
  - endgame or conversion → the positions from your games where it happened, opened on the analysis board
  - time → flagged in "Why this mix" (FR-10.30)
- **FR-10.59** **Lesson pointers:**
  - **First, the in-app drill:** e.g. *"Learn zugzwang"* loads zugzwang puzzles in Standard mode 200 below your rating band, with Explain encouraged (there's no setting that turns Explain on; v0.11 planning).
  - **Then outside resources:**
    - a **curated map** from topics (themes, endgame types, opening families) to stable free pages: **Lichess Practice and Lichess Learn only** (Adam, v0.11 planning); everything else goes through the search links
    - **search links** for YouTube, chess.com and any site you choose (Settings: which sites are shown, and an optional custom search URL with a `{q}` placeholder)
  - **The LLM only picks a topic** from the app's list. It never writes a URL, and any link the app didn't build itself is dropped. *(v0.11 planning:)* the screen sends only the topic and the target (a curated link or a search site); the backend builds the URL, checks it against the curated host allowlist or the search templates, and opens it.
  - **Links open in your default browser.** The app never fetches those sites, and the search terms go to the site you click (the User Guide's privacy section says so).
- **FR-10.60** **Include my notes** (a per-run option, **off by default**): adds your mistake-reason notes (§7.3) for the games and puzzles in the run to the prompt. Before Confirm, you see exactly which notes will be sent. *(v0.11 planning:)* that's the latest reason and note for your moves in the run's games, plus your puzzle and Retry notes in the report's period. Web addresses are removed from notes before the preview and before sending (FR-8.16).

### 10.12 Training plan and training journal (v0.12; Adam, 2026-11-04)
**Goal:** turn the Coach's diagnosis into a routine you can follow, and keep a record of what you did and what you learned, so the Coach (and you) can see what's working. Requested by Adam during the v0.10 manual test. The plan and the journal live in the Coach, v0.12 also makes every option explain itself (FR-10.72), and every report compares itself with your earlier ones (FR-10.73) (Adam, 2026-11-05, during the v0.11 manual test).

**Training plan**
- **FR-10.61** **Built from your weaknesses:** a plan of **1–4 weeks** (default 2) from your latest Coach report (with v0.11's whole-game weaknesses when present). You pick your **training weekdays** (default Monday to Friday; days per week is the number you pick, 1–7) and **minutes per day** (default 20, 10–120). The plan starts today if today is a day you picked, otherwise on the next one (Adam, v0.12 planning). The top weaknesses get the most time; a weakness reported as fixed later (v1.0) keeps a small maintenance share.
- **FR-10.62** **Daily sessions:** each training day has 2–4 **tasks** that fit the minutes you set. Task types (a closed list, so every task is something the app can open):
  - a **puzzle session**: filters (themes, rating, source, own-game share), a mode and a count, e.g. *20 Danger-spotting puzzles: forks*
  - **puzzles from your games** at a severity level (§10.9)
  - **Retry your mistakes** in a named game (FR-11.15)
  - **review a game** in Game Review, with Show best moves off (FR-11.35)
  - a **lesson pointer** (FR-10.59, v0.11)
  - a **journal reflection** (FR-10.69)
- **FR-10.63** **Tasks open where they happen:** **Start** opens the task's screen ready to go. A puzzle task starts a session with the task's filters for that session only; it never changes your saved presets or your Mixer filters.
- **FR-10.64** **A daily checklist that ticks itself off:** each day's tasks are shown as **checkboxes**. A task ticks itself when the app sees it done: a puzzle task when its session reaches the count; Retry when every mistake was tried; a review when you have visited every key moment and the game's final move (Adam, v0.12 planning); a lesson when you open one of its links or start its drill (v0.12 planning); a reflection when the entry is saved from the task, even if you closed its question first (Adam, 2026-11-06). A puzzle task counts only sessions started from that task, added up if you stop and resume. You can also tick or untick any box by hand, and skip or swap a task (Adam, 2026-11-05: auto and manual). **A hand choice always wins:** a hand tick counts as done whatever the app saw, and a box you unticked stays unticked until you tick it again. A missed day's tasks are either carried over or dropped (setting, default carried over, at most one day's worth). Once a task has a copy, the copy is the task: it keeps the progress and an untick, what you finish from the original counts for it, and the original's row has no box of its own (QA v0.12-B32 to B34). Swap never offers what's already on that day, a game or lesson the plan already has, or a game you've already finished (QA v0.12-B31, B35).
- **FR-10.65** **In the Coach, plus a Today card** (Adam, 2026-11-05): the Coach has three tabs, **Report**, **Plan** and **Journal**; there are no separate Plan or Journal pages. The **Plan** tab shows each week and its days as checklists, with done / skipped / left and minutes spent, and today's day opened. The main page shows a small **Today's plan** card with the same checkboxes and Start on each task; ticking in either place updates both. A new plan replaces the current one only when you confirm; old plans stay in the history with their completion.
- **FR-10.66** **AI coaching includes the plan** (Adam, 2026-11-04):
  - With AI coaching (§10.6, §10.11), the LLM's answer includes a **proposed plan** in a strict schema: weeks → days → tasks of the FR-10.62 types only, with theme keys, modes, counts, game references and lesson topics validated like presets (FR-10.23). Invalid tasks are dropped and the **deterministic plan** fills the gaps, so there is always a complete plan. **Use this plan** (with a confirm) makes it current. The AI plans the shape in your saved plan settings; a saved answer keeps the shape it was made with, so changing the settings never re-bills you. A stored answer without a plan is not reused for your own reports, so asking again makes a new run (v0.12 planning). Another player's report asks for no plan.
  - The next AI coaching run is told how the current plan went, as **aggregates only**: tasks done and skipped per type and weakness, minutes, and puzzle accuracy per task theme. No journal text unless FR-10.71's option is on.
  - Without an AI key the plan is still built deterministically; all §9.3 guardrails apply.

**Training journal**
- **FR-10.67** **Your notes:** dated entries you write (up to 5,000 characters), with optional tags: a weakness, a game (and ply), a plan day. You can edit and delete them.
- **FR-10.68** **Automatic log:** for each day, the app adds a read-only summary computed from what's stored. It adds only two small records: when a game was analyzed (`games.analyzed_at`) and which moves you visited in Game Review (`review_passes`), so games analyzed before v0.12 aren't counted as analyzed on any day (v0.12 planning). It shows: puzzles by mode and source with first-try accuracy and the themes you missed most, games played, synced, analyzed and reviewed, Retry results, plan tasks done, Coach runs and their top weakness. A game counts as played on the day you played it, whenever it was synced, so a sync can fill in an earlier day (Adam, 2026-11-06).
- **FR-10.69** **Game reflections:** in Game Review, **Add a note** on a game or on one of its moves saves a journal entry linked to that game and ply. The game shows its notes (with a marker on the move), and the journal links back to the position.
- **FR-10.70** **Journal tab** (in the Coach, FR-10.65): one timeline of your notes, reflections and the daily log, newest first, with filters (weakness, game, type, date range) and text search. Entries stay on the PC unless you turn on FR-10.71's option for a run (privacy section updated). Mistake-reason notes (FR-10.60) aren't part of the timeline.
- **FR-10.71** **Feeds the AI coach (opt-in):** a per-run **Include my journal** option (off by default) adds your notes and reflections from the report's period to the AI coaching prompt, with a preview of exactly what is sent before Confirm. It extends v0.11's **Include my notes** (FR-10.60). Game references go as the report's own game labels, never as platform ids or URLs; names you typed yourself are sent only if you include them, and the preview warns that notes are sent as written. **Scope** (v0.12 planning): entries tagged to one of the report's games, plus entries dated from the report's first game onward, because reflections are written after the games; the newest 30, each cut to 1,000 characters with web addresses removed. The preview shows the cut text. A game outside the report goes with no game reference. It's a separate checkbox from Include my notes, off for every run and never saved, with one preview listing both. A saved answer is reused only if the journal text is unchanged. Your own reports only.

**Easier to use** (Adam, 2026-11-05)
- **FR-10.72** **Every option explains itself:** app-wide, every setting and every choice the user makes (switches, number boxes, selects, segmented controls, checkboxes such as Advanced analysis) has a **tooltip** (an ⓘ next to its label, also on keyboard focus) that says in plain words what it does and, for a choice, what each option means and costs, e.g. the Coach's **Summary** vs **Detailed** (how much is sent and written, and the cost difference). Tooltip text is plain text, kept in one place in the front end (`web/src/text/tooltips.ts`), and is written for the user, matching the User Guide. Later versions add a tooltip for every option they add. Free-text data entry has none (a game you paste, a search box, your journal text, an API key, a name you type), nor do a row's select box and one theme in a picker's list; each such control says why in the code, and the Playwright walk checks every other control (v0.12 planning).

**Since last report** (Adam, 2026-11-05)
- **FR-10.73** **Each report compares itself with your earlier ones:** a **Since last report** section in every report on games, and the AI coaching sees the same numbers.
  - **Compared with:** the previous report of the same subject (you, or that other player, whose reports never mix with yours, §10.1), plus the trend across up to the **5** latest reports. Reports on your puzzle history compare only with other puzzle-history reports.
  - **What it shows:** for each weakness in either report, its rate per 10 games then and now and the change, with **New** (not in the earlier report) and **Gone** (no longer in the top list) marked; overall game health (blunders, mistakes and inaccuracies per 10 games); the whole-game measures that both reports have (score per opening family, conversion and save rates, low-clock mistakes, late castling); puzzle first-try accuracy for each weakness's themes (your reports only: your attempts up to the older report against those between the two, each side needing at least 10 attempts); and the days and new games between the two reports.
  - **Guards:** a change is called **better** or **worse** only when both reports have at least **5 games** in that group (FR-10.53's guard) and at least 5 of the newer report's games weren't in the older one; otherwise it says *not enough new games yet*. When the two reports share games, it says how many. Reports made with different analysis settings (think time, thresholds) are flagged, because their rates aren't directly comparable. Reports from before v0.12 didn't record their settings, so they show *settings unknown*.
  - **To the AI:** with AI coaching on, the prompt gets this section as **aggregates only**: weakness keys and their rates per report, labeled *this report*, *1 report ago* and so on, with days between them. It gets no games, positions or text from earlier reports, and the AI is asked to say what improved, what got worse and whether earlier advice seems to be working. A statement about a trend goes in its own `trend` field, `{key, change, comment}`, because a weakness that's gone has no game to cite: the key must be one that was sent, and `change` (improved / worse / same) must match the app's own guarded result, otherwise the statement is dropped (v0.12 planning; the same check as FR-10.55, and it never inflates progress).
  - It describes the change; it doesn't set a weakness's status. Statuses, baselines and the Progress page are v1.0 (§10.8), which reuses these comparisons.

## 11. Game Review: import a game, analyze it, explain better moves

**Principle:** Stockfish grades every move locally, for free. The AI explains key moments using the same grounded-context and validation rules as Explain (§9.2). Without an LLM key, Game Review still works as a full engine review.

### 11.1 Importing
- **FR-11.1** An **Import game** button on the main page opens the Game Review page.
- **FR-11.2** **Inputs:**
  - paste a PGN
  - open a `.pgn` file (if it holds several games, pick one from a list)
  - a **Lichess** game URL
  - a **chess.com** game URL
  - pick from your **Game library**, which pulls games automatically from your linked accounts (§11.5). This is the main way in. The options above are for one-off games.
- **FR-11.3** **Lichess URL** (`lichess.org/<gameId>`, optionally followed by `/white`, `/black` or `#<ply>`): take the 8-character game ID and call `GET /game/export/{gameId}` with `evals=true`, `clocks=true`, `accuracy=true`, `opening=true`, `division=true`. Every game is analyzed locally (§11.2), even when Lichess already analyzed it, so every review is graded the same way. Lichess's per-move evals don't include the top lines or refutations the review needs. Lichess's accuracy % is shown, and the game gets an *Analyzed on Lichess* badge. *(Adam, v0.8 planning; this replaces "reuse Lichess's evals".)*
- **FR-11.4** **chess.com URL** (`chess.com/game/live/<id>` or `/game/daily/<id>`): the public API has no single-game endpoint. Search the user's recent monthly archives for the matching game URL, using the username from settings (or ask once), with serial requests only (FR-10.7). If it isn't found, ask the user to paste the PGN (chess.com: Share → PGN).
- **FR-11.5** **Your color:** detected by matching the PGN player tags against your configured usernames. Otherwise the app asks which side you played. You can also choose to review both sides.
- **FR-11.6** Validate with python-chess and reject malformed or illegal games with a clear error. Version 1 supports standard chess only (no Chess960 or other variants).
- **FR-11.7** Imported games are stored in `games` with `source` set to paste / file / lichess / chesscom. Re-importing the same game (same source ID or identical moves) reuses the existing analysis.

### 11.2 Engine analysis (local, free)
- **FR-11.8** Evaluate **every position** in the game (default **0.3 s per position**, configurable), in the background, with a progress bar and the option to cancel. The user's moves are highlighted, and the opponent's moves are graded too, so you can see blunders you failed to punish.
- **FR-11.9** **Recorded for each move:** eval before and after (cp or mate, from the mover's view), best move, top 3 engine lines, centipawn loss, and a classification of Best / Good / Inaccuracy / Mistake / Blunder. Thresholds are configurable and shared with the Coach: inaccuracy ≥ 50 cp, mistake ≥ 100 cp, blunder ≥ 200 cp or a mate swing. Positions already decided (beyond ±500 cp) aren't penalized.
- **FR-11.10** **Tagging:** every user mistake or blunder is classified as Missed or Allowed and tagged with the lichess-puzzler tagger (same as FR-10.11 and FR-10.12). *(Adam, v0.8 planning: v0.8 classifies Missed / Allowed / Other with a simple rule but adds no theme tags. The tagger arrives in v0.10, which then tags stored mistakes and puzzles.)*
- **FR-11.11** **Summary per side:** counts of inaccuracies, mistakes and blunders; average centipawn loss; Lichess's accuracy % when the export provides it; a breakdown by phase (from Lichess's `division` data, or estimated by move number); and mistakes made with a low clock (when clock data exists).

### 11.3 Review screen
- **FR-11.12** Board plus move list with annotation symbols (?!, ?, ??), all clickable. An **eval graph** for the whole game; click to jump to a move.
- **FR-11.13** **Key moments:** the biggest eval swings on the user's side (default top 5). Each shows "Played X, better was Y" and the eval swing, plus the mistake-reason chips (§7.3).
- **FR-11.14** **At any move:** best-move arrow and the engine's top lines. At a mistake, also the **refutation** of the move you played, which you can step through.
- **FR-11.15** **Retry mode** ("learn from your mistakes"): from the position before each of your mistakes, you try to find a better move before the answer is shown. Any move within 30 cp of the best move (configurable) counts as found. Results feed local stats. *(Adam, 2026-11-04, during the v0.11 build:)* once you've tried, **Explain this move** (FR-11.17) is offered for that mistake, with its Show me drawn on the Retry board. It's never offered before your attempt, so it can't help you find the move.
- **FR-11.34** **Analyze from here** (Adam, 2026-11-04, after v0.9; built in **v0.10**). From any position in Game Review, open a free analysis board where you can play any moves, both sides, away from the game. It reuses the analysis board (FR-7.7) with the **interactive** engine (never the background one, ARCHITECTURE §3 decision 12): eval and top lines for the position on the board, with Back / Forward and **Back to the game**. Nothing you play there changes the game, its analysis or any stats. It respects **Show best moves** (FR-11.35): with it off, the engine's eval and lines stay hidden until you turn it on.
- **FR-11.35** **Show best moves** (Adam, 2026-11-04, after v0.9; built in **v0.10**). A toggle on the Review screen, **off by default**, saved in `user.db` through the bridge (never browser storage) and kept across games and restarts. While it's off, Game Review hides everything that gives the better move away, so you can try to find it first: the best-move arrow, the engine lines (FR-11.14), "Better was X" at a move, "better was Y" on the key moments (FR-11.13), and the AI's better lines and arrows (FR-11.18). The eval graph, the eval number, the ?! ? ?? symbols, the refutation of the move you played ("why it fails") and the AI's text stay visible. Turning it on shows them at once. Retry mode (FR-11.15) is unchanged.
- **FR-11.16** **Save as puzzle:** any key moment can be saved to `custom_puzzles` (position, best line, tags) and drilled through the "My puzzles" source (FR-3.15), including Spaced repetition. It stores the position, the best line and (from v0.10) tags; it is solved with the 30 cp tolerance (FR-10.43). These puzzles never sync to Lichess.
- **FR-11.36** **Review in three parts** (Adam, 2026-11-07; built in **v0.14**). A review that lists only faults reads as criticism even after a strong game, so the Review screen has three parts, all computed from the stored engine analysis and all working with no AI key:
  1. **Summary:** the result, your accuracy and average centipawn loss, the turning point (the largest eval swing), and how each phase went.
  2. **What to improve:** the key moments (FR-11.13), unchanged.
  3. **What you did well:** only things the engine data backs up, each linked to its move:
     - **only move found:** you played the best move, and the engine's second choice was at least 150 cp worse
     - **mistake punished:** after an opponent's mistake or blunder, your reply stayed within the inaccuracy threshold
     - **hard defence:** from an eval of −150 or worse you played a Best or Good move
     - **conversion:** you reached +200 or better and won without dropping below +100
     - **clean phase:** at least 8 of your moves in a phase with no mistakes or blunders
     - Positions already decided (beyond ±500 cp) don't count. With nothing that qualifies, it says so plainly and invents no praise.
  - **Explain my game** (FR-11.18) receives this list as grounded context and adds a short "what you did well" part. It may explain only the listed strengths, never add its own. Its cache key includes a new prompt version, so earlier narratives aren't reused.
  - **The AI fills the same three parts** (Adam, 2026-11-08, v0.15-rc1 manual test; built in **v0.15**). Explain my game doesn't add a block of its own: there is one Summary, one What to improve and one What you did well.
    1. **Summary:** the AI's general summary replaces the computed sentences (which return without it). It reads as a summary, not a list of moves: what you struggled with and what went right, pointing at a move number at most. The turning point sits under it.
    2. **What to improve:** opens with the AI's own 2–3-sentence summary of the patterns behind your mistakes, then the key moments with their notes (each ending with what to look for next time). Each key moment is tagged with up to 3 **training ideas**: puzzle theme keys from the preset's allowed list (FR-10.23), validated the same way, shown by name. The recommended preset (Practise / Train these) closes this part.
    3. **What you did well:** opens with the AI's own 1–3-sentence summary, then each computed strength with the AI's words on it underneath. With no computed strength, the AI's summary is dropped too, so it still never invents praise.
    - The opening summary, recurring themes and takeaways are gone (the general summary and the part summaries cover them). The cache key's prompt version changes again, so a narrative saved before v0.15 isn't reused.
  - The rules respect **Show best moves** (FR-11.35): an only-move item names your move, never the engine's alternative.

### 11.4 AI explanations (optional)
- **FR-11.17** **Explain this move:** on demand, for a key moment or any of **your** moves (every move when you review both sides; Adam, v0.9 planning). Its grounded context: position, played move, best move and its line, refutation of the played move, eval swing, top engine lines, attack/defense facts, tags. Output, validation and board annotations work exactly like FR-8.3 to FR-8.5.
- **FR-11.18** **Explain my game:** one batched request covering the top N key moments (default 5, max 10), plus a short narrative (opening summary, turning point, recurring themes, 2–3 takeaways; *from v0.15*, a general summary, the turning point, a summary for What to improve and one for What you did well, and training ideas on each key moment: see FR-11.36) and an optional recommended puzzle preset, validated as in FR-10.23. In v0.9 the preset is minimal (Adam, v0.9 planning): up to 3 theme keys and an optional rating range; unknown themes and invalid ranges are dropped. **Train these** applies it to the Mixer's filters only when you click it and confirm, and never changes a saved preset.
- **FR-11.19** The context may include this game's **SAN move list only** (no headers, clocks or comments) for the narrative. Players are anonymized as "You" and "Opponent": no names, ratings, URLs or dates.
- **FR-11.20** Results are cached per (game, ply, provider, model) for single moves, and per (game, N, provider, model) for the narrative. The key also includes the analysis settings (think time and engine) and the grading thresholds, so a re-analysis at other settings, or new thresholds, never shows an explanation grounded on the old evals or grades (v0.9 planning; thresholds added for v0.9-B2).
- **FR-11.21** All §9.3 guardrails apply. Estimated cost of Explain my game (~10k input / 3k output tokens): about $0.003 on Claude Haiku 5.5, $0.05 on Sonnet 5.5, $0.07 on GPT-5.4, $0.14 on GPT-5.5. Single-move explanations cost the same as in §9.2.
- **FR-11.22** Game Review never syncs anything to Lichess or affects any rating. Retry-mode results are local only.

### 11.5 Linked accounts and game library
- **FR-11.23** **Lichess:** the account you signed in with (§8.1) is linked automatically. Its games are exported with your token, which is the fastest rate (60 games/s for your own games).
- **FR-11.24** **chess.com:** linked by **username**. The **Verify** button calls `GET https://api.chess.com/pub/player/{username}` and shows the profile; a 404 means the user doesn't exist. chess.com's public API needs no login and serves only public data, so linking by username grants nothing and proves nothing. It just tells the app whose public games to pull. *(chess.com's OAuth, "Sign in with Chess.com," is only available by application and approval, so it's out of scope for version 1. It's a possible later upgrade if you want verified identity.)* The username is stored in `settings`, since it isn't a secret.
- **FR-11.25** **Game library page ("My Games"):** one list combining both accounts, newest first. Columns: date, platform, your color, opponent and rating, your rating, result, time control, opening/ECO, platform accuracy (when provided), and status (**Not analyzed / Analyzed / AI-reviewed**, plus a badge when Lichess already has computer analysis).
- **FR-11.26** **Library filters:** platform, time class, rated, result, color, opponent search, opening, date range, status.
- **FR-11.27** **Sync:** runs on app open (default on, can be turned off) and from a **Refresh** button. It fetches new game **metadata and PGNs only**, never analysis, and doesn't block the UI.
  - **Lichess:** `GET /api/games/user/{username}` with `since` set to the last sync time, plus `pgnInJson`, `clocks`, `evals`, `accuracy`, `opening`.
  - **chess.com:** fetch the archives list, then only months newer than or equal to the last synced month, strictly one request at a time, using ETags (a 304 means unchanged).
  - **First sync:** the last 90 days or 200 games per account, whichever is smaller (configurable), to avoid flooding either API.
- **FR-11.28** **chess.com data handling:** monthly archive games contain `white`/`black` (`username`, `rating`, `result`), `url`, `pgn`, `fen`, `end_time`, `time_control`, `rules`, `eco`, and `accuracies` **only if chess.com already calculated them**. Treat every other field as optional. Derive the time class from `time_control` when it's missing. Skip games whose `rules` isn't `chess` (variants aren't supported in version 1).
- **FR-11.29** **Actions on one game:**
  - **Review:** runs the §11.2 analysis, or reuses it, then opens the review screen with the AI buttons available.
  - **Review + Explain my game:** runs the analysis, shows the cost estimate (§9.3), and after you confirm, runs FR-11.18 automatically.
  - **Open on Lichess / chess.com:** opens the game in your default browser.
- **FR-11.30** **Multi-select actions:** **Analyze selected** (engine only, queued, no LLM cost) and **Send to Coach** (runs §10 on exactly those games).
- **FR-11.31** **Analysis queue:** one Stockfish job at a time (each job already uses several threads), with visible progress and cancel. Results are saved, so a game is never analyzed twice at the same settings.
- **FR-11.32** **Documented APIs only:** use only the Lichess API and chess.com's Published-Data API. Never use chess.com's internal website endpoints (e.g. the "callback" game URLs). They aren't meant for general use and can get your IP banned.
- **FR-11.33** **Privacy:** games and analysis stay local. Nothing leaves the PC except the API fetches and whatever you explicitly send to the LLM (FR-11.19, anonymized).

---

## 12. Stats

- **FR-9.1** Accuracy per theme, per length, per mode, and per rating band.
- **FR-9.2** **First move right, line wrong** rate. This is the key metric for whether calculation is improving.
- **FR-9.3** Time to solve, help usage, Commit-mode calculation accuracy, Name-the-idea tag accuracy, Danger-spotting accuracy.
- **FR-9.4** Lichess puzzle rating trend, from sync responses (stored per FR-6.11d): a line chart of your rating over time on the Stats page, with the change per session.
- **FR-9.5** Weakest themes list, with a one-click "drill these" preset.
- **FR-9.6** Weakness tracking and checkpoint history are on the Coach's Progress page (FR-10.38). Stats links to it.
- **FR-9.7** **Mistake-reason breakdown** (§7.3): overall, and filterable by theme, habit tag, mode and source (puzzles vs. games), with a trend over time. Puzzle-vs-game comparison is included (e.g. forks you miss in games because you didn't look but solve fine in puzzles). Misclicks are shown separately.

---

## 13. Security requirements

- **SR-1** Secrets (Lichess token, LLM key) live **only** in Windows Credential Manager via `keyring`. They are never written to SQLite, config files or logs, and **never sent to the front-end JavaScript**.
- **SR-2** The pywebview JS bridge exposes a **minimal API**, and the backend validates every argument coming from JS.
- **SR-3** The web view loads **only local assets** (no remote scripts or CDNs), with a strict Content Security Policy.
- **SR-4** OAuth: PKCE with S256, random `state` checked on callback, loopback listener bound to `127.0.0.1` only, single use, with a timeout.
- **SR-5** Log redaction for `Authorization` headers and API keys.
- **SR-6** Verify downloaded files (puzzle DB, Stockfish) over HTTPS from official sources, and check hashes where published. Stockfish's SHA-256 is pinned in `engine_manifest.json`, and the install refuses on a mismatch (FR-7.5).

### Secret handling (runtime)
- **SR-7** **One secret module.** Only `secret_store.py` imports `keyring`. Everything else calls its functions. Secrets are held in memory only as long as a request needs them. They are never returned to JS, never printed, and never included in exception messages (wrap HTTP errors so headers are stripped).
- **SR-8** No secrets in process arguments or environment variables. Stockfish and any helper processes never receive credentials.
- **SR-9** The OAuth callback URL and authorization `code` are never logged. The loopback listener replies with a plain "Signed in. You can close this tab." page.
- **SR-10** Logging: INFO level by default, with `httpx`/`httpcore` debug logging off. As defense in depth, a logging filter redacts token patterns (`li?_…`, `sk-…`, `Bearer …`). Logs stay local.
- **SR-11** The LLM context builder uses an **allowlist** of fields (positions, moves, themes, stats). It never includes settings, headers, error text or usernames.

### Secret handling (development and tests)
- **SR-12** **Fixtures are scrubbed when recorded:** `Authorization` headers, cookies, `code`, `code_verifier` and `access_token` fields. A pytest test fails if any file under `tests/fixtures/` matches a secret pattern. Tests mock `secret_store`, never `keyring` directly. Placeholders look obviously fake (`lip_FAKE…`, `sk-ant-FAKE…`).
- **SR-13** **Live tests are opt-in** (`@pytest.mark.live`, skipped by default). They use Adam's own Lichess account (Lichess's Terms of Service don't allow a second account just for testing) through a **separate personal access token** with only the `puzzle:read` and `puzzle:write` scopes, created at lichess.org/account/oauth/token and revocable on its own. That token is stored under a separate keyring service name (`weaksquare-test`) and read through `secret_store`. Live tests always send `rated: false` and push at most 3 solves per run. The app's own sign-in token is never used in tests.
- **SR-12a** **Fixtures are anonymized** as well as scrubbed: recorded games and API responses replace real usernames (yours and opponents'), game IDs and URLs with obvious placeholders (`player_a`, `opponent_b`, `GAMEID01`). The public repo must not identify anyone.
- **SR-14** **Repo guardrails** (shipped in the starter files):
  - **gitleaks** pre-commit scan, using the built-in rules plus custom Lichess and Bearer rules in `.gitleaks.toml`
  - a **pre-commit check** that `keyring` is used only in `secret_store.py`
  - a **Claude Code PreToolUse hook** (`.claude/hooks/guard_secrets.py`) that blocks shell commands reading stored credentials (`keyring.get_password`, `cmdkey`, etc.) and any command or file write containing a secret-looking value
  - **deny rules** so the agent can't edit `.claude/`, `.gitleaks.toml` or `.pre-commit-config.yaml`

  The purpose: credentials must never enter the Claude Code transcript, which is sent to the model provider, and never enter git.
- **SR-14a** **GitHub's own scanning on the public repo:** secret scanning and push protection (free on public repositories) as a server-side backstop to the local gitleaks hook, plus Dependabot alerts for vulnerable dependencies. Enabled when the repo is published.
- **SR-14b** **Dependencies are locked and approved.** Python dependencies are locked in `uv.lock`, front-end dependencies in `package-lock.json` (installed with `npm ci`), and CI installs only from the lockfiles. A new dependency must appear in the approved version plan with its purpose, and its exact name is checked on PyPI or npm first (AI-suggested package names can be typosquats or not exist).
- **SR-15** **Threat model note:** Windows Credential Manager protects secrets at rest, per Windows user. Any code running as that user can read them. This is accepted for a personal app. Sign-out revokes the Lichess token on the server (FR-6.6), and LLM keys can be rotated in the provider's console.
- **SR-16** **Debugging port only in tests:** the WebView2 remote-debugging (CDP) port is enabled **only** when the test harness sets `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`, always bound to 127.0.0.1 with a random free port. The app never enables it itself, and release builds refuse to start if the variable contains `--remote-debugging-port` (anyone on the machine could otherwise attach to the UI).

---

## 14. Milestones → see ROADMAP.md

The build plan lives in **ROADMAP.md**, as versions v0.1 → v1.1, each a stop-and-test checkpoint. Code structure is in **ARCHITECTURE.md**. How the earlier milestones map onto the versions:

| Earlier milestone | Versions |
|---|---|
| M1 Data + board | v0.1 (MVP mixer), v0.2 (mixer complete) |
| M2 Lichess | v0.3 |
| M3 Stockfish + stuck ladder | v0.2 (hint/answer from the dataset), v0.4 (engine) |
| M5 Modes + stats + reasons | v0.5, v0.6 |
| M4 LLM Explain + guardrails | v0.7 (moved after the modes; guardrails still ship before the first LLM call) |
| M6 Game Review | v0.8 (engine), v0.9 (AI) |
| M7 Coach + fix tracking | v0.10 (Coach), v0.11 (whole-game coaching), v0.12 (training plan and journal), v1.0 (checkpoints, release) |

---

## 15. Licensing

The project is open source under **AGPL-3.0-or-later** from the first commit (`LICENSE` in the repo root).
- **Why AGPL:** chessground is GPL-3.0 and the lichess-puzzler tagger (v0.10) is AGPL-3.0, so the combined work must be AGPL. Starting there avoids relicensing at v0.10.
- **lichess-puzzler** isn't on PyPI, so its tagger (`tagger/cook.py`, `util.py`, `model.py`) is **vendored** under `src/weaksquare/vendor/lichess_puzzler/` at a pinned commit, with its AGPL-3.0 licence and a README giving the commit and the patch (v0.10 planning). Its generator's rules are ported, not copied (FR-10.41).
- **Stockfish (GPL-3.0)** is downloaded by the user's own setup from the official release and never redistributed by this project, so the repo carries no Stockfish binary.
- **Lichess puzzle database:** public domain (CC0). It's downloaded at setup, never committed.
- **The About screen** shows the license and a link to the source code (NFR-7).
- Third-party npm and Python packages keep their own licenses. A dependency with a license incompatible with AGPL-3.0 isn't added.
- The same applies to bundled assets (sounds, images, fonts): each has a recorded source and an AGPL-compatible license (FR-1.13).

---

## 16. Verified external facts (as of 2026-10-31)

| Fact | Source |
|---|---|
| Puzzle DB: ~6.06M puzzles, CSV (zstd), public domain, last updated 2026-07-29. FEN is before the opponent's move; mate-in-one exception | https://database.lichess.org/#puzzles |
| `POST /api/puzzle/batch/{angle}` sets puzzles solved and updates ratings, scope `puzzle:write`, body `solutions[{id,win,rated}]` | https://github.com/lichess-org/api (doc/specs/tags/puzzles/api-puzzle-batch-angle.yaml) |
| Fewer than 100 solutions per request; 400 cost/hour/IP rate limit, authenticated cost 2 per solution | https://github.com/lichess-org/lila (app/controllers/Puzzle.scala, modules/puzzle/src/main/PuzzleForm.scala) |
| Rating updates only on first attempt; `rated:false` records without changing rating; angle weighting (mix = 1.0; motif win 0.2, loss 0.7; obvious themes win 0.1, loss 0.4) | lila modules/puzzle/src/main/PuzzleFinisher.scala |
| PKCE: unregistered public clients OK, S256 only, tokens ~1 year, no refresh tokens; `GET /oauth`, `POST /api/token`, `DELETE /api/token` | lichess-org/api spec (lichess-api.yaml, tags/oauth/*) |
| `GET /api/puzzle/activity` returns ndjson; params `max`, `before`, `since`; scope `puzzle:read` | lichess-org/api spec (tags/puzzles/api-puzzle-activity.yaml) |
| Theme list and counts | https://lichess.org/training/themes |
| chessground: SVG arrows and circles, GPL-3.0 | https://github.com/lichess-org/chessground |
| `GET /api/games/user/{username}`: `max`, `rated`, `perfType`, `evals` (only when analysis exists), `accuracy`, `opening`; 20 / 30 / 60 games/s (anonymous / authenticated / own games) | lichess-org/api spec (tags/games/api-games-user-username.yaml) |
| `GET /game/export/{gameId}` (export one game): params include `evals`, `clocks`, `accuracy`, `opening`, `division`, `pgnInJson` | lichess-org/api spec (tags/games/game-export-gameId.yaml) |
| `GET /api/puzzle/dashboard/{days}`: per theme `nb`, `firstWins`, `replayWins`, `performance`, `puzzleRatingAvg` | lichess-org/api spec (schemas/PuzzleDashboard.yaml, PuzzlePerformance.yaml) |
| chess.com PubAPI: read-only; monthly game archives; serial access unlimited, parallel requests may get 429; descriptive User-Agent with contact recommended; no per-move review labels | https://support.chess.com/en/articles/9650547-published-data-api |
| chess.com PubAPI: no authentication; profile `GET /pub/player/{username}` (404 for unknown users); archives list `/pub/player/{username}/games/archives`; archive game fields `white`, `black`, `accuracies` (only if previously calculated), `url`, `fen`, `pgn`, `start_time` (daily only), `end_time`, `time_control`, `rules`, `eco`, `tournament`, `match` | https://www.chess.com/news/view/published-data-api |
| chess.com OAuth ("Sign in with Chess.com") exists but requires applying for access, so it isn't self-service. The internal "callback" game endpoints aren't for general use, and heavy use risks an IP ban | chess.com developer forum threads; chess-web-api issue #10 |
| lichess-puzzler: Lichess's open-source puzzle generator and tagger (`tagger/cook.py`, python-chess), AGPL-3.0. Not on PyPI. The tagger needs only python-chess; the generator needs MongoDB, a tablebase server and `zstandard`. Pinned for v0.10 at `8e24b6d5e2b9` (2026-10-23) | https://github.com/ornicar/lichess-puzzler |
| Stockfish 19 (tag `sf_19`, released 2026-09-05) ships universal binaries that detect CPU features and run the optimal code, replacing the separate AVX2/AVX-512 builds | https://stockfishchess.org/blog/2026/stockfish-19/ and https://github.com/official-stockfish/Stockfish/releases/tag/sf_19 |
| Windows asset: `stockfish-windows-x86-64-universal.zip`, about 81 MB | SourceForge mirror of the sf_19 release |
| Since Stockfish 19, an invalid position or illegal move prints `info string CRITICAL ERROR` and terminates the process | https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html |
| GitHub computes a SHA-256 digest for every release asset at upload, shown in the Releases UI, REST API and `gh` CLI | https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/ |

### LLM prices used to seed `llm_prices` (USD per 1M tokens, input / output; verify before relying)
| Model | Input | Output | Source |
|---|---|---|---|
| Claude Haiku 5.5 | $0.10 ($0.50 above a 100k prompt) | $0.50 ($2.50 above a 100k prompt) | Anthropic pricing docs, via pricing trackers (Oct 2026) |
| Claude Sonnet 5.5 | $2.00 | $10.00 | same |
| Claude Opus 5.5 | $4.00 | $20.00 | same |
| Claude Fable 5.1 | $10.00 | $50.00 | same |
| GPT-5.4 nano | $0.20 | $1.25 | developers.openai.com model page |
| GPT-5.4 mini | $0.75 | $4.50 | OpenAI pricing, via pricing trackers (2026) |
| GPT-5.4 | $2.50 | $15.00 | same |
| GPT-5.5 | $5.00 | $30.00 | same |

The four Claude rows were re-checked against Anthropic's model table at v0.7 planning (2026-11-03) and match. The GPT rows are re-checked when the OpenAI adapter is written.

Estimated cost per request at these prices (my token estimates; actual usage gets logged): Explain ≈ $0.001 (Haiku 5.5) to $0.045 (GPT-5.5); Coach Detailed ≈ $0.004 to $0.19.

---

## 17. Robustness and operations (non-functional)

- **NFR-1** **Single instance.** A second launch brings the running window to the front and exits. Two copies would mean two database writers and duplicate Lichess submissions. A lock file in the data folder implements this.
- **NFR-2** **Data folder.** Default `%LOCALAPPDATA%\WeakSquare`. The `WEAKSQUARE_DATA_DIR` environment variable overrides it. Dev runs default to `%LOCALAPPDATA%\WeakSquare-dev` and tests always use a temp folder, so building and testing the app never touches your real history.
- **NFR-3** **Migration safety.**
  - Before applying any migration to `user.db`, copy it with SQLite's backup API to `<data>\backups\user-<old schema>-<timestamp>.db`, keeping the last 5.
  - If `user.db` has a newer schema version than the running app knows (for example after rolling back to an older build), refuse to open it and say so. Never write to it.
- **NFR-4** **Logging.** Rotating log files in `<data>\logs` (5 files of 2 MB). The first line of each run records the app version, Python, WebView2 and Stockfish versions. Uncaught exceptions in any thread (`sys.excepthook`, `threading.excepthook`) and front-end errors (`window.onerror`, unhandled promise rejections, forwarded through the bridge and rate-limited) are logged. Redaction per SR-10.
- **NFR-5** **Errors across the bridge.** Every bridge method returns either its result or an error object `{code, message, retryable}`. Python tracebacks, file paths and request details stay in the local log and never reach the UI.
- **NFR-6** **Clean shutdown.** Closing the window cancels running jobs (each saves its progress), stops the engine processes and closes database connections. Pending sync stays queued in `user.db` for next time.
- **NFR-7** **About screen.** App version, data folder (with an Open button), logs folder (with an Open button), puzzle database export date, Stockfish version and path (from v0.4), the license and a link to the source repository.
- **NFR-8** **Runs from source.** `scripts/setup.py` installs everything into a virtual environment and creates a Start-menu shortcut that launches the app without a console window. Updating is `git pull` followed by `scripts/setup.py` again.
  - **NFR-8a** **Desktop shortcut and app icon** (v0.2).
    - **Desktop shortcut:** `setup.py` also creates one by default. `--no-desktop-shortcut` skips it, and `--no-shortcut` skips both shortcuts. It finds the Desktop through the Windows known-folder API, because the Desktop is often redirected to OneDrive. Re-running replaces the shortcuts and never duplicates them.
    - **The icon:** four board squares (2×2, in the board's light and dark colors) with a **black** queen on top (chosen over a white queen because the solid shape stays readable at 32 px and below). The queen comes from the **cburnett** piece set the board already uses (Colin M. L. Burnett, GPL-2.0-or-later, shipped with chessground), so its license is compatible with AGPL-3.0.
    - **Files:** the SVG source is committed. A small script builds a multi-size `.ico` (16–256 px) from it, and the `.ico` is committed too, so `setup.py` needs no image tools. Both shortcuts use it, and the app window and taskbar use it where pywebview allows. The plan checks how to make the taskbar show it rather than the Python icon.
    - **Credits:** recorded in the repo's asset credits and ARCHITECTURE.md §7, like the sounds (§15).

---

## 18. Opening trainer (v0.13; moved from v2.0 by Adam, 2026-11-06)

Learn an opening line by line with grounded explanations, build your own repertoire (including your answers to the opponent's sidelines), then drill it. **The moves always come from a book, the engine, real-game data from the Lichess explorer or you, never from the LLM.** The LLM only explains moves that already exist and have been validated, exactly as in §9.2.

### 18.1 Where the lines come from
- **FR-12.1** **Opening book:** the Lichess `chess-openings` dataset (ECO code, name, PGN; 3,865 named lines when checked on 2026-11-06, median 5 full moves; CC0 public domain). It's bundled with the app, pinned by commit and SHA-256, and imported into its own table in `user.db`, on first opening the Openings page and again only when the bundled version changes. Every line is validated with python-chess at import. Lines are matched by **position**, not move order, so transpositions are recognized. The position key is the FEN without move counters, with an en passant square only if the capture is legal.
- **FR-12.2** **Main lines of an opening:** the named sub-lines under the chosen opening in the book. You can also add popularity data from the **Lichess opening explorer** (masters and Lichess games, the most common replies with their frequencies). The book has no main-line marker, so lines are ranked by explorer popularity when available, otherwise by how many book lines sit under a move, then fewer moves, then name. The **main line** follows the top-ranked move at each step, and sub-lines are the next-ranked branches. The explorer API needs a Lichess token (it returns 401 without one, checked 2026-11-01). It's used only when you're signed in (§8.1), with responses cached locally, and the trainer still works without it. The prefetch scope is configurable (FR-12.7a).
- **FR-12.3** **Engine:** Stockfish evaluates every position you study (the interactive engine, ARCHITECTURE §3 decision 12), and suggests replies to deviations (FR-12.8). Bulk jobs (prefetch, FR-12.7, and Build my repertoire, FR-12.14) use the background engine so they don't hold up the position you're looking at. All positions and move lists are validated before they're sent (FR-7.6).

### 18.2 Repertoire
- **FR-12.4** **Your repertoire** is a tree of positions per color (White and Black). Each move records its **source**: book / engine / explorer / you, plus study from v0.14 (FR-13.11). You pick openings and lines to add, and can remove, reorder or mark a move as "main" or "sideline". Stored in `user.db` (new migration): `repertoire_nodes(id, color, position_key, move_uci, san, source, is_main, sort_order, created_at)`, unique per (color, position_key, move). Moves are edges between positions, not a strict tree, so a transposition reuses the same position. Removing a line deletes only the moves no longer reachable from the starting position.

### 18.3 Learn mode (walks you through lines)
- **FR-12.5** **Overview first:** opening a line starts with an overview of the opening: its key ideas, typical plans for both sides, pawn structures, common traps and what to aim for. It's generated by the LLM from grounded context (the opening name, ECO code, the line's SAN moves, the engine evaluations of its key positions, and Wikibooks text when available, FR-12.15). It's shown as escaped text (FR-8.7), and every square or move it mentions is validated before it's drawn (FR-8.4/8.5).
- **FR-12.6** **Step through the line:** the board walks the moves one at a time, with forward and back controls. Each move has an **Explain** button: why this move, what it prepares, and what happens if you don't play it, grounded in the engine's top lines for that position and Wikibooks text when available (FR-12.15). Without an LLM configured, the step-through still works with engine evals, lines and the Wikibooks panel. A switch changes to play-along (FR-12.16).
- **FR-12.7** **Store everything, ask once:** overviews and move explanations are saved in `opening_notes` in `user.db`, keyed by position (FEN), move, kind (overview / move), provider, model and prompt version. They're reused across lines and transpositions, and the LLM is never asked twice for the same thing.
  - **Prefetch when you start an opening:** the trainer offers to fetch the overview and every move explanation for its main lines in one go. Requests are batched one line per request to keep cost down. It shows the pre-run estimate with **Confirm**, and the per-run cap, monthly budget and hard `max_tokens` all apply (§9.3). Already-stored items are skipped and not charged.
  - **FR-12.7a** **Prefetch scope (configurable, with suggested presets):**

    | Preset | Sub-lines | Moves per line | Use |
    |---|---|---|---|
    | **Light** | main line + 1 | 8 | a quick look, lowest cost |
    | **Standard** (default) | main line + 3 | 12 | the usual choice |
    | **Deep** | main line + 6 | 16 | serious study of one opening |
    | **All** | every book line of the opening | 20 | the whole book for one opening (Adam, 2026-11-07) |
    | **Custom** | 0–10 | 4–20 | your own numbers |

    The global default is in the opening-trainer settings, and you can change it for each prefetch in the prefetch dialog. Moves per line is an upper limit: few book lines reach 12 moves (FR-12.13), and the dialog shows the real counts. **All** shows Deep's lines, then every other book line named under the opening, so each name is on a line (a name partway along a longer line, or reached by transposition, isn't repeated). Only the opening's own names count, so a broad opening such as King's Pawn Game doesn't take in every 1. e4 line. A long list scrolls in its own box.
  - **FR-12.7b** **What it will cost and how long it takes:** the prefetch dialog updates as you change the scope. Before you confirm, it shows:
    - **How much:** the number of lines, positions and LLM requests, with how many are already stored (and so free).
    - **Usage:** estimated input and output tokens and cost, computed from the `llm_prices` table for your provider and model (never hard-coded), plus what share of the remaining monthly budget that is. It says plainly whether the run fits under the per-run cap (FR-8.12).
    - **Time:** estimated LLM time (requests × the recent average response time for your model, or a conservative default until there's history) plus engine time (positions × the analysis time per position).
    - **Blurb:** a short plain-language note, e.g. *"About 45 moves across 4 lines: ~4 requests, ~$0.03 (≈1% of this month's budget), about 2 minutes. Already-saved notes are free. You can keep using the app while it runs, and cancel at any time; whatever is finished stays saved."*
    - **Larger scopes:** a yellow warning when the estimate is above 25% of the remaining monthly budget or longer than 10 minutes. When it's over the per-run cap, the dialog offers to **split it into several runs**, each under the cap. It never raises the cap automatically.
    - **Without an LLM:** the dialog shows engine time only.
    - **While it runs:** prefetch is a background job with progress and Cancel. Finished items are saved as they arrive.
  - Saved notes work offline. A **Regenerate** button on any note replaces it after showing the cost. You can also export or delete an opening's notes.
- **FR-12.8** **"What if they play…?" (your own deviations):** at any position in a line, you can enter a move for the **other side**, either on the board or as SAN.
  - The move is validated with python-chess.
  - Stockfish gives your best replies (MultiPV, default top 3, with evals), and you pick one, by default the best.
  - **Explain** says why that reply works, the same way as FR-12.6.
  - The branch (their move, your reply, the engine evals and the explanation) is **stored** in your repertoire with `source = you` / `engine`, and is drilled in Practice like any other line.
  - Engine results are cached by position, think time and engine, so revisiting a branch costs nothing.

### 18.4 Practice mode (quizzes you on your lines)
- **FR-12.9** **Drill your repertoire:** the app plays the opponent's moves from your repertoire, picking among the stored replies (weighted toward main lines, and by explorer popularity when it's available). You play your side.
  - **Correct:** any move stored as yours at that position, or one within the engine tolerance if you allow it in settings (off by default, because the point is to learn *your* line).
  - **Wrong:** shows the correct move, its stored explanation and the engine's view of your move (the refutation, using the same tools as Game Review FR-11.14). Any help before the line ends is a loss (§7.1).
  - Mistake reasons (§7.3) work here too.
- **FR-12.10** **Spaced repetition per position:** each of your decision points has its own Leitner box (same schedule as FR-4.6). Practice shows positions that are due first, and **New lines** introduces unseen branches a few at a time. Sessions can be limited to one opening, one color or one branch.
- **FR-12.11** **Stats:** per opening and per line, the accuracy, due count and weakest positions. All local, never synced to Lichess, and no effect on any rating.

### 18.5 Privacy and cost
- **FR-12.12** The LLM receives only opening data: names, ECO codes, SAN moves of book or repertoire lines, engine evals and lines, and Wikibooks text (FR-12.15). It never receives anything about you or your games. Explorer requests send positions to Lichess with your token, to the documented API only, and Wikibooks requests send a line's moves to Wikimedia as a page title. Both appear in the User Guide's privacy section. Prefetch estimates reuse the §9.3 machinery. A typical opening (overview plus 4 lines of about 12 moves) is roughly 20–30k input tokens and 8–12k output tokens in total. The v0.13 plan replaces this with figures from the `llm_prices` table, never hard-coded.

### 18.6 Added at v0.13 planning (Adam, 2026-11-06)
- **FR-12.13** **Short book lines (configurable):** a setting, also on the prefetch dialog, with two choices.
  - **Extend past the book** (default): after the book ends, continue with the explorer's most-played move, otherwise Stockfish's best, up to the preset length.
  - **Stop at the book's end:** only book moves, and the preset length is an upper limit.
  - Every move in a line shows its source.
- **FR-12.14** **Build my repertoire:** a background job that takes a color, an opening and limits (default 12 moves, replies with at least 5% of games, up to 3 replies per position, up to 60 positions), all editable, and proposes a tree.
  - **Opponent replies** come from the explorer when you're signed in, otherwise from the book.
  - **Your answer** at each position, in order: one you already have, the book, the explorer's most-played if within 50 cp of the engine's best, the engine's best.
  - **Gaps are flagged:** an answer that fell back to the engine, too few games, or a bad eval.
  - You review the tree before anything is saved, and it never overwrites a move you stored.
- **FR-12.15** **Wikibooks:** text from the *Chess Opening Theory* pages on English Wikibooks (CC BY-SA 4.0), found by the line's SAN path.
  - **Fetching:** at runtime through `adapters/http.py`, saved locally, never bundled, and never before you Confirm a prefetch. A setting turns all use off.
  - **In the prompt:** cut to a size limit per page and per request, with URLs and reference sections removed, and marked as untrusted reference text. The engine outranks it when they disagree. A missing page, an offline run or the setting turned off means engine-only grounding, and the note says so.
  - **Shown to you:** a panel with the text as plain text, attributed and linked, so concepts work with no AI key.
  - **Attribution:** a note records the pages and revisions it used and shows *Based in part on Wikibooks: page, CC BY-SA 4.0, may be adapted*, with links built by the app. Exported notes carry the same notice and are marked CC BY-SA 4.0.
- **FR-12.16** **Play-along:** a switch in Learn mode. The app plays the other side and you make your moves, with a retry and a nudge if you go wrong. Nothing is scored. Lichess studies reuse this screen (FR-13.8).

## 19. Lichess studies (v0.14; Adam, 2026-11-06)

Find Lichess studies, work through them in the app and keep your place. The Lichess API has no way to browse or search all public studies, only to fetch one by ID or list one author's (checked 2026-11-06), so finding them uses the four ways below.

### 19.1 The Studies tab and finding studies
- **FR-13.1** **Studies tab:** two parts, **My studies** and **Find studies**. My studies lists everything you've added, with its title, author, your progress (such as "Chapter 3 of 8") and **Continue**, and can be filtered by favorites, in progress or finished.
- **FR-13.2** **Four ways to find a study:** the Lichess window (FR-13.3), your browser and a pasted link (FR-13.5), studies by author (FR-13.5a, Adam, v0.14 planning), and the starter list (FR-13.6).
- **FR-13.3** **Lichess window:** opens the real `lichess.org/study` pages in a separate window inside the app, so you can browse and search them. This is the only place the app shows a remote website.
  - It has **no bridge** and no access to your settings, tokens, database or files. A test proves it.
  - It stays on `lichess.org`. Any other link opens in your normal browser.
  - It's isolated from the app's own page, and the app never reads what you type in it.
  - If this isolation can't be proven when v0.14 starts, the window is dropped and FR-13.5 and FR-13.6 remain. Adam decides what happens next.
- **FR-13.4** **Add this study:** a button on the Lichess window, active only on a study page. The app takes only the study's ID from the address, then downloads it as in FR-13.7.
- **FR-13.5** **Browser and paste:** **Open Lichess** opens the study list in your normal browser. You paste a study's link, a link to one of its chapters (`lichess.org/study/{id}/{chapterId}`), or its ID, into the tab. A chapter link opens that chapter once the study is added. Anything that isn't a Lichess study address gets a clear message and no request is made.
- **FR-13.5a** **Studies by author** (Adam, v0.14 planning): type a Lichess username to list that author's public studies with `GET /api/study/by/{username}`, which returns only each study's ID, name and dates (checked 2026-11-06). Picking one downloads it as in FR-13.7. An unknown user, no studies and offline each get a clear message. That endpoint answers an unknown user with an empty list, not an error (checked 2026-11-08), so only when the list is empty the app asks `GET /api/user/{username}`, whose 404 means there's no such user.
- **FR-13.6** **Starter list:** a list that ships with the app, filterable by opening. It holds **only links, titles and authors, never study content**. A study is downloaded only when you pick it. It changes only with new app versions, and Adam approves its first contents.

### 19.2 Your copy of a study
- **FR-13.7** **Download and store:** `GET /api/study/{id}.pgn` through `adapters/http.py`, one request at a time, documented API only. Public studies need no sign-in. The request is first made **without** your token. Only if Lichess refuses it (403) and your sign-in has `study:read` (FR-6.1) is it retried with the token, so a private study you own or belong to works. A sign-in from before v0.14 lacks that scope, so the app says *Sign in again to allow reading your private studies*. A study you can't read even when signed in says so plainly.
  - Every move is validated with python-chess. An illegal chapter is rejected with a clear message and the rest are kept.
  - **Text chapters** (Adam, v0.14 planning): a chapter with **no moves** whose position python-chess calls invalid (a decorative board, such as an empty board or pawn art with no kings) is kept as a text chapter. Its text and board are shown as-is, with no engine, play-along or Add to repertoire. A chapter that has moves from an invalid position is rejected.
  - Comments and chapter titles are untrusted: rendered as escaped plain text and never turned into links, even when they contain a web address. An arrow or highlight naming an invalid square is dropped.
  - The copy is stored in `user.db` (new migration), so a saved study works offline and stays if its author later deletes it.
  - **Check for updates** downloads the latest version and shows what changed before replacing your copy. Your place is kept when that chapter still exists.
  - **Rights:** the study's author keeps their rights. Study content is never bundled, shipped or shared by the app, and each copy stays on your PC. The study's title, author and a link back are always shown.

### 19.3 Working through a study
- **FR-13.8** **Play along:** using the same screen as Learn mode (§18.3). The chapter's text, arrows and highlighted squares appear as you go. In an interactive (`gamebook`) chapter you play the moves yourself; other chapters step forward and back. Alternative moves are shown as branches. Nothing here is scored or affects any rating. *(v0.14 planning: most real chapters are normal analysis chapters with deep branching, e.g. up to 120 side moves in one chapter of Adam's Vienna study, so the move list shows nested branches you can click, with Back, Forward and Back to main line.)*
  - **How closely it matches Lichess** (checked during the v0.14 build against Adam's test studies `ZCPaIb70` and `nq1GGbNO`, and 24 starter studies):
    - **The same:** the main line inline with move numbers, side lines indented under the move they replace, nested; each comment after its move; the glyphs !, ?, !!, ??, !? and ?!; arrows and highlighted squares in Lichess's green, red, yellow and blue; the arrow keys and clicking any move. In a gamebook chapter the app plays the other side along the main line, the author's text and arrows for each move appear as you go, and a wrong move the author wrote a side line for shows the author's text for it.
    - **Different, on purpose:** web addresses in comments and titles are plain text, never links (FR-13.7). No engine, explorer, chat or other people's comments.
    - **Different, because the PGN export doesn't carry it:** Lichess's gamebook hints and its custom wrong-move messages aren't in `/api/study/{id}.pgn`, so **Hint** highlights the piece to move and an uncovered wrong move says *Not this one. Try again.* Lichess-only commands such as `[%anno]` are dropped.
- **FR-13.9** **Hearts:** you can heart any of your studies and filter by them. They're stored only in the app, because the API has no way to like a study, so they never appear on Lichess.
- **FR-13.10** **Your place:** the app saves your chapter and move in each study as you go. A chapter is finished when you reach the end of its main line; a chapter with no moves (an introduction or a text chapter) is finished when you open it. **Continue** returns you there, and you can restart a chapter or the study. Progress is local and never sent to Lichess.
- **FR-13.11** **Add to my repertoire:** adds a chapter's or study's lines to your repertoire (FR-12.4) with `source = study`, for the color you choose. By default only each chapter's **main line** is added, because side lines mix the opponent's alternatives with the author's analysis of other moves for your side. An **Include side lines** switch adds them too (Adam, v0.14 planning). You review what will be added before anything is saved. Positions are matched by FEN, so a transposition reuses its position. If a study's move conflicts with one you have there, you choose which stays: **Keep mine** (the default) skips the study's move and what only it leads to; **Use the study's** makes it your main move there and keeps yours as a sideline, so nothing of yours is deleted (v0.14 build). Your repertoire starts from the first move, so only moves reachable from it are added: a chapter that starts from a set position joins only if your repertoire already reaches that position, and the preview says how many moves were skipped. The added lines are drilled in Practice (FR-12.9).

### 19.4 Privacy
- **FR-13.12** Study text is never sent to an LLM. Requests to Lichess and everything the Lichess window loads appear in the User Guide's privacy section.

## 20. Analysis board tab (v0.15; Adam, 2026-11-06)

A board of its own for setting up positions, importing PGNs and exploring. It reuses the existing analysis board (FR-7.7, FR-11.34).

- **FR-14.1** **The tab:** an **Analysis** tab that opens at the starting position and needs no puzzle or game. Your lines are kept while the app is open, including when you switch tabs, but they're never saved: closing the app clears them (Adam, v0.15 planning). Replacing a board that has moves (a new board, an imported game, or Open in Analysis tab) asks first, and **Keep my board** leaves it as it was.
- **FR-14.2** **Set up a position:** drag pieces onto or off the board, choose the side to move and castling rights, or paste a FEN. An illegal or impossible position gets a clear message and never reaches Stockfish (FR-7.6). *(v0.15 build: each problem python-chess finds gets its own sentence, such as "Black has no king." A castling box is greyed out unless that king and rook are on their starting squares. Pieces can also be placed by picking one from the palette and clicking squares.)*
- **FR-14.3** **Import a PGN:** paste a PGN and step through it with the controls and keys Game Review uses. A bad PGN gets a clear message and changes nothing on the board. Comments show as escaped plain text. The game isn't added to your library. *(v0.15 build: side lines come with it; headers, clocks and other `[%…]` commands are left out. A PGN with several games lists them to pick one; games that can't be used are listed with the reason.)*
- **FR-14.4** **Explore:** move for either side, legal moves only, and the lines you try stay as branches you can move between. The interactive engine shows the eval, top 3 lines and an arrow for its best move, worded from White's side ("+0.3", "White mates in 3") because you play both sides. Popular replies come from the Lichess explorer (FR-12.2) when you're signed in, and are skipped cleanly otherwise. *(v0.15 build: each reply shows its games and White wins, draws and Black wins; clicking one plays it. They use the explorer settings from the opening trainer and share its saved answers.)*
- **FR-14.5** **Nothing counts:** moves here are never scored, and never change puzzles, stats, your game library or Coach reports. Nothing here goes to an LLM.
- **FR-14.6** **Open in Analysis tab:** a button on the existing analysis boards, in puzzles and Game Review, opens the current position in this tab, with the moves that led to it (the game from its start, or the puzzle from its start) so you can step back through them (Adam, v0.15 planning).
