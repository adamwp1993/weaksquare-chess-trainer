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

**Decided:** front end = React + TypeScript + Vite + Mantine (see ARCHITECTURE.md §3). **Decided:** runs from source, no packaged `.exe` (NFR-8; ARCHITECTURE.md §7). **To decide during the build:** default model IDs (v0.7).

---

## 3. Application flow

### 3.1 Startup page
Shown when the app launches.

- **FR-1.1** "Sign in with Lichess" button runs the OAuth PKCE flow (§8.1). Shows status: *Not signed in* / *Signed in as `<username>`* / *Sign-in failed (reason)*.
- **FR-1.2** LLM provider dropdown: *None*, *Anthropic*, *OpenAI*.
- **FR-1.3** Model field for the selected provider. Pre-filled with a default but editable. Model names must not be hard-coded anywhere else in the app.
- **FR-1.4** API key field (optional, masked) with a **Test key** button that makes a minimal API call and reports success or the error.
- **FR-1.5** **Continue** button goes to the main page.
- **FR-1.6** **Fast path:** if a stored Lichess token validates against `GET /api/account`, and either no LLM is configured or the stored key passes a silent test, the page shows a single **Continue as `<username>`** button, listing the linked chess.com username if there is one. A link expands the full form.
- **FR-1.11** **Linked accounts panel:** Lichess (the signed-in account, FR-1.1) and an optional **chess.com username** with a **Verify** button (§11.5). Either account can be unlinked here or in the gear settings.
- **FR-1.7** **Offline / sign-in failure:** the user can always continue without being signed in. Solves are recorded locally and queued for sync (§8.4). The main page shows an "Offline: N solves waiting to sync" indicator.

### 3.2 Main page
- Puzzle filters and queue controls (§5), training-mode selector (§6), board, the stuck ladder (§7.2), **Coach** button (§10), **Import game** button (§11), stats (§12).
- **FR-1.8** **Gear icon** opens the same settings as the startup page (linked Lichess and chess.com accounts, game-sync options, LLM provider/model/key, engine settings) plus the **LLM price table and budget** (§9.3), without leaving the main page.
- **FR-1.10** A small **LLM spend indicator** (this month's spend vs. budget) appears whenever an LLM is configured.
- **FR-1.9** **Rated toggle** (session-level, default ON). When off, every solve this session syncs as `rated: false`.
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
- `weaknesses(id PK, key, kind, label, first_seen_checkpoint, baseline_rate, baseline_games, status, status_changed_at, related_themes)`. `key` is a theme or simple-tag key; `kind` is missed / allowed / habit.
- `weakness_metrics(weakness_id, checkpoint_id, window_games, occurrences, game_rate, puzzle_attempts, puzzle_first_try_accuracy)`: the trend data for each weakness at each checkpoint
- `game_analysis(game_id, ply, fen_before, move_uci, mover, eval_before, eval_after, best_move, multipv_json, cp_loss, classification, themes, kind, phase, low_clock)`: one row per analyzed move. Shared by Game Review (§11) and the Coach (§10). `kind` is missed / allowed / other for mistakes.
- `game_errors`: a **view** over `game_analysis`, containing the user's mistakes only, used by the Coach
- `custom_puzzles(id PK, game_id, ply, fen, solution_uci, themes, origin, kind, severity, cp_loss, phase, time_control, game_date, solve_as, status, created_at, UNIQUE(game_id, ply))`: puzzles from your own games. `origin` is manual (Save as puzzle, FR-11.16) or coach (FR-10.39). `kind` is missed / allowed. `severity` is inaccuracy / mistake / blunder. `solution_uci` holds the full line. `solve_as` is you / opponent. `status` is active / archived. They live in `user.db`, never `puzzles.db`, which is replaced on every re-import (FR-2.3). Their attempts are stored in `attempts` with ids prefixed `my:`.
- `mistake_reasons(id PK, source, ref_id, reason, suggested_reason, note, created_at)`: why you missed something (§7.3). `source` is puzzle / game / retry / danger; `ref_id` points to an `attempts` row or a `game_analysis` (game_id, ply).
- `coach_reports(id, created_at, sources_json, params_json, report_json, provider, model, cost_usd)`

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
| FR-3.9 | History | Checkboxes: exclude solved here / exclude played on Lichess / **only my misses** | Uses `attempts` and `lichess_history`. *Exclude solved here* (**on by default**) hides puzzles you've **won at least once** in this app; ones you only failed can still come up. *Only my misses* (off by default) keeps only puzzles whose **latest** attempt here was a loss, so a miss drops out once you solve it. *Exclude played on Lichess* (**on by default**, decided at v0.3 planning) hides puzzles in your imported Lichess history (FR-6.17) and those you've synced from here, because Lichess never changes your rating for a puzzle you've already played; with no imported history it changes nothing. |
| FR-3.10 | **Ratios** (optional) | Weighted buckets, e.g. 50% fork, 30% capture-the-defender, 20% one-move | Draws from each bucket by weight |
| FR-3.11 | Order | Random / easy → hard / grouped by theme | |
| FR-3.12 | Queue size | Fixed N or endless | |
| FR-3.13 | **Presets** | Save / load / rename / delete named filter sets | Stored as JSON |
| FR-3.14 | Hidden labels | Themes are **not shown** while solving | Revealed after the puzzle ends |
| FR-3.15 | Puzzle source | Lichess DB / **My games** / Both | "My games" = `custom_puzzles`, saved from Game Review (§11) or created by the Coach (§10.9). These never sync to Lichess. Extra filters for My games: severity level (FR-10.40), Missed / Allowed, phase, time control, game date, origin. They have no rating, so the rating filter doesn't apply to them. |

---

## 6. Training modes

All six modes ship in version 1. The user picks one per session from a selector on the main page.

| ID | Mode | How it works | Win condition | Syncs to Lichess |
|---|---|---|---|---|
| FR-4.1 | **Standard** | Lichess-style: you move, the opponent's reply plays automatically | Every player move correct, no help used | Yes |
| FR-4.2 | **Commit the line** | Plan mode: you play **both sides** of the full line on the board (your moves plus the replies you expect), with nothing validated, then press **Submit**. The line is then graded against the solution. | Every **player** move matches. Predicted opponent replies are scored separately as "calculation accuracy" and don't affect the win. | Yes |
| FR-4.3 | **Name the idea first** | Before moving, you tag the idea: setup motif(s), payoff motif(s), and optionally the target square or defender. Then you solve normally. Afterwards your tags are compared to the puzzle's themes. | Same as Standard. Tag accuracy is a separate stat. | Yes |
| FR-4.4 | **Danger spotting** | Shows the **pre-blunder position** (the raw FEN) from the side that's **about to blunder**, with a candidate move highlighted. You answer **Safe** or **Unsafe**. If Unsafe, you play the refutation. Candidates are about 50% the real blunder and 50% a **Stockfish-verified safe move**, so the answer is never always "Unsafe." | Correct Safe/Unsafe call, plus the correct refutation when Unsafe | **No** (local stats only; this doesn't correspond to solving the Lichess puzzle as served) |
| FR-4.5 | **Depth ladder** | For the selected motifs, starts at short puzzles and moves up to long, then very long, once accuracy is at least the threshold over a rolling window (default 80% over the last 20; configurable) | Same as Standard | Yes |
| FR-4.6 | **Spaced repetition** | Missed puzzles come back on a Leitner schedule (default boxes: 1, 3, 7, 14, 30 days). A win moves the puzzle up a box, a loss resets it to box 1. | Same as Standard | Yes. Lichess won't change your rating for a puzzle you've already played, so the app shows an "already played: rating unaffected" badge. |

---

## 7. Scoring and the "stuck" ladder

### 7.1 Scoring rules
- **FR-5.1** A **win** means the full line was solved with no wrong move and **no help used**. This matches Lichess's definition.
- **FR-5.2** **Any help before completion counts as a loss:** Hint, Show answer or Explain.
- **FR-5.3** A wrong move is a loss. The puzzle then continues so you can see the solution, with nothing more to lose.
- **FR-5.4** After a puzzle ends (win or loss), Show answer and Explain are free.
- **FR-5.5** Record per attempt: `first_move_correct`, `line_correct`, `help_used` (none / hint / answer / explain), and `time_ms`.

### 7.2 Stuck ladder (each step unlocks the next)
1. **Hint**: highlights the piece that moves next. Counts as a loss.
2. **Show answer**: plays the solution step by step with back/forward controls. If you played a wrong move earlier, it first shows **Stockfish's refutation** of that move (the best reply line, 3–5 plies, with eval). Counts as a loss.
3. **Explain** (only if an LLM is configured): see §9. Counts as a loss.

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
- **FR-5.8** **One click, never blocking:** a row of 6 reason chips below the board, with keyboard shortcuts **1–6** and a Skip option. The next puzzle loads as normal, and the chips stay available on the result panel until you move on. A setting controls how often you're asked: *Always* / *Game Review only* / *Off*.
- **FR-5.9** **Suggested reason:** the app pre-highlights a likely reason, but it's only saved when you click it.
  - `rushed`: move made in under 3 s (configurable), or a game move made with a low clock
  - `miscalculated`: first move correct, later move wrong (puzzles), or the right idea's first move was played but the continuation failed (games)
  - `missedResource`: your move was refuted by an opponent reply that is a check, capture or tactic
  - `unknownPattern`: in Name-the-idea mode, your tags didn't include the puzzle's main motif
  - No suggestion otherwise
- **FR-5.10** **Misclick handling:** a `misclick` attempt is **excluded** from local accuracy stats and weakness metrics, and counted separately. If an unusually high share of your misses are tagged misclick, the app says so. **It still counts as a loss on Lichess:** no take-backs, and the sync isn't changed.
- **FR-5.11** **What it feeds:**
  - **Stats:** reason breakdown overall, per theme, per habit tag and per mode (FR-9.7)
  - **Coach:** reason breakdown per weakness (FR-10.38), and drill-mode choice in the Suggested mix (FR-10.29)
  - **LLM coaching:** reason counts only, never your notes, unless you explicitly include them

## 8. Lichess integration

### 8.1 Authentication: OAuth 2.0 with PKCE
- **FR-6.1** Authorize at `GET https://lichess.org/oauth` with `response_type=code`, an arbitrary unique `client_id` (Lichess supports unregistered public clients), `redirect_uri`, `code_challenge_method=S256`, `code_challenge = BASE64URL(SHA256(code_verifier))`, `scope=puzzle:read puzzle:write`, and a random `state`.
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

### 9.2 LLM "Explain"
- **FR-8.1** Optional. The button only appears when a provider and key are configured. Providers: **Anthropic** and **OpenAI**, behind one interface (`explain(context) -> ExplainResult`).
- **FR-8.2** **The LLM explains; it doesn't calculate.** It receives grounded context:
  - FEN, side to move, the full solution line (SAN and UCI)
  - Puzzle themes (revealed at this point)
  - The user's attempted moves, and Stockfish's refutation of any wrong move
  - Stockfish MultiPV lines and evals
  - Attack/defense facts computed by python-chess for the key squares and pieces (what attacks and defends the target, what each solution move changes)

  The prompt tells it to use only the moves provided and never invent moves or pieces.
- **FR-8.3** **Structured output** (JSON): a short summary, then one step per solution move containing an explanation and annotations (`arrow from→to`, `circle square`, color), then key ideas (e.g. "deflection," "overloaded defender").
- **FR-8.4** **Validation before display:** every move must be legal in sequence from the puzzle position, and every square must be valid. Drop invalid annotations and show a small "some annotations were discarded" note.
- **FR-8.5** **"Show me":** steps through the solution on the board, drawing each step's arrows and circles with chessground's shape API.
- **FR-8.6** **Cost control:** only runs on an explicit button press. Results are cached by `(puzzle_id, user move path, provider, model)`. All guardrails in §9.3 apply.
- **FR-8.7** LLM text is rendered as **escaped text / sanitized markdown**, never raw HTML (prevents injection into the web view).
- **FR-8.8** Timeouts and readable errors (bad key, quota, network).

### 9.3 LLM cost guardrails (apply to Explain and Coach)
- **FR-8.9** **Editable price table** (`llm_prices`), seeded with the prices in §16 (as of 2026-10-31), including long-context price tiers (e.g. Claude Haiku 5.5 charges more above a 100k-token prompt). Every cost figure in the app is computed from this table and the token counts the provider actually reports.
- **FR-8.10** **Usage log:** every request records feature, provider, model, input and output tokens, and cost.
- **FR-8.11** **Pre-run estimate:** manually started Coach runs always show estimated input/output tokens and cost, with a **Confirm** button. Automatic checkpoint runs follow FR-10.37. Explain shows its estimate inline (no confirm needed, since it's cents at most).
- **FR-8.12** **Per-run cap** (default **$0.50**). A request estimated above the cap is blocked unless the user raises the cap.
- **FR-8.13** **Monthly budget** (default **$5.00**). Warn at 80%. At 100%, Explain and Coach are disabled until the next month or until the budget is raised.
- **FR-8.14** **Hard `max_tokens`** on every request. Defaults: Explain 1,500; Coach Summary 2,500; Coach Detailed 5,000.
- **FR-8.15** **Reasoning / thinking effort** setting, default **off/low**. Hidden reasoning is billed as output and can multiply cost 2–5×. If enabled, the estimate accounts for it.
- **FR-8.16** Prompts stay compact by design. The app never sends raw PGNs (headers, clocks, comments) to the LLM, and never sends batches of games. The only game text allowed is a **single game's SAN move list**, for the Game Review narrative (FR-11.19), anonymized. The Coach sends aggregates only (§10).

---

## 10. Coach: weakness analysis and recommendations

**Principle:** Stockfish and python-chess do the analysis locally, for free. The LLM gets only a compact summary and does the coaching. LLM cost doesn't grow with the number of games analyzed. Without an LLM key, the Coach still produces a full weakness report and recommended presets.

### 10.1 Sources and settings
- **FR-10.1** A **Coach** button on the main page opens the Coach page.
- **FR-10.2** **Source picker:** *Puzzle history* / *Games* / *Both*, with a usage note on each:

  | Source | Engine time | LLM tokens | What it shows |
  |---|---|---|---|
  | Puzzle history | None | Lowest | Themes you fail when you know it's a puzzle |
  | Games | Minutes (local CPU) | Low (summary) | What actually costs you games, including tactics you **allowed** |
  | Both | Minutes | Low | Gaps between puzzles and games (e.g. solving forks in puzzles but walking into them in games) |

- **FR-10.3** **Accounts:** defaults to your **linked accounts** (§11.5), and you can override them per run. Lichess username and/or chess.com username. Accept either a plain username or a profile URL (`lichess.org/@/<user>`, `chess.com/member/<user>`).
- **FR-10.4** **Game filters:** count **25 / 50 / 100 / 200 (default 50)**; rated only (default on); time controls (default **rapid + classical**, since bullet and blitz mistakes come from the clock, not from tactics); color.
- **FR-10.5** **Detail level** for LLM coaching: **Summary** (~5k input tokens: aggregates plus 10–15 example positions) or **Detailed** (~20k input tokens: aggregates plus your 20 worst moments with context).

### 10.2 Fetching games
- **FR-10.6** **Lichess:** `GET /api/games/user/{username}` with `max`, `rated`, `perfType`, `evals=true`, `accuracy=true`, `opening=true`, as ndjson. Use the token when signed in (own-game export is faster). Documented rates: 20 games/s anonymous, 30 games/s authenticated, 60 games/s for your own games. Back off on 429.
- **FR-10.7** **chess.com:** Published-Data API. List the monthly archives, then fetch months newest-first **strictly one request at a time** (parallel requests get 429). Send a descriptive `User-Agent` with contact info (the project's repository URL, never a personal email), use ETag caching, and stop once N matching games are collected. Treat 410 as permanent.
- **FR-10.8** Cache games locally (`games`). Re-runs fetch only newer games.

### 10.3 Finding and tagging mistakes (local, free)
- **FR-10.9** Analyze **only the user's moves**. Use Lichess's existing evals when the game has them; otherwise run a quick Stockfish pass (default ~0.15 s per position), then a deeper check on candidate mistakes.
- **FR-10.10** **Thresholds** (configurable): mistake = eval drop of at least 100 cp; blunder = at least 200 cp or a mate swing. Skip the first 6 moves (opening book) and positions already decided (beyond ±500 cp).
- **FR-10.11** Each mistake is classified as:
  - **Missed:** you had a winning tactic. Its line comes from Stockfish's principal variation from your position.
  - **Allowed:** your move let the opponent win material or mate. Its line comes from Stockfish's principal variation after your move.
  - **Other:** a positional or untaggable mistake.
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
- **FR-10.28** **First run:** after the first Coach run, the app builds a **Suggested** preset, and it becomes the default puzzle selection on the main page, labeled *"Suggested — from checkpoint #N, <date>"*. Before any Coach run exists, the default is a broad mix (all themes, all lengths, rating band around your Lichess puzzle rating or 1500).
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
- **FR-10.32** **Trigger:** a checkpoint runs automatically after every **10 new eligible games** across your linked accounts (eligible = matches the Coach game filters, FR-10.4; default rated rapid + classical). There's also a **Run checkpoint now** button. Both numbers are configurable.
- **FR-10.33** **What a checkpoint does:** syncs and analyzes the new games in the background (§11.2 pipeline; local CPU only, free), recomputes every weakness metric, updates statuses, saves a `coach_checkpoints` row, and rebuilds the Suggested preset (§10.7).
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
- **FR-10.36** **Overall game health per checkpoint** (context, not statuses): blunders, mistakes and inaccuracies per game; average centipawn loss overall and by phase; habit-tag rates; **mistake-reason mix** (share of process / calculation / knowledge / time, from §7.3); results; and rating on each platform.
- **FR-10.37** **AI at checkpoints:** the engine and statistics part always runs automatically and is free. An optional setting, **Auto AI checkpoint summary** (default **off**), adds an LLM commentary on what improved, what didn't and why the mix changed, using the Summary detail level. When it's on, it runs without a Confirm prompt **only if** the estimate is under the per-run cap and within the monthly budget (§9.3). Otherwise it waits behind a **Get AI take** button with the usual estimate and Confirm. A Summary costs about $0.001 (Claude Haiku 5.5) to $0.07 (GPT-5.5) per checkpoint.
- **FR-10.38** **Progress page:** one card per weakness, showing status, baseline vs. current game rate, a trend line across checkpoints (game rate and puzzle accuracy on the same chart), the **mistake-reason breakdown** for that weakness (e.g. *"Knight forks: 70% didn't look, 20% miscalculated"*), and click-through to the latest game examples. Plus a checkpoint history with the overall game-health trends, and an optional notification when a weakness changes status (*"Allowed forks: Improving → Fixed"*).

---

### 10.9 Puzzles from your games
- **FR-10.39** **Created by the analysis:** when the Coach analyzes your games (default your last 50, up to 200, FR-10.4; checkpoints add only new games), it turns qualifying mistakes into puzzles in `custom_puzzles` with `origin = coach`. It's part of the same background job and the same pipeline (FR-10.26). Games already analyzed aren't analyzed again. Re-runs never create duplicates (one puzzle per game and ply). Everything stays local and never syncs to Lichess.
- **FR-10.40** **Severity level (user setting):** which mistakes become puzzles. **Blunders only** / **Mistakes and blunders** (default) / **Inaccuracies, mistakes and blunders**. The levels use the shared thresholds (FR-11.9).
  - Changing the level rebuilds the set from the stored `game_analysis`, with no new engine pass over the games. Only new candidates get the quality check (FR-10.41).
  - Narrowing the level **archives** the puzzles outside it, never deletes them, so their attempt history is kept. Widening restores them.
  - The same three choices are also a filter when training the My games source (FR-3.15).
- **FR-10.41** **Quality check:** a mistake becomes a puzzle only if it has a clear answer.
  - The best move must be clearly better than the second best (default gap 150 cp, configurable), or be the only move that keeps the advantage.
  - The position must not already be decided (beyond ±500 cp before the move).
  - The line extends while the solver's move stays the only good one, the way Lichess builds multi-move puzzles.
  - Prefer reusing lichess-puzzler's generator logic (AGPL-3.0, already a dependency for tagging) over writing our own. Confirm this in the v0.10 plan.
  - Inaccuracies are kept only when they pass the same check, so the inaccuracy level may add few puzzles. The setting says so.
- **FR-10.42** **Missed and Allowed:**
  - **Missed** (you had a tactic and didn't play it): you solve from your own position, as the side you played.
  - **Allowed** (your move let your opponent in): you solve **as your opponent**, from the position after your mistake, finding the punishment. The board is oriented for the side to move, and the puzzle is labelled *"Find what your opponent could have played."*
  - Allowed positions can also feed Danger spotting (FR-4.4) once that mode exists.
- **FR-10.43** **Solving rules:** these come from engine analysis, not a verified single solution, so any move within 30 cp of the best (configurable, shared with Retry mode FR-11.15) counts. The interactive engine then continues the line from the move you played. Themes come from the lichess-puzzler tagger and stay hidden until the puzzle ends (FR-3.14). Any help before completion is a loss, as everywhere (§7.1).
- **FR-10.44** **Training them:**
  - **My games** works as a source on its own or mixed with Lichess puzzles, in every mode that supports it, including **Spaced repetition** (FR-4.6).
  - The Suggested mix (§10.7) may include a share of your own-game puzzles (default 20%) linked to your top weaknesses, and "Why this mix" says so.
  - Each puzzle links back to its game in Game Review. You can archive any puzzle you don't want.
- **FR-10.45** **Progress:** accuracy on your own-game puzzles appears on each weakness card (FR-10.38) next to Lichess-puzzle accuracy. It's a secondary signal only. A weakness's status is still decided by its game rate (§10.8), never by puzzle accuracy.

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
- **FR-11.3** **Lichess URL** (`lichess.org/<gameId>`, optionally followed by `/white`, `/black` or `#<ply>`): take the 8-character game ID and call `GET /game/export/{gameId}` with `evals=true`, `clocks=true`, `accuracy=true`, `opening=true`, `division=true`. Reuse Lichess's evals when the game was already analyzed there.
- **FR-11.4** **chess.com URL** (`chess.com/game/live/<id>` or `/game/daily/<id>`): the public API has no single-game endpoint. Search the user's recent monthly archives for the matching game URL, using the username from settings (or ask once), with serial requests only (FR-10.7). If it isn't found, ask the user to paste the PGN (chess.com: Share → PGN).
- **FR-11.5** **Your color:** detected by matching the PGN player tags against your configured usernames. Otherwise the app asks which side you played. You can also choose to review both sides.
- **FR-11.6** Validate with python-chess and reject malformed or illegal games with a clear error. Version 1 supports standard chess only (no Chess960 or other variants).
- **FR-11.7** Imported games are stored in `games` with `source` set to paste / file / lichess / chesscom. Re-importing the same game (same source ID or identical moves) reuses the existing analysis.

### 11.2 Engine analysis (local, free)
- **FR-11.8** Evaluate **every position** in the game (default **0.3 s per position**, configurable), in the background, with a progress bar and the option to cancel. The user's moves are highlighted, and the opponent's moves are graded too, so you can see blunders you failed to punish.
- **FR-11.9** **Recorded for each move:** eval before and after (cp or mate, from the mover's view), best move, top 3 engine lines, centipawn loss, and a classification of Best / Good / Inaccuracy / Mistake / Blunder. Thresholds are configurable and shared with the Coach: inaccuracy ≥ 50 cp, mistake ≥ 100 cp, blunder ≥ 200 cp or a mate swing. Positions already decided (beyond ±500 cp) aren't penalized.
- **FR-11.10** **Tagging:** every user mistake or blunder is classified as Missed or Allowed and tagged with the lichess-puzzler tagger (same as FR-10.11 and FR-10.12).
- **FR-11.11** **Summary per side:** counts of inaccuracies, mistakes and blunders; average centipawn loss; Lichess's accuracy % when the export provides it; a breakdown by phase (from Lichess's `division` data, or estimated by move number); and mistakes made with a low clock (when clock data exists).

### 11.3 Review screen
- **FR-11.12** Board plus move list with annotation symbols (?!, ?, ??), all clickable. An **eval graph** for the whole game; click to jump to a move.
- **FR-11.13** **Key moments:** the biggest eval swings on the user's side (default top 5). Each shows "Played X, better was Y" and the eval swing, plus the mistake-reason chips (§7.3).
- **FR-11.14** **At any move:** best-move arrow and the engine's top lines. At a mistake, also the **refutation** of the move you played, which you can step through.
- **FR-11.15** **Retry mode** ("learn from your mistakes"): from the position before each of your mistakes, you try to find a better move before the answer is shown. Any move within 30 cp of the best move (configurable) counts as found. Results feed local stats.
- **FR-11.16** **Save as puzzle:** any key moment can be saved to `custom_puzzles` (position, best line, tags) and drilled through the "My games" source (FR-3.15), including Spaced repetition. These puzzles never sync to Lichess.

### 11.4 AI explanations (optional)
- **FR-11.17** **Explain this move:** on demand, for a key moment or any move. Its grounded context: position, played move, best move and its line, refutation of the played move, eval swing, top engine lines, attack/defense facts, tags. Output, validation and board annotations work exactly like FR-8.3 to FR-8.5.
- **FR-11.18** **Explain my game:** one batched request covering the top N key moments (default 5, max 10), plus a short narrative (opening summary, turning point, recurring themes, 2–3 takeaways) and an optional recommended puzzle preset, validated as in FR-10.23.
- **FR-11.19** The context may include this game's **SAN move list only** (no headers, clocks or comments) for the narrative. Players are anonymized as "You" and "Opponent": no names, ratings, URLs or dates.
- **FR-11.20** Results are cached per (game, ply, provider, model) for single moves, and per (game, N, provider, model) for the narrative.
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

The build plan lives in **ROADMAP.md**, as versions v0.1 → v1.0, each a stop-and-test checkpoint. Code structure is in **ARCHITECTURE.md**. How the earlier milestones map onto the versions:

| Earlier milestone | Versions |
|---|---|
| M1 Data + board | v0.1 (MVP mixer), v0.2 (mixer complete) |
| M2 Lichess | v0.3 |
| M3 Stockfish + stuck ladder | v0.2 (hint/answer from the dataset), v0.4 (engine) |
| M5 Modes + stats + reasons | v0.5, v0.6 |
| M4 LLM Explain + guardrails | v0.7 (moved after the modes; guardrails still ship before the first LLM call) |
| M6 Game Review | v0.8 (engine), v0.9 (AI) |
| M7 Coach + fix tracking | v0.10 (Coach), v1.0 (checkpoints, release) |

---

## 15. Licensing

The project is open source under **AGPL-3.0-or-later** from the first commit (`LICENSE` in the repo root).
- **Why AGPL:** chessground is GPL-3.0 and the lichess-puzzler tagger (v0.10) is AGPL-3.0, so the combined work must be AGPL. Starting there avoids relicensing at v0.10.
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
| lichess-puzzler: Lichess's open-source puzzle generator and tagger (`tagger/cook.py`, python-chess), AGPL-3.0 | https://github.com/ornicar/lichess-puzzler |
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

## 18. Opening trainer (v2.0)

Learn an opening line by line with grounded explanations, build your own repertoire (including your answers to the opponent's sidelines), then drill it. **The moves always come from a book, the engine or you, never from the LLM.** The LLM only explains moves that already exist and have been validated, exactly as in §9.2.

### 18.1 Where the lines come from
- **FR-12.1** **Opening book:** the Lichess `chess-openings` dataset (ECO code, name, PGN; about 3,500 named lines; CC0 public domain). It's bundled with the app or downloaded through `adapters/http.py` with a pinned hash, and imported into its own table. Every line is validated with python-chess at import. Lines are matched by **position (FEN)**, not move order, so transpositions are recognized.
- **FR-12.2** **Main lines of an opening:** the named sub-lines under the chosen opening in the book. You can also add popularity data from the **Lichess opening explorer** (masters and Lichess games, the most common replies with their frequencies). The explorer API needs a Lichess token (it returns 401 without one, checked 2026-11-01). It's used only when you're signed in (§8.1), with responses cached locally, and the trainer still works without it. The prefetch scope is configurable (FR-12.7a).
- **FR-12.3** **Engine:** Stockfish evaluates every position you study (the interactive engine, ARCHITECTURE §3 decision 12), and suggests replies to deviations (FR-12.8). All positions and move lists are validated before they're sent (FR-7.6).

### 18.2 Repertoire
- **FR-12.4** **Your repertoire** is a tree of positions per color (White and Black). Each move records its **source**: book / engine / you. You pick openings and lines to add, and can remove, reorder or mark a move as "main" or "sideline". Stored in `user.db` (new migration): `repertoire_nodes(id, color, parent_id, fen_before, move_uci, san, source, is_main, created_at)`, unique per (color, fen_before, move). A transposition reuses the same position.

### 18.3 Learn mode (walks you through lines)
- **FR-12.5** **Overview first:** opening a line starts with an overview of the opening: its key ideas, typical plans for both sides, pawn structures, common traps and what to aim for. It's generated by the LLM from grounded context (the opening name, ECO code, the line's SAN moves and the engine evaluations of its key positions). It's shown as escaped text (FR-8.7), and every square or move it mentions is validated before it's drawn (FR-8.4/8.5).
- **FR-12.6** **Step through the line:** the board walks the moves one at a time, with forward and back controls. Each move has an **Explain** button: why this move, what it prepares, and what happens if you don't play it, grounded in the engine's top lines for that position. Without an LLM configured, the step-through still works with engine evals and lines only.
- **FR-12.7** **Store everything, ask once:** overviews and move explanations are saved in `opening_notes` in `user.db`, keyed by position (FEN), move, kind (overview / move), provider, model and prompt version. They're reused across lines and transpositions, and the LLM is never asked twice for the same thing.
  - **Prefetch when you start an opening:** the trainer offers to fetch the overview and every move explanation for its main lines in one go. Requests are batched one line per request to keep cost down. It shows the pre-run estimate with **Confirm**, and the per-run cap, monthly budget and hard `max_tokens` all apply (§9.3). Already-stored items are skipped and not charged.
  - **FR-12.7a** **Prefetch scope (configurable, with suggested presets):**

    | Preset | Sub-lines | Moves per line | Use |
    |---|---|---|---|
    | **Light** | main line + 1 | 8 | a quick look, lowest cost |
    | **Standard** (default) | main line + 3 | 12 | the usual choice |
    | **Deep** | main line + 6 | 16 | serious study of one opening |
    | **Custom** | 0–10 | 4–20 | your own numbers |

    The global default is in the opening-trainer settings, and you can change it for each prefetch in the prefetch dialog.
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
  - Engine results are cached by position and depth, so revisiting a branch costs nothing.

### 18.4 Practice mode (quizzes you on your lines)
- **FR-12.9** **Drill your repertoire:** the app plays the opponent's moves from your repertoire, picking among the stored replies (weighted toward main lines, and by explorer popularity when it's available). You play your side.
  - **Correct:** any move stored as yours at that position, or one within the engine tolerance if you allow it in settings (off by default, because the point is to learn *your* line).
  - **Wrong:** shows the correct move, its stored explanation and the engine's view of your move (the refutation, using the same tools as Game Review FR-11.14). Any help before the line ends is a loss (§7.1).
  - Mistake reasons (§7.3) work here too.
- **FR-12.10** **Spaced repetition per position:** each of your decision points has its own Leitner box (same schedule as FR-4.6). Practice shows positions that are due first, and **New lines** introduces unseen branches a few at a time. Sessions can be limited to one opening, one color or one branch.
- **FR-12.11** **Stats:** per opening and per line, the accuracy, due count and weakest positions. All local, never synced to Lichess, and no effect on any rating.

### 18.5 Privacy and cost
- **FR-12.12** The LLM receives only opening data: names, ECO codes, SAN moves of book or repertoire lines, engine evals and lines. It never receives anything about you or your games. Explorer requests send positions to Lichess with your token, to the documented API only, and appear in the User Guide's privacy section. Prefetch estimates reuse the §9.3 machinery. A typical opening (overview plus 4 lines of about 12 moves) is roughly 20–30k input tokens and 8–12k output tokens in total. The v2.0 plan replaces this with figures from the `llm_prices` table, never hard-coded.
