# Architecture: WeakSquare Chess Trainer

The structure is designed for the **finished app** (REQUIREMENTS.md), but each version only builds what it needs (ROADMAP.md).

**Rule of thumb:** create the *interface* when a concept first appears, implement only what that version needs, and never write placeholder code for future features.

---

## 1. Layers and the dependency rule

```
web/ (React + TS)  ──calls──▶  bridge/  ──▶  services/  ──▶  core/      (pure logic, no I/O)
                                                   └────────▶  adapters/  (all I/O)
```

| Layer | Owns | May import | Must never |
|---|---|---|---|
| `web/` | Views, components, UI state | Its own `api.ts` only | Touch the network, files or secrets |
| `bridge/` | The JS ↔ Python API (pywebview `js_api`), input validation, DTOs, push events | `services`, `bridge.dto` | Contain business logic |
| `services/` | Use cases and orchestration (start session, record attempt, sync, analyze game, run checkpoint) | `core`, adapter **interfaces** | Talk to SQLite, HTTP or processes directly |
| `core/` | Domain rules: FilterSpec, puzzle semantics, scoring, angle rule, modes, SRS, tags, weakness statuses | Python stdlib, `python-chess` | Do any I/O (files, network, DB, time.sleep, subprocess) |
| `adapters/` | SQLite repositories, Lichess / chess.com / LLM clients, Stockfish, secret store, shared HTTP client | Third-party libraries | Contain business rules |

**Why it matters:** the rules that decide ratings and fix status live in `core/` and are tested in milliseconds with no fixtures. Adapters can be swapped for fakes in tests. The UI can be developed and tested against a mock API.

**Composition root:** `app.py` is the **only** place concrete adapters are constructed and wired into services. Nothing else news up a client.

---

## 2. Repository layout

```
weaksquare-chess-trainer/
├─ pyproject.toml  uv.lock     # deps (locked with uv), ruff, pytest, mypy config
├─ LICENSE                     # AGPL-3.0-or-later
├─ .github/workflows/ci.yml    # static checks + tests on the fixture, Windows runner (v0.1)
├─ plans/                      # the approved plan for each version, ticked off as work lands
├─ README.md  REQUIREMENTS.md  ARCHITECTURE.md  ROADMAP.md  CLAUDE.md  CHANGELOG.md
├─ docs/                      # USER_GUIDE.md, DEVELOPER_GUIDE.md, img/ (generated screenshots)
├─ assets/icon/               # weaksquare.svg (source), weaksquare.ico (built by scripts/make_icon.py), CREDITS.md
├─ .claude/  .gitleaks.toml  .pre-commit-config.yaml  .gitignore
├─ src/weaksquare/
│  ├─ __main__.py              # python -m weaksquare
│  ├─ app.py                   # composition root + pywebview window
│  ├─ config.py                # paths (platformdirs → %LOCALAPPDATA%\WeakSquare), defaults
│  ├─ engine_manifest.json     # pinned Stockfish release: tag, asset, URL, SHA-256   (v0.4)
│  ├─ bridge/
│  │  ├─ api.py                # class Api: methods exposed to JS (thin)
│  │  ├─ errors.py             # @bridge_call: argument checks, logging, {code, message, retryable}
│  │  ├─ dto.py                # dataclasses for everything crossing to JS
│  │  └─ events.py             # Python → JS push (job progress, sync status)
│  ├─ core/
│  │  ├─ clock.py              # Clock protocol + FixedClock (the real clock is an adapter)
│  │  ├─ errors.py             # AppError and friends: code + user-facing message
│  │  ├─ chess_rules.py        # FEN/UCI helpers, player color, length, mate-in-1 acceptance
│  │  ├─ puzzle.py             # Puzzle, PuzzleRef(source, id)  (PuzzleSource protocol: services/session.py)
│  │  ├─ csv_rows.py           # puzzle CSV rows by header name
│  │  ├─ themes.py             # theme catalog: names and picker groups
│  │  ├─ checksums.py          # sha256sums.txt parsing
│  │  ├─ engine.py             # EngineClient protocol, manifest, zip safety, FEN checks, "for you" evals (v0.4)
│  │  ├─ filters.py            # FilterSpec (+ JSON schema, validation)
│  │  ├─ queue.py              # ordering, ratios, queue building (pure; takes candidate ids)
│  │  ├─ move_sounds.py        # which sound a move makes (v0.2)
│  │  ├─ stats.py              # Stats grouping: theme, length, rating band (v0.2)
│  │  ├─ db_update.py          # newer-export rules, puzzle-count parsing (v0.2)
│  │  ├─ scoring.py            # angle selection (v0.3), the result panel's rating status
│  │  ├─ oauth.py              # PKCE challenge, authorize URL, callback check (v0.3)
│  │  ├─ lichess.py            # LichessClient protocol, result types, response parsers (v0.3)
│  │  ├─ modes/                # TrainingMode protocol + one module per mode
│  │  ├─ reasons.py            # mistake-reason suggestion rules      (v0.6)
│  │  ├─ srs.py                # Leitner scheduling                   (v0.5)
│  │  ├─ ladder.py             # depth-ladder levels from the attempts log (v0.5)
│  │  ├─ tags.py               # habit tags from attack maps          (v0.10)
│  │  └─ weakness.py           # metrics + status rules               (v1.0)
│  ├─ services/                # one module per use-case area; created when first needed
│  │                           #   v0.1: puzzle_db.py (import and upgrade jobs), mixer.py (catalogs, counts), session.py
│  │                           #   v0.2: presets.py, stats.py, ui_settings.py, db_update.py (update check job)
│  │                           #   v0.3: account.py (sign-in, launch check, sign-out), sync.py (the queue),
│  │                           #         lichess_history.py (history import)
│  │                           #   v0.4: engine_install.py (the Stockfish installer), engine.py (EngineService)
│  ├─ adapters/
│  │  ├─ db/
│  │  │  ├─ connection.py      # opens puzzles.db + user.db, ATTACH, pragmas
│  │  │  ├─ migrate.py         # numbered migrations, backup first, newer-schema refusal
│  │  │  ├─ puzzles_indexes.sql  # built after each puzzle import's bulk load
│  │  │  ├─ migrations/puzzles/0001_init.sql …
│  │  │  ├─ migrations/user/0001_init.sql …
│  │  │  └─ repos/             # one repository per aggregate
│  │  ├─ http.py               # shared httpx client: UA, timeouts, retry/backoff, redaction
│  │  ├─ secret_store.py       # the ONLY module that imports keyring
│  │  ├─ system_clock.py       # SystemClock + the seeded Random, built only in app.py
│  │  ├─ logging_setup.py      # rotating logs, redaction, crash hooks
│  │  ├─ instance_lock.py      # single-instance lock + bring the window forward
│  │  ├─ desktop.py            # open a folder, pick a file, fatal-error box
│  │  ├─ stockfish.py          # StockfishEngine (python-chess UCI) + probe_engine  (v0.4)
│  │  ├─ lichess.py            # LichessHttp (v0.3)   chesscom.py (v0.8)
│  │  ├─ oauth_loopback.py     # one-shot 127.0.0.1 listener for the OAuth redirect (v0.3)
│  │  ├─ scheduler.py          # run-later timer for sync retries and reconnect checks (v0.3)
│  │  └─ llm/                  # LLMProvider protocol, anthropic.py, openai.py (v0.7)
│  └─ jobs/runner.py           # background jobs: queue, progress, cancel
├─ web/
│  ├─ index.html  vite.config.ts  package.json  package-lock.json
│  ├─ public/sounds/           # bundled sound sets + CREDITS.md (v0.2)
│  └─ src/
│     ├─ api/                  # ApiClient interface + pywebviewClient + mockClient
│     ├─ components/           # Board (chessground wrapper), ThemePicker, FilterControls, SessionBar, …
│     ├─ views/                # Startup, Trainer, Settings, Stats, Library, Review, Coach, Progress
│     ├─ sound/                # the move-sound player (v0.2); which sound comes from core/move_sounds.py
│     └─ state/                # small hooks and defaults (useJob, defaultFilters, shortcuts, colorScheme)
├─ tests/
│  ├─ unit/                    # core/ — fast, no I/O
│  ├─ integration/             # services + real SQLite (tmp) + fake clients
│  ├─ e2e/                     # Playwright against web/ with mockClient
│  ├─ smoke/                   # the real app over CDP (harness in conftest.py)
│  ├─ fulldb/                  # opt-in timings against the full puzzle DB
│  ├─ live/                    # opt-in, Adam only: Lichess with the weaksquare-test token (v0.3)
│  ├─ engine/                  # opt-in: the real Stockfish (-m engine) (v0.4)
│  ├─ fakes/                   # fake Lichess client, listener, browser, scheduler (v0.3);
│  │                           #   fake engine + a fake UCI engine subprocess (v0.4)
│  └─ fixtures/                # tiny puzzle CSV sample, scrubbed HTTP recordings (http/lichess_db/);
│                              #   tools/ holds the dev-only generator and recorder scripts
└─ scripts/                    # setup.py (one-command setup), fetch_puzzle_db.py, fetch_stockfish.py
                               #   (thin CLIs over services, download + hash check), check_docs.py,
                               #   gen_types.py (bridge/dto.py → web/src/api/types.ts), make_icon.py (v0.2),
                               #   set_test_token.py (v0.3; Adam runs it, never Claude Code)
```

`services/` and later `adapters/` modules are created **in the version that first needs them**. The tree shows the end state.

---

## 3. Decisions locked in at v0.1 (expensive to change later)

1. **Two SQLite files.** `puzzles.db` holds the Lichess import (~1 GB, rebuildable, replaced on re-import). `user.db` holds everything you create (attempts, presets, settings, games, analysis, weaknesses). They're joined with `ATTACH` when a query needs both. Re-importing puzzles can never touch user data (FR-2.3), and backups are small.
2. **Numbered SQL migrations from day one**, per database, with a `schema_version` table. Every later feature adds a migration. Tables are never edited by hand.
3. **`PuzzleRef(source, id)`** everywhere, never a bare ID: `lichess:00008` vs `my:42` (custom puzzles in v0.8). Attempts, SRS and stats key on it.
4. **Attempts are an append-only event log.** Each attempt records mode, result, help, timing, rated flag, angle and sync status. Stats, sync, SRS, the Coach and fix tracking all *read* this log, and no feature keeps its own copy. New fields arrive as nullable columns via migrations.
5. **`FilterSpec` is one serializable object** (JSON), shared by the filter panel, presets, Coach suggestions, the angle rule and the queue. Its full schema (§5 of REQUIREMENTS.md) is defined in v0.1, even though the UI exposes only part of it at first.
6. **`TrainingMode` protocol:** `start(puzzle) → state`, `on_move(state, uci) → (state, feedback)`, `on_help(state, kind)`, `result(state) → AttemptResult`. Standard mode is the first implementation, and the other five plug in without changing the trainer view.
7. **Long work = jobs.** DB import, sync, game analysis and checkpoints all run through `jobs/runner.py`, which handles job IDs, progress events and cancellation. The UI never blocks on a bridge call that takes more than ~200 ms.
8. **The bridge contract is typed and versioned.** `bridge/dto.py` and `web/src/api/types.ts` must match, and a test compares them. The front end talks only to the `ApiClient` interface, which has two implementations: `pywebviewClient` (real) and `mockClient` (UI development and Playwright).
9. **One HTTP client** (`adapters/http.py`) for every external call: User-Agent, timeouts, retry/backoff (including chess.com's serial rule), and header redaction in logs.
10. **Secrets:** only `adapters/secret_store.py` touches keyring (SR-7). Services ask it for a token per request, and tokens never go into DTOs.
11. **Front end:** React + TypeScript + Vite, with **Mantine** as the component library (grouped multi-select, range slider, tables, modals and notifications out of the box). chessground is wrapped in a single `Board` component. It's the largest ecosystem, the most reliable stack for AI-written code, and Mantine covers the filter-heavy UI without hand-building controls. In production pywebview serves the built `web/dist`. In development it points at the Vite dev server.
12. **Threading model.** pywebview runs every bridge call on its own thread, and jobs run on worker threads.
    - **SQLite:** one connection per thread, opened lazily from `adapters/db/connection.py`, in WAL mode with a 5 s busy timeout, with `puzzles.db` attached on each connection. Connection objects are never shared between threads.
    - **Stockfish:** `EngineClient` owns two engine processes. The *interactive* engine serves the trainer, Explain and the Review screen; the *background* engine (v0.8) serves the analysis queue and checkpoints. Interactive requests never wait behind background work.
13. **Bridge surface.** The `Api` class keeps every dependency in underscore attributes, because pywebview exposes all public methods and nested objects to JavaScript. Every public method is wrapped by one `@bridge_call` decorator that validates arguments, logs, and turns exceptions into the `{code, message, retryable}` error object (NFR-5). A test asserts the exposed method names equal an explicit allowlist.
14. **No browser storage.** pywebview runs WebView2 in private mode by default, which wipes cookies and local storage every session. The front end never uses localStorage, sessionStorage, IndexedDB or cookies. Persistent UI state goes through the bridge into `settings`.
15. **Injected clock and randomness.** `app.py` creates one `Clock` and one seeded `random.Random` and passes them to services. `core/` functions take `now` or `rng` as parameters. Nothing calls `datetime.now()`, `time.time()` or the global `random` directly, so tests are deterministic.
16. **Data folder and migration safety.** All paths come from `config.py`, which resolves the data folder (NFR-2). Migrations back up `user.db` first and refuse a newer schema (NFR-3). A lock file there enforces a single instance (NFR-1).
17. **Puzzle import builds a new file and swaps it in** (FR-2.3). Everything that joins attempts to puzzles uses left joins and tolerates missing puzzles (FR-2.4).

---

## 4. Key interfaces (Python `Protocol`s, in the version that first needs them)

| Interface | Implementations | First version |
|---|---|---|
| `PuzzleSource` | `LichessDbSource` → `CustomPuzzleSource` | v0.1 → v0.8 |
| `TrainingMode` | `Standard` (also serves Spaced repetition) → `CommitLine` → `NameIdea` (Standard's rules plus tags), `DangerSpotting` (its own call step, `on_call`). Depth ladder is a queue order (`core/ladder.py`), not a mode (v0.5 planning) | v0.1 → v0.5 → v0.6 |
| `JobRunner` | thread-pool runner | v0.1 |
| `SecretStore` | `KeyringSecretStore`, `FakeSecretStore` (tests) | v0.3 |
| `LichessClient` | httpx implementation, fake | v0.3 |
| `EngineClient` | `StockfishEngine`, fake | v0.4 |
| `LLMProvider` | `AnthropicProvider`, `OpenAIProvider`, fake | v0.7 |
| `GameSource` | `LichessGames`, `ChesscomGames`, `PgnImport` | v0.8 |
| `Tagger` | `LichessPuzzlerTagger` + `HabitTagger` | v0.10 |

---

## 5. Data flow examples

**Solve a puzzle (v0.1):** Trainer view → `api.next_puzzle(session_id)` → `SessionService` builds or reads the queue from `FilterSpec` (candidate IDs from `PuzzleRepo`, ordered by `core.queue`) → returns `PuzzleDTO` (FEN after the opponent's move, player color, no themes) → the user moves → `api.submit_move` → `TrainingMode.on_move` checks it against the solution (`core.chess_rules`, including mate-in-1) → on finish, `AttemptService` appends the attempt → the result DTO (now with themes) goes back to the view.

**Sync (v0.3):** finished attempt → `sync_status = pending` → `SyncService` job batches fewer than 100 at a time → `LichessClient.solve_batch(angle, …)` → updates `sync_status` and `rating_diff`.

**Game checkpoint (v1.0):** library sync job → 10 new eligible games → `AnalysisService` (engine, tagger) → `CoachService` aggregates the rolling window → `core.weakness` updates statuses → a new Suggested `FilterSpec` → push event → banner in the UI.

---

## 6. Testing strategy

| Level | What | Tools | Runs |
|---|---|---|---|
| Static | `ruff`, `mypy` (non-strict), `tsc --noEmit`, ESLint | each tool | every change; CI |
| Unit | everything in `core/` | pytest | every change (hook) |
| Integration | services + temp SQLite + fakes (engine, Lichess, LLM, secret store) | pytest | every change |
| Contract | `dto.py` ↔ `types.ts` match; scrubbed fixtures contain no secrets | pytest | every change |
| E2E UI | user flows against `mockClient` in headless Chromium, with screenshots | Playwright | each version checkpoint |
| Real-app smoke | the actual pywebview window: launched with the WebView2 CDP port on 127.0.0.1 (test harness only, SR-16), driven by Playwright `connect_over_cdp` | Playwright + pytest | each version checkpoint (QA) |
| Full DB (opt-in) | filter counts and queue building against the full imported puzzle DB, with time limits | `pytest -m fulldb` (skipped when the DB isn't there) | QA, each version checkpoint |
| CI | static checks, unit, integration and contract tests on the small fixture, `check_docs.py`; not the real-app smoke, full-DB or live tests | GitHub Actions, `windows-latest` | every push and pull request |
| Live (opt-in) | Adam's Lichess account via the separate test token (`rated:false`, max 3 solves), real Stockfish, a tiny real LLM call within the budget cap | `pytest -m live` | manually, at checkpoints |
| Docs | `check_docs.py`: changelog and guides updated with the code, links and images resolve, no overdue `TODO(v0.x)`; user-guide screenshots regenerated from the mock client with fixed data | `python scripts/check_docs.py`, Playwright | self-check and QA, each version |
| Manual | the checklist for that version in ROADMAP.md | Adam | each version checkpoint |

---

## 7. Decision log

Decisions made or changed **after** the locked decisions in §3, newest first. Add an entry in the same commit as the change, whenever a choice would be expensive to reverse or would surprise someone reading the code later: a new dependency, a schema shape, a protocol change, a workaround. If the decision changes behavior, update REQUIREMENTS.md in the same commit too.

Entry format:

```
### YYYY-MM-DD, v0.x: <decision in one line>
- Context: why a decision was needed
- Decision: what was chosen
- Alternatives: what was rejected, and why
- Consequences: what this makes easier or harder
```

### 2026-11-03, v0.6: Name the idea, Danger spotting and mistake reasons: modes, rules and storage
- Context: FR-4.3, FR-4.4 and §7.3 (FR-5.6–5.10), with Adam's v0.6 planning decisions.
- Decision:
  - **Storage** (user.db `0005_reasons_modes.sql`, nullable columns only): `attempts.idea_tags` (JSON), `idea_found`, `idea_total`, `idea_extra`, `danger_candidate`, `danger_safe`, `danger_call`, plus the `mistake_reasons` table from REQUIREMENTS §4. Reasons are append-only too: choosing another chip adds a row and the latest row per `(source, ref_id)` counts, so the attempts log itself is never updated for a reason.
  - **Name the idea** (`core/modes/name_idea.py`): `NameIdeaMode` subclasses `StandardMode` (its state adds the tags). `set_tags` must come before the first move. `grade_tags` compares your tags with `core.themes.motif_themes` (the Motifs, Advanced, Mate patterns and Special moves groups), whatever slot they're in. `IDEA_SETUP` / `IDEA_PAYOFF` only split the pickers.
  - **Danger spotting** (`core/modes/danger.py`): its own state machine, `on_call(state, call)` then, after a correct Unsafe on the real blunder, one `on_move` for the refutation's first move. `safe_candidates` is pure over `ScoredMove`s (mover's side), so the 50 cp rule is unit-tested without an engine. Mate scores map to large values, and a mate against the mover is never safe. `wants_safe` keeps an "owed" safe slot when a puzzle had no safe move.
  - **Reasons** (`core/reasons.py`): the reason set in FR-5.6 order (keys 1–6), and `suggest(ReasonContext)` with the FR-5.9 rules in a fixed order (rushed, miscalculated, missedResource, unknownPattern). `StandardState` gained `position_ms` / `decisive_ms` so "rushed" measures the deciding move's own think time.
- Alternatives: putting a `reason` column on `attempts` and updating it (breaks decision 4's append-only log); grading idea tags by slot (Lichess has no role data to grade against); asking Stockfish for every Danger move list (only the safe slot needs the engine).
- Consequences: Danger spotting and Name the idea plug into `SessionService`'s registry; Danger adds a call step to the trainer view, like Commit's Submit.

### 2026-11-03, after v0.5: The board re-measures itself on every press
- Context: Adam, after signing off v0.5: a move only registered when he clicked the middle of a square. Chessground caches the board's screen position and re-measures only on a window resize, a scroll, or a change in the board's own size (its ResizeObserver). Content above the board (a notice, the session bar wrapping, the dev banner, the filters panel in a narrow window) can move the board without any of those, so clicks were mapped with the old position, off by up to the shift.
- Decision: `components/Board.tsx`, the only chessground wrapper, clears chessground's cached bounds (`state.dom.bounds.clear()`) in a capture-phase `mousedown`/`touchstart` listener on its element, so chessground measures again just before it handles each press.
- Alternatives: dispatching `chessground.resize` or calling `redrawAll()` on layout changes (every component that can move the board would have to know about it, and `redrawAll` rebuilds the DOM); a ResizeObserver on ancestors (sees size, not position).
- Consequences: one `getBoundingClientRect()` per press, which costs nothing noticeable. `tests/e2e/test_board_clicks.py` clicks near square corners, including after the board has been pushed down.

### 2026-11-02, v0.5: QA fixes (v0.5-B1 to B9)
- Context: `qa/QA-v0.5.md` rounds 1 and 2 (six minor bugs, then B7, a major slowdown caused by the B2 fix, and two minor test-tooling flakes).
- Decision:
  - **B2:** `core.ladder.status` takes the levels that have puzzles (`available`). Empty levels are skipped going up, the last open level is the top (`LadderStatus.top` is now a field), and a recorded level that has emptied falls back to the nearest open level above, else below, with a fresh window. REQUIREMENTS FR-4.5 says so.
  - **B3:** the hidden-length entry cap is a constant 60 plies, so reaching it says nothing about the solution.
  - **B1:** a mode switch saves the mode only after its new session starts; otherwise the running session and mode stay and the reason shows.
  - **B4/B5/B6:** no calculation badge without replies; the already-played badge wraps and says "Already played: rating unaffected"; Show move count says "From the next session" in both states.
  - **B7:** the first B2 fix counted every level, which took a depth-ladder count to about 0.9 s on the full DB. `SessionService.ladder_preview` now builds only the `available` list the decision needs. That's the count at the level you'd play (needed for the display anyway) plus whether anything is above it: in one scan with SUMs when themes are chosen (`count_level_and_above`), or a count plus a `LIMIT` existence check (`has_puzzles`) with All themes. The exact next open level (`levels_with_puzzles`) is looked up only when the window says you move up. After an attempt with no move up, the session reuses the levels it found at the start and runs no puzzle query. Full DB: 185–280 ms per preview, against the 500 ms target (`tests/fulldb/test_perf_v05.py`).
  - **B8:** the docs screenshot spec ticks a theme in the picker it opened (by its `aria-controls` id) and waits for it to close.
  - **B9:** `cancel_sign_in` also cancels the sign-in job, and the job checks for that once its listener is up, so a Cancel pressed just after Sign in isn't lost.
- Alternatives (B2): letting the level drop to a level with puzzles (contradicts "never drops"); refusing a theme set that can't fill every level (most single-motif sets can't).
- Consequences: an empty level costs a scan of the levels above it, inside the same query when themes are chosen. With All themes every level has puzzles, so the existence check returns at once.

### 2026-11-02, v0.5: Front end for the modes and the collapsible filters panel
- Context: §6's Modes control, Commit the line's entry on the board, and FR-1.14 (Adam, v0.5 planning).
- Decision:
  - The Modes control and Show move count live in `MixerView`; the modes list is `web/src/state/modes.ts`. In Spaced repetition the filters sit in a disabled `<fieldset>` (greyed, unreachable by keyboard), with the due line at the top; the queue size and Rated stay live.
  - Commit entry (`TrainerView` + `components/CommitLine.tsx`) keeps the entered line in React state and checks legality with chess.js; the board is movable for both colors. Entered moves play sounds from `entrySound`, which mirrors `core/move_sounds.py`'s priority locally, because the moves only reach the backend at Submit (a bridge call per entered move just for its sound wasn't worth it). The graded line comes back from `submit_line`.
  - Hide filters: `App` keeps `MixerView` mounted in a `display: none` grid column (so its state, counts and catalogs survive) and shows `FiltersStrip` across the top; the trainer column takes the full width and `Board` gets a larger `maxWidth` (`min(760px, 100vh − 240px)`) with the side panel centred beside it. The state is `ui.filters_collapsed` in `user.db`. **F** toggles it.
  - The mock client implements every new method with the backend's rules (Commit grading, the ladder by theme-set key, SRS due puzzles until reviewed), with `?mode=`, `?srs=none` and `?dev=1` scenarios.
- Alternatives: a vertical strip beside the board (too narrow for a readable summary); unmounting the panel while hidden (it would refetch everything and lose unsaved input).
- Consequences: the trainer has a Commit branch; a later move-by-move mode needs none.

### 2026-11-02, v0.5: Commit the line has its own entry point instead of `on_move`
- Context: FR-4.2 grades a whole line at once; decision 6 assumed every mode is played move by move through `on_move`.
- Decision: `CommitLineMode` (`core/modes/commit_line.py`) keeps `start`, `start_practice`, `on_help` and `give_up`, refuses `on_move` with `ConflictError`, and adds `on_submit(state, line)`. Grading is pure (`grade()`): your moves are compared with the solution's by index; a mating alternative (§4.2) is accepted only while every earlier move matched exactly, so the position is real, and it ends the line there. `first_wrong` (for Stockfish's refutation) is set only under the same condition. Calculation accuracy is stored on the attempt (`replies_correct`, `replies_total`, migration 0004). The front end checks legality only (chess.js) and the backend re-checks the line with python-chess. Bridge: `submit_line`; `PuzzleView.max_plies` (a sanity cap: 2× the solution + 10, at most 60) and `solution_plies` (only with Show move count, so the length never reaches the UI when it's hidden). Show move count makes `angle_for(..., length_known=True)` report the length theme when the themes are All (§8.3).
- Alternatives: feeding the line through `on_move` one ply at a time (every reply would need "no validation" special cases in Standard's state machine); grading replies only up to the first wrong one (Adam's FR-4.2 scores predicted replies separately, so they're graded by index).
- Consequences: the trainer view has a Commit branch, contrary to decision 6's "without changing the trainer view". Modes that are played move by move still plug in without UI changes.

### 2026-11-02, v0.5: Spaced repetition and the depth ladder are worked out from the attempts log
- Context: decision 4 says no feature keeps its own copy of the attempts. Adam chose that **every** miss, past ones included, enters the Leitner boxes, and that the depth ladder (now an **order**, not a mode) keeps its level per theme set and never drops.
- Decision:
  - **SRS** (`core/srs.py`): `schedule()` replays one puzzle's attempts (a loss anywhere → box 1; a win in `spaced_repetition` mode → up a box; a win from the last box → graduated). `AttemptsRepo.srs_rows()` reads every attempt of each Lichess puzzle with a loss, using `attempts_puzzle_win`. Due dates are local calendar days (`Clock.local_date`, new in the protocol), so an evening miss is due the next morning. An SRS session ignores the filters except the queue size, serves due puzzles most overdue first, holds puzzle **IDs** (looked up as served, so a re-import can't point it at another puzzle), never refills, and reports angle `mix`. It plays by `StandardMode`'s rules; only the recorded mode differs.
  - **Ladder** (`core/ladder.py`): `ladder_key(spec)` = sorted themes + match mode (only with 2+ themes) + excluded themes. Attempts in a ladder session store `ladder_key` and `ladder_level` (migration 0004, indexed). The current level = the highest level recorded for the key, moved up one when the last *window* attempts at that level reach the *threshold*. The session draws from `spec.at_ladder_level(level)` (lengths = the level, random order), so the existing angle rule reports the matched theme or the length theme. On a level-up the queue is dropped and refilled from the new level. Ratios can't be combined with it (`FilterSpec.validate`).
  - Settings go through `UiSettingsService`, which also implements the session's `TrainingPrefs` protocol.
- Alternatives: an `srs_cards` table or a `ladder` table updated on every attempt (a second copy of the log, which could drift, and couldn't include misses from before v0.5 without a backfill).
- Consequences: changing the box intervals or the ladder settings applies to the whole history at once. Both read a few thousand rows at most per call; the full-DB tests time them.

### 2026-11-02, v0.5: The training mode is per session; fast-forward time is a dev-only clock
- Context: the Modes control (§6), Adam's "switching mode starts a new session", and his manual test needing Spaced-repetition misses to come due without waiting days.
- Decision: `start_session(spec, rated, mode, show_length)` records the mode on the session and every attempt; switching mode in the UI calls it again, exactly like Start (the old session is simply abandoned, with nothing recorded for an undecided puzzle, as before; pinned by a test). `adapters/system_clock.py` adds `OffsetClock`, a `SystemClock` whose `now()` is moved by whole days (`monotonic_ms` untouched). `app.py` builds it only for `--dev` runs and restores `debug.time_offset_days` at startup; the bridge's `set_time_offset` refuses outside `--dev`, and `set_setting` can't write that key.
- Alternatives: a fake-time setting in the real app (attempts recorded with future timestamps would stay in your real history forever); offsetting only the SRS "today" (reviews done while fast-forwarded would then be due again at once).
- Consequences: a dev data folder that has been fast-forwarded holds attempts with future timestamps; delete it to start clean.

### 2026-11-02, v0.4: Try again is a practice run that can't record (FR-5.12)
- Context: Adam's manual test: after Show answer and the analysis board he wanted to retry the puzzle. Letting Reset clear the result was rejected, because the first result may already be on Lichess and stats must agree with it.
- Decision: `StandardMode.start_practice` builds a fresh state for the same puzzle with `practice = True` and a placeholder `attempt`, so the mode never decides again (a wrong move no longer decides when an attempt exists; `give_up` returns nothing). `SessionService.retry` (only once the puzzle is finished) swaps it in, keeping the engine cache; `submit_move`, `request_help` and `next_puzzle` also skip recording for practice states (defence in depth). FR-7.3 still applies: the engine is refused until the practice run is finished. Bridge: `retry_puzzle`. The UI keeps the first result's panel and shows a *Practice: not scored* badge.
- Alternatives: Reset un-records the attempt (rewrites history that Lichess may already have); a separate practice queue (that's Spaced repetition, v0.5).
- Consequences: practice runs leave no trace in `attempts`, Stats or sync. v0.5's modes can reuse `start_practice` if they need an unscored replay.

### 2026-11-02, v0.4: QA fixes to the engine (v0.4-B1, B2, B5, B6, B8)
- Context: `qa/QA-v0.4.md` round 1.
- Decision:
  - **B1, workaround for a python-chess 1.11.2 bug:** when a search is killed (our timeout), python-chess's `connection_lost` raises `InvalidStateError` before resolving the protocol's `returncode` future, so `SimpleEngine`'s background thread (not a daemon) waits forever and Python can't exit: the app kept `weaksquare.lock`, and `uv run pytest` never returned. `adapters/stockfish._close` now resolves that future a second after closing if nothing else has; the thread then ends normally. Remove it once python-chess fixes this upstream (a test runs the timeout in a child process and checks it exits).
  - **B5:** `close()` no longer waits for a search in progress (up to the think time; the lock file stayed held). It kills a busy process at once; that search fails with `engine_stopped`, which is quiet: no restart and no error log. `EngineService.close` doesn't take the engine lock either.
  - **B2:** Stockfish sometimes ends a pv after 2 plies. The refutation asks again from where the line stopped (at most twice) until it has 3 plies or the game is over (§7.2: 3–5).
  - **B8 (round 2):** closing while the engine was still starting (~0.35 s) left it running. `StockfishEngine._adopt` checks `_closed` both before and after storing a newly started process; `close()` sets `_closed` before reading the process, so one of them always stops it. A process killed mid-search can also surface as `concurrent.futures.CancelledError`, now handled like the other failures (quiet `engine_stopped` after close, otherwise a crash with one restart).
  - **B6:** the NFR-4 banner is written before `user.db` is open, so it can only describe the managed install. The engine actually in use (custom ones included) is logged right after start-up (`app.engine_log_line`).
- Alternatives: an own asyncio loop in a daemon thread instead of `SimpleEngine` (more code to replace one future); pinning a newer python-chess (none fixes it as of 1.11.2).
- Consequences: an upgrade of python-chess should re-run `tests/integration/test_qa_v04_engine.py` and drop the workaround if the thread exits without it.

### 2026-11-02, v0.4: The interactive engine, FR-7.3 in the backend, and evals "for you"
- Context: FR-7.1–7.7 and §7.2 step 2; ARCHITECTURE §3 decisions 7 and 12; Adam's v0.4 planning choices (evals from your side; a post-puzzle panel plus an analysis board).
- Decision:
  - **Shapes:** `core/engine.py` has the `EngineClient` protocol (`analyse(board, think_s, multipv)`, `configure`, `info`, `close`), the White-relative `EngineLine`, FEN and move-list validation, and `format_score`. `adapters/stockfish.py` (`StockfishEngine`) is the python-chess implementation; v0.8's background engine is a second instance, not new methods.
  - **Never hangs, survives crashes (FR-7.6):** one process, started lazily and kept until close; a lock serializes requests; python-chess's timeout (think time + 10 s) bounds each one. A crash, timeout or protocol error kills the process, starts one new one (a failing restart leaves it stopped; the next request tries once more) and fails that request with `engine_crashed` / `engine_timeout`. python-chess logs engine traffic at DEBUG on `chess.engine`; a logger filter keeps the `CRITICAL ERROR` lines (by pid) for the error log and stops the rest reaching the log file. The process gets `CREATE_NO_WINDOW`.
  - **`services/engine.py` (`EngineService`):** picks the binary (custom path, else the managed install), validates every position before the engine (and keeps only the legal prefix of each returned pv), owns the settings (`engine.think_s` 0.2–10 s, `engine.threads` 1–CPUs, `engine.hash_mb` 16–2048, `engine.custom_path` saved only after the probe passes, in a job), and runs the install job. Engine calls are **bridge calls the UI awaits** (about the think time, 1 s by default), not jobs: the UI shows a thinking state and never disables other controls. This refines decision 7 for short, bounded calls. **Latest request wins:** each caller key (a session's panel or analysis board) has a generation number; a queued request that's no longer the newest returns `superseded` without searching.
  - **FR-7.3 is enforced in `SessionService`:** `get_refutation` and `analyze` refuse (`conflict`) until the puzzle is *finished* (line complete or Show answer used). Lost-but-still-playing counts as in progress. Results are cached per puzzle by FEN.
  - **Refutation:** Standard mode keeps `first_wrong` (the FEN before it and the move); `HelpResult.refute` tells the UI to ask for it. It's the engine's line after that move, trimmed to 5 plies, with the eval.
  - **Evals "for you" (FR-7.2):** the score is flipped to the solver's side: "+3.2 for you", "−1.4 for you", "0.0 (level)", "You mate in 3", "You're mated in 2". Mate, stalemate and insufficient material are answered without the engine.
- Alternatives: running engine requests as jobs (needs a result channel and polling for a ~1 s call); hiding evals only in the UI (a bug or a hand-made bridge call could leak them); White-relative evals (Lichess's convention; Adam preferred "for you").
- Consequences: tests use `tests/fakes/engine.py` (in process) through `build_services(make_engine=…)`, and `tests/fakes/uci_engine.py` (a subprocess that exits on an invalid position like Stockfish 19) for the adapter, so CI needs no binary. `-m engine` runs the real Stockfish. Settings need no migration (the `settings` table).

### 2026-11-02, v0.4: The Stockfish installer and where the engine lives
- Context: FR-7.5. The binary is gitignored, so every copy installs it, and Adam chose (v0.4 planning) to keep it per data folder like everything else (NFR-2).
- Decision:
  - `engine_manifest.json` pins `sf_19` / `stockfish-windows-x86-64-universal.zip` with GitHub's published digest (`3c8bf1f9…b48a7`, read from the releases API and confirmed by downloading the asset) and `exe_member` (`stockfish/stockfish-windows-x86-64-universal.exe`, read from the real zip). It's keyed `windows-x86_64`; GitHub also publishes a `windows-arm64` build, left out until the v1.1 platform work.
  - `core/engine.py` holds the pure rules: manifest parsing, the platform key, and `check_zip_names`, which refuses the **whole** archive if any entry is absolute, has a drive letter or a `..` part.
  - `services/engine_install.py` (`EngineInstaller`) downloads through `http.py` into `downloads/`, hashes, vets the names, extracts only the exe into `engines/.sf_19.tmp-*`, runs the probe (`adapters/stockfish.probe_engine`: the UCI handshake, then a 0.2 s search from the start must return a legal move), writes `install.json` (tag, asset and exe SHA-256, `id name`, time from the Clock), and renames the folder to `engines/sf_19`. A `--force` reinstall moves the old folder aside and puts it back if the swap fails. The download and the temp folder are always deleted. "Already installed" means the marker matches the manifest and the exe still has its recorded hash.
  - `app.build_engine_installer` is the one constructor, shared by the app, `scripts/fetch_stockfish.py` and (through that script) `scripts/setup.py`.
  - Workaround: right after the self-test, Windows denied the rename for about 1.6 s (Defender scanning the fresh exe, or the probe process still exiting). `adapters/files.rename_with_retry` retries "access denied" for up to 10 s; it's injected, since services can't sleep (decision 15).
- Alternatives: one shared `engines` folder for dev and real runs (one 80 MB copy, but an exception to NFR-2); resuming a partial download (not worth it for 80 MB, and a leftover `.part` would break "leaves nothing behind").
- Consequences: dev runs need their own install (`fetch_stockfish.py --dev`). Upgrading Stockfish is a manifest edit plus an entry here. `.exe` and `engines/` stay gitignored.

### 2026-11-01, v0.3: `@mantine/charts` + `recharts` for the rating trend
- Context: FR-9.4 needs a line chart on Stats; Adam chose a library over a hand-written SVG at planning (more charts follow with the Coach and Progress pages).
- Decision: npm runtime dependencies **`@mantine/charts`** (MIT, the same 9.7.x as `@mantine/core`), **`recharts`** (MIT) and its peer **`react-is`** (MIT, the same version as React), all checked on npm. `components/RatingTrend.tsx` draws a single series: a 2px line with 4px dots, the crosshair tooltip, horizontal grid only, and no legend (the title names it). The per-session table is its table view. The line color is checked with the dataviz palette validator against each surface: teal-9 `#087f5b` in Light, teal-8 `#0ca678` in Dark. Points are only `attempts.rating_after`, the glicko rating Lichess returned.
- Alternatives: a hand-written SVG chart (no dependency, but no tooltip or axes for free).
- Consequences: the bundle grows by 115 kB gzipped (218 → 333 kB; it loads from disk, so start-up is barely affected). Recharts renders inline SVG with inline styles, which the CSP already allows for Mantine. `npm audit --omit=dev` reports nothing.

### 2026-11-01, v0.3: Lichess sign-in, the sync queue, the history import and the angle rule
- Context: FR-6.1–6.17, FR-1.6/1.7, and Adam's v0.3 planning decisions (REQUIREMENTS.md FR-3.9, 6.14, 6.16).
- Decision:
  - **Shapes:** `core/lichess.py` holds the `LichessClient` protocol, its result types and defensive parsers. `adapters/lichess.py` (`LichessHttp`) is the httpx client. `tests/fakes/lichess.py` is the fake, which loads its defaults from `tests/fixtures/http/lichess/`. `http.py` gains JSON, form, delete and ndjson calls. Each takes a per-request `token`, never a client default. It also gains `Unauthorized` (401) and `RateLimited` (429, not retried in the client).
  - **Sign-in:** `core/oauth.py` provides the PKCE challenge, the authorize URL and the callback check. The verifier and state come from `secrets.token_urlsafe`, never the seeded rng. `adapters/oauth_loopback.py` is a stdlib `http.server` on `127.0.0.1:0` that takes exactly one `/callback`; other paths get a 404 without consuming it. It shuts down after the callback, after 5 minutes or on cancel, and never logs the query. `AccountService` runs the sign-in as a job and checks a stored token at launch: a 401 means expired (the token is deleted), a network error means offline, with rechecks after 30 s, then up to 10 min. Sign-out revokes the token first; when Lichess can't be reached, *Remove from this PC anyway* is needed. Signing in again revokes the previous token. Retries go through an injected scheduler (`adapters/scheduler.py`).
  - **The queue is the attempts log** (decision 4). user.db `0003` adds nullable `rated`, `angle`, `sync_status`, `sync_account`, `already_played`, `rating_diff`, `rating_after` and `synced_at`, and marks every older attempt `local` (never synced). A solve is queued for the account that was signed in when you made it. A solve made while signed out goes to the next account that signs in. `SyncService` drains the queue in a single `lichess_sync` job, grouped by angle, at most 99 per request and one solution per puzzle per request, since Lichess answers per puzzle id. A batch is marked synced only on a 2xx. Ids Lichess didn't return are marked `skipped`, and any other refusal marks the batch `failed`. Network errors and 5xx back off from 30 s to 10 min, and a 429 waits at least 60 s or `Retry-After`. While a retry waits, new solves only join the queue and send nothing (QA v0.3-B5). A sign-in may cut a network backoff short, but nothing cuts a 429 wait. A 429 always starts its own full wait, and only the newest scheduled retry acts, so an older network-backoff timer can't end it early (v0.3-B8). A network failure while a retry is already pending still holds new solves until it fires (v0.3-B9). Batches are never resent inside the HTTP client (`retry=False`), and a response Lichess sent that can't be parsed counts as a refusal, not as offline (v0.3-B1, B4). A token obtained during a sign-in that then fails is revoked (v0.3-B3). The response's `glicko.rating` is stored as `rating_after` on the batch's last attempt and sent to the header. That's the only source of the rating besides `GET /api/account`.
  - **History:** `lichess_history(puzzle_id, played_at, win)` is a cache for the signed-in account. It's filled by the `lichess_history_import` job (`since` is saved only after a complete stream) and by every synced solve, and cleared when another account signs in.
  - **Exclude played on Lichess** (on by default; saved filters get it once, `SAVED_FILTERS_VERSION` 3) joins v0.2's subtraction: the count without the hiding filters, minus the matching IDs in `SOLVED_IDS UNION PLAYED_IDS`. Only my misses overrides it, as it overrides Exclude solved. Presets saved in v0.2 keep the `false` they were saved with: presets are never changed silently. On the full DB with 20,000 history IDs, the default count takes 363 ms.
  - **Angle** (`core/scoring.py`): `mix` only when themes, move count and ratios are all unset. Otherwise the selected theme the puzzle matched (motif-like groups, then phases/goals/origin, then lengths, and selection order within a tier), or the length theme when only the move count was narrowed.
- Alternatives: a separate `sync_queue` table (a second copy of the log); one request per solve (a ~200 solves/hour rate limit makes batching matter after a long offline session); keyring-backed tests (they would touch real credentials).
- Consequences: the response shapes are from the API spec until Adam's live run records real ones (`tests/fixtures/http/lichess/README.md` says which). If a real response differs, only the parsers change.

### 2026-11-01, v0.3: `keyring` and the secret store
- Context: FR-6.5 and SR-1/SR-7: the Lichess token lives only in Windows Credential Manager.
- Decision: Python runtime dependency **`keyring`** (MIT; checked on PyPI; on Windows it pulls in `pywin32-ctypes` and `jaraco.*`). `adapters/secret_store.py` is the only importer and provides the `SecretStore` protocol, `KeyringSecretStore` and `MemorySecretStore`. That last one is what tests use, and the default for scripts that need no secret. Each data folder has its own entry: `weaksquare` for the real folder, `weaksquare-dev` for the dev folder and `weaksquare-<hash of the path>` for any other `WEAKSQUARE_DATA_DIR` (so smoke-test launches start signed out and never call Lichess with a stored sign-in). The live-test token uses `weaksquare-test` (SR-13). Under pytest, `KeyringSecretStore` refuses anything but `weaksquare-test`. Secrets are at most 1,200 characters: Credential Manager holds 2,560 bytes and keyring writes UTF-16, which is still well over FR-6.7's 512. keyring errors are re-raised as `SecretStoreError` with the error type only. The log redaction also covers JSON `"access_token": "…"` fields.
- Alternatives: calling `CredWrite` through ctypes (more code, and v1.1's macOS/Linux port would need keyring's backends anyway).
- Consequences: any code running as your Windows user can read the token (SR-15, accepted). Sign-out revokes it on Lichess.

### 2026-11-01, v0.2: Fast counts with Exclude solved and ratios (found by the full-DB self-check)
- Context: with v0.2's defaults, the full-DB count took 4 s. `p.id NOT IN (solved ids)` needs `id`, which the covering index doesn't hold, so SQLite read every table row. A ratio mix also counted each group in its own scan, and its live match count ignored the groups' themes (counting the whole database).
- Decision: Exclude solved is counted by subtraction: the count without it (covering index), minus the solved puzzles that match (looked up through the unique `id` index). Sampling a small pool drops the solved keys the same way. A ratio mix is counted in one scan, `SELECT COUNT(*), SUM(<group 1>), …` with the groups' union in `WHERE` (`count_with_buckets`), and `count_buckets` returns the total and the groups in one bridge call.
- Alternatives: adding `id` to the covering index (a bigger index, and the per-row `NOT IN` check still costs).
- Consequences: the default count takes about 315 ms on the 6.16M export. A three-group ratio over the whole rating range takes about 550 ms, just over the 500 ms target; narrower filters are faster.

### 2026-11-01, v0.2: App icon, taskbar identity and the desktop shortcut
- Context: NFR-8a.
- Decision: `assets/icon/weaksquare.svg` is a 2×2 board in chessground's brown colors with the cburnett black queen (Colin M. L. Burnett, GPL-2.0-or-later), copied from chessground's CSS; credits are in `assets/icon/CREDITS.md`. `scripts/make_icon.py` renders it with Playwright's Chromium at 16–256 px and packs PNG entries into an `.ico` with `struct` (no new dependency); the build is deterministic, and `--check` (run by the e2e suite) compares it with the committed file. pywebview's `icon` argument only works on GTK and Qt, so `app.py` sets an explicit AppUserModelID (`WeakSquare.ChessTrainer`) before the window exists, and once it's shown sends `WM_SETICON` with the `.ico` (`adapters/desktop.py`). `setup.py` finds the Desktop with `SHGetKnownFolderPath(FOLDERID_Desktop)` (OneDrive redirection) and writes both shortcuts with `IconLocation`; saving to the same path replaces a shortcut.
- Alternatives: Pillow plus cairosvg for the icon (two dependencies, one needing a native Cairo DLL); `%USERPROFILE%\Desktop` (wrong when OneDrive redirects it).
- Consequences: the shortcuts don't carry the AppUserModelID (WScript.Shell can't set it), so a shortcut pinned to the taskbar may group separately from the running window. Adam's manual test checks the taskbar.

### 2026-11-01, v0.2: The puzzle-database update check
- Context: FR-2.5.
- Decision: `core/db_update.py` holds the rules (newer = a different published SHA-256, or a later Last-Modified when the import has no hash; skipped exports are remembered as `sha256:<hash>` or `date:<date>`; at most once a day by the injected clock; the page's count parsed best-effort). `services/db_update.py` runs it as a `puzzle_db_update_check` job that the front end starts once per launch when a database is installed; "Check for updates" forces it. It makes three requests through `adapters/http.py` (`get_text` for the sums and the page, `head_info` for the file), catches every network error, and records the check time only after a successful check. "Not now" is kept in memory (this launch), "Skip" in `settings`. The offer disappears once its export is imported. After an update import the dialog stays open to show the exact new/removed numbers. Tests replay recorded responses (`tests/fixtures/http/lichess_db`, from `tests/fixtures/tools/record_db_update.py`) through the real `HttpClient` with an `httpx.MockTransport`.
- Scrubbing: the page section included Lichess's sample CSV with real game URLs. The recorder keeps only the introduction and blanks lichess.org links. `test_fixtures_clean.py` used to scan only five extensions and missed the `.html`; it now scans every text file under `tests/fixtures`.
- Alternatives: starting the check from `app.py` at launch (the result would arrive before the UI could listen for it).
- Consequences: if Lichess redesigns the page, only the approximate count disappears; re-run the recorder and update `parse_count`.

### 2026-11-01, v0.2: Dark mode without browser storage, AA contrast, move sounds from lila
- Context: FR-1.12 and FR-1.13; decision 14 (no browser storage).
- Decision:
  - **Dark mode:** Mantine's default color-scheme manager uses localStorage, so `state/colorScheme.ts` provides one that keeps the scheme in memory and saves it through `set_setting("ui.color_scheme")`. `main.tsx` waits for `get_settings` (at most 1.5 s) before the first render, and `app.py` paints the window background in the saved scheme (`system_prefers_dark()` reads the Windows app mode for Match system), so nothing flashes. Match system is Mantine's `auto` (`prefers-color-scheme`, which WebView2 updates live). The plan's `?scheme=` start URL wasn't needed; the mock uses `?scheme=` only to start in a scheme for tests.
  - **Contrast:** an e2e test checks every visible text node on every main screen in both schemes against WCAG AA. Mantine's defaults failed it, already in v0.1's light theme: dimmed grey 3.3:1, white on teal-6 buttons 2.6:1, teal light badges 4.3:1, green text 4.4:1. `main.tsx` sets `primaryShade: 9` and overrides those CSS variables.
  - **Sounds:** `core/move_sounds.py` classifies each move (mate > check > capture > castle > move) and the bridge sends the kind with every move (`opponent_sound`, `move_sound`, `reply_sound`, `answer_sounds`), so the rule is unit-tested in Python. `web/src/sound/player.ts` creates `Audio` elements only while sounds are on, and a new sound stops the last. The files are lila's Enigmahack sets (AGPLv3+ in lila's `COPYING.md`), the six `.ogg` files each set needs, pinned to lila commit `9934f0a6`; lila's `Checkmate.ogg` is a git symlink to `Check.ogg`, so each set ships a copy of it. `web/public/sounds/CREDITS.md` lists every file with its SHA-256, and a contract test keeps it complete. The CSP gains `media-src 'self'`.
  - **Autoplay:** a real-app smoke test shows WebView2 plays audio without a user gesture, so the planned `--autoplay-policy` switch wasn't added.
  - The real-app smoke harness now stops with the build command when `web/dist` is older than `web/src` (a stale build had hidden the new Settings menu).
- Alternatives: rendering at once and switching after the settings arrive (a visible flash); a JS move-sound classifier (no unit tests without a JS runner); shipping `.mp3` too (Chromium plays Ogg).
- Consequences: a theme color change can fail the contrast test; fix it in `main.tsx`'s resolver.

### 2026-11-01, v0.2: `on_help`, Stats definitions, one UI-settings service
- Context: §7.2 steps 1–2 without an engine; FR-9.1/9.2; and dark mode, sounds and coordinates all needing persisted UI settings.
- Decision:
  - `TrainingMode.on_help(state, "hint" | "answer", now)` returns a `HelpResult` (hint square, or the answer's start FEN and remaining UCI moves). Help before the attempt is decided appends the loss at that moment with `help_used` set; after that it's free (FR-5.4). Mid-puzzle, Show answer is refused (`conflict`) until a Hint; once decided it needs none. Show answer ends the puzzle. After a finished line it replays from the start. Since Hint always comes first, Standard mode records `help_used = 'hint'` in practice; `'answer'` stays for modes that allow it directly.
  - Stats read the attempts log left-joined to puzzles.db. "First move right, line wrong" is a share of the attempts whose first move was right (it measures calculation, not spotting). Rating bands use `attempts.puzzle_rating`.
  - `services/ui_settings.py` owns every UI setting key and its validator; `set_setting`'s key is a `Literal` of the allowed keys, and the front end's `SettingValues` type mirrors it.
- Alternatives: recording help as a separate event row (the attempts log already has `help_used`); keeping settings in `MixerService` (it would have grown a key per feature).
- Consequences: adding a UI setting means a validator in `ui_settings.py`, a field in `dto.UiSettings` and a key in `SettingValues`.

### 2026-11-01, v0.2: Ratios by quota, history filters in SQL, defaults that upgrade saved filters
- Context: FR-3.8 to FR-3.11 and Adam's planning decisions (quality and Exclude solved on by default).
- Decision:
  - **Ratios** (`core.queue.allocate`): each refill computes every group's target share of everything drawn so far (largest remainder, ties broken by the injected rng), fills the shortfall and shuffles the slots. A 50/30/20 mix stays within one puzzle of exact. A group with no puzzles gets weight 0 at the start (`SessionInfo.empty_buckets`, shown as a notice), and one that runs dry mid-session gets weight 0 and its slots go to the others. Each group is the base filters with that group's themes (ANY); groups never repeat a puzzle between them.
  - **Order:** a fixed-size queue in a non-random order is drawn whole, then sorted; an endless one sorts each refill of 50.
  - **History filters** are subqueries on `attempts` (user.db is the main schema of every connection): `id NOT IN (ids ever won)` and `id IN (ids whose latest attempt lost)`. *Only my misses* overrides *Exclude solved*.
  - **Changed defaults:** `FilterSpec` defaults are now popularity ≥ 50, ≥ 100 plays and Exclude solved on. Saved filters carry a `mixer.filters_version`; `upgrade_saved` gives v0.1 filters the new defaults once.
  - The mixer recounts after each recorded attempt, since the history filters change the count.
- Alternatives: a weighted coin per slot (drifts by several puzzles in short sessions); a history column copied into puzzles.db (it's replaced on every import).
- Consequences: ratio sessions draw per group, so a session with N groups makes up to N sampling queries per refill.

### 2026-11-01, v0.2: puzzles.db schema v2, upgraded locally from the old file
- Context: the opening (FR-3.7) and quality (FR-3.8) filters need new columns and a wider covering index. puzzles.db is attached read-only, and the download is deleted after an import, so a v1 database can't be migrated in place or simply re-imported from disk.
- Decision: `puzzles/0002_openings_quality.sql` adds `opening_family` and `opening_variation` (ids into a new `openings(id, tag, family_id, count)` table; the first OpeningTags tag is the family, the second its variation). The covering index becomes `(rating, length, player_color, t0, t1, t2, popularity, nb_plays)`, plus `(opening_family, rating)` and `(opening_variation, rating)`. When `puzzles.db` has an older schema, the app offers an **upgrade** job: `ExistingPuzzleDb` streams the current file's rows CSV-shaped through the same parser and `PuzzleDbWriter` into `puzzles.new.db`, which is checked and swapped as in FR-2.3. The writer also attaches the database it replaces and counts new and removed puzzle IDs before the swap (FR-2.5); a job can now return its own finish message. user.db `0002` adds `presets` and a nullable `attempts.puzzle_rating`, which is backfilled from puzzles.db where the puzzle still exists.
- Alternatives: `ALTER TABLE` plus a 6M-row `UPDATE` on a copy of the live file (slower, and a second import path); forcing a 300 MB re-download.
- Consequences: one code path builds every puzzles.db. Each future puzzles.db schema change reuses the upgrade job.

### 2026-11-01, v0.1: Standard-mode scoring details and the `TrainingMode` shape
- Context: Show answer arrives only in v0.2, so v0.1 needed a defined behavior after a wrong move and when you move on early.
- Decision: a wrong move decides the attempt as a loss at that moment (it's appended to `attempts` then), the move is taken back, and you can keep playing the line with nothing more recorded. Moving on before the attempt is decided (**Skip**) records a loss. Themes are revealed with the decision. The v0.1 protocol is `start`, `on_move` and `give_up`; `on_help` joins it in v0.2 with Hint and Show answer, rather than shipping unused.
- Alternatives: recording the attempt only when the line ends (an abandoned puzzle would then never be recorded).
- Consequences: every attempt reaches `user.db` as soon as it's decided, so closing the app loses nothing.

### 2026-11-01, v0.1: Queue sampling and count tuning
- Context: plan decision 3, and the < 500 ms targets on the full DB.
- Decision: pools of ≤ 100k puzzles are fetched and sampled with the injected `Random`; larger pools use rejection sampling over the dense key `n` in batches sized from the match density, keeping the rng's order so a seed always gives the same queue. The attached `puzzles.db` uses `mmap_size` = 2 GB, which cut full-range count scans by about 20% (worst case ~330 ms, warm).
- Alternatives: `ORDER BY random() LIMIT 50`, which sorts the whole pool.
- Consequences: deterministic tests for queues; memory-mapped pages count toward the app's working set, but they're file-backed and shared with the OS cache.

### 2026-11-01, v0.1: Test harness details
- Context: the real-app smoke harness and the screenshot spec had timing problems on the first runs.
- Decision: the smoke harness waits until the WebView2 debugging endpoint lists the app's page (polled over HTTP at `/json/list`) before attaching, because the sync Playwright API only learns about new pages while a call is running. It closes the app with `WM_CLOSE` to the PID the app writes into its lock file (the venv's `python.exe` is a launcher with a child process). The screenshot spec drives the mock's progress timers with Playwright's fake clock. The mock client serves fixed puzzles taken from the fixture (`web/src/api/mockPuzzles.ts`).
- Consequences: smoke runs were stable over repeated runs, and screenshots are reproducible.

### 2026-11-01, v0.1: Theme bitmasks on `puzzles` instead of a `puzzle_themes` table
- Context: the live match count must answer within 500 ms on ~6.2M puzzles, including ALL across several themes (FR-3.1). A `puzzle_themes` join table would hold ~25M rows (~1 GB more) and makes ALL a multi-way intersection.
- Decision: `puzzles` gets three integer columns `t0`, `t1`, `t2` (62 theme bits each, up to 186 themes) plus `theme_bits(theme, bit, count)`, built at import, so a theme new to an export gets a bit automatically. A covering index `(rating, length, player_color, t0, t1, t2)` answers every v0.1 filter without touching the table. `puzzles.n` is a dense integer key used for random sampling. The plan named a separate narrow `puzzle_index` table; a covering index gives the same narrow scan without a second copy of the rows. Indexes are built after the bulk load (`puzzles_indexes.sql`). REQUIREMENTS §4.3 is updated to match.
- Alternatives: `puzzle_themes(theme, puzzle_id)`, which the spec suggested first and allowed replacing "if multi-theme counts are too slow".
- Consequences: measured on the 2026-10-02 export, a full import takes about 90 s and `puzzles.db` is 1.4 GB. Warm counts take 80–400 ms (the worst cases scan the whole rating range). A filter on a theme beyond bit 186 isn't possible; the importer logs it.

### 2026-11-01, v0.1: The puzzle download is verified against Lichess's published SHA-256
- Context: plan decision 8 had to be confirmed at build time. database.lichess.org publishes `sha256sums.txt` at its root, and it lists `lichess_db_puzzle.csv.zst`.
- Decision: the importer fetches that list, downloads (resuming with `Range` / `If-Range`), and compares hashes. On a mismatch it deletes the file and stops. A complete earlier download that matches is reused. If the list ever stops naming the file, the import continues with a logged warning. The export date is the file's `Last-Modified`. `scripts/fetch_puzzle_db.py` takes the single-instance lock, so it can't replace `puzzles.db` under a running app.
- Alternatives: a hard-coded hash, impossible because the export changes every month.
- Consequences: a download caught mid-update by Lichess fails cleanly and can be retried.

### 2026-11-01, v0.1: Pin MIME types for the local web server
- Context: on some Windows machines the registry maps `.js` to `text/plain`. Python's `mimetypes` reads that, pywebview's local server sends the bundle as `text/plain`, and WebView2 refuses to run module scripts, so the window is blank. It happened on the first real-app smoke run.
- Decision: `app.fix_mime_types()` pins `.js`, `.mjs`, `.css` and `.svg` before the window starts. A regression test covers it.
- Alternatives: a single inline bundle, rejected because it conflicts with the strict CSP (SR-3).
- Consequences: none beyond the four lines.

### 2026-11-01, v0.1: `--dev` decides the data folder and permits the test debugging port
- Context: NFR-2 wants dev runs kept apart from real history. SR-16 says "release builds" refuse the WebView2 debugging port, but the app runs from source, so there is no separate release build.
- Decision: `python -m weaksquare` (the Start-menu shortcut) uses `%LOCALAPPDATA%\WeakSquare`; `--dev` uses `WeakSquare-dev`; `WEAKSQUARE_DATA_DIR` overrides both. The app refuses to start if `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` contains `--remote-debugging-port` unless `--dev` is given, and the smoke harness always launches with `--dev` and a temp data folder. Under pytest, `config.resolve_paths` raises if it resolves to either real folder.
- Alternatives: a separate environment variable to allow the port, rejected as one more thing a stray environment could set.
- Consequences: the real app can never be attached to, and a dev run never sees real history.

### 2026-11-01, v0.1: SQLite threading details
- Context: decision 12 says one connection per thread, but FR-2.3 swaps `puzzles.db` while the app runs, and Windows can't replace a file that's open.
- Decision: every query runs inside `Database.session()`, which holds a shared lock. `swap_puzzles_db()` takes the exclusive lock (so no query is running), closes every registered connection, replaces the file, and bumps a generation counter so each thread reopens lazily. That's the only time a connection is touched from another thread (connections are opened with `check_same_thread=False` for that reason alone). WAL is set once when `Database` is created, because switching it from several threads at once fails with "database is locked". `puzzles.db` is attached read-only (`mode=ro`), so it never has `-wal` files.
- Alternatives: versioned puzzle files (`puzzles-<date>.db`) with a pointer, rejected because FR-2.3 names the `puzzles.new.db` → `puzzles.db` swap and cleanup is messier.
- Consequences: a swap waits for running queries to finish (milliseconds).

### 2026-11-01, v0.1: The DTO contract is generated
- Context: decision 8 needs `bridge/dto.py` and `web/src/api/types.ts` to match.
- Decision: `scripts/gen_types.py` writes `types.ts` from the dataclasses listed in `dto.EXPORTED`, and a contract test runs it with `--check`. Every bridge result is wrapped as `{ok: true, data}` or `{ok: false, error: {code, message, retryable}}` by `@bridge_call` (NFR-5), and the TypeScript client unwraps it and throws `ApiCallError`.
- Alternatives: hand-written types plus a parser that compares them, which is more code and still drifts.
- Consequences: changing a DTO means re-running the generator, and the test says so.

### 2026-11-01, v0.1: First dependencies
- Context: the v0.1 scaffold (plans/v0.1.md). Every name was checked on PyPI and npm first (SR-14b).
- Decision:
  - Python runtime: `pywebview` (window and JS bridge; pulls in `pythonnet` on Windows), `chess` (python-chess), `platformdirs` (`%LOCALAPPDATA%`), `httpx` (the one HTTP client), `zstandard` (streaming `.csv.zst`; the stdlib `compression.zstd` needs Python 3.14).
  - Python dev: `pytest`, `ruff`, `mypy`, `pre-commit`, `playwright` (Python). One Playwright drives both the mock-client e2e tests and the real-app CDP smoke test.
  - Build backend: `uv_build` (`>=0.13,<0.14`), which is part of uv and is only used to install the package into the venv. It's not a runtime dependency, and users install nothing for it, because `uv sync` (run by `setup.py`) provides it. **Accepted by Adam, 2026-11-01** (QA v0.1-B11: it wasn't in the plan's dependency list). When uv moves past 0.13, widen the range in `pyproject.toml`; check this at each version's planning.
  - npm runtime: `react`, `react-dom`, `@mantine/core`, `@mantine/hooks`, `chessground` (GPL-3.0), `chess.js` (BSD-2-Clause).
  - npm dev: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`, `eslint`, `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`. npm resolved `typescript` to 6.x, the newest that `typescript-eslint` supports.
- Alternatives: npm `@playwright/test` plus Python Playwright (two browsers to install); `pywin32` for the Start-menu shortcut, replaced by an inline PowerShell `-Command` that calls COM.
- Consequences: `npm audit` reports a moderate `minimatch` advisory inside ESLint's dependency tree. It's dev-only, never shipped or run on untrusted input, and has no non-breaking fix yet.

### 2026-10-31, pre-v0.1: Named WeakSquare Chess Trainer
- Context: the working name, "Lichess Puzzle Mixer", matched a GitHub repo (`lichess-puzzle-mixer`) that distributed SmartLoader malware as a zipped `.exe`. Using "Lichess" in the name would also suggest an official connection.
- Decision: display name **WeakSquare Chess Trainer**; repo `weaksquare-chess-trainer`; Python package `weaksquare`; data folder `%LOCALAPPDATA%\WeakSquare`; environment variable `WEAKSQUARE_DATA_DIR`. A weak square is a hole the opponent can exploit, and the app finds and fixes yours.
- Alternatives: ChessTrainerPlus, rejected because the "Chess Trainer" app namespace is crowded; Blind Spot, already used by a similar open-source tool.
- Consequences: none for code (nothing built yet).

### 2026-10-31, pre-v0.1: Open source under AGPL-3.0; run from source instead of a packaged installer
- Context: the project is public, and it combines GPL-3.0 (chessground, Stockfish) and AGPL-3.0 (lichess-puzzler) components.
- Decision: license the repo AGPL-3.0-or-later from the first commit. v1.0 ships as a tagged GitHub release of the source; `scripts/setup.py` installs it and creates a Start-menu shortcut (NFR-8).
- Alternatives: a permissive license, impossible with these components; a PyInstaller `.exe`, rejected because an unsigned bundled executable triggers SmartScreen and antivirus warnings, and a zipped `.exe` is exactly how fake GitHub "tools" deliver malware.
- Consequences: users need Python and Node installed. Updating is `git pull` plus setup. A packaged installer stays a parked idea.

### 2026-10-31, pre-v0.1: uv for Python dependencies and locking
- Context: contributors and CI need reproducible installs (SR-14b).
- Decision: manage Python dependencies with uv and commit `uv.lock`; `scripts/setup.py` installs uv with pip if it's missing; CI uses `uv sync --locked`. The front end uses `package-lock.json` and `npm ci`.
- Alternatives: pip-tools with hashed requirements files, workable but more moving parts.
- Consequences: one extra tool, bootstrapped automatically.

### 2026-10-31, pre-v0.1: Stockfish 19 universal build, pinned by hash, installed outside the repo
- Context: the engine binary is gitignored, so every clone and every installed copy has to fetch it.
- Decision: pin the `sf_19` universal Windows build in `engine_manifest.json` with its SHA-256; install it under `%LOCALAPPDATA%\WeakSquare\engines\`; one installer service shared by the dev scripts, the in-app Install button and the v1.0 wizard (FR-7.5).
- Alternatives: per-CPU builds with feature detection, no longer needed since Stockfish 19's universal binary does it; vendoring the binary into the repo, rejected for repo size and licensing hygiene; always downloading "latest", rejected because it's unverifiable and changes engine behavior without a decision.
- Consequences: no CPU-detection code. Upgrading Stockfish is a deliberate manifest change. Stockfish 19 terminates on invalid input, so `EngineClient` must validate positions first and survive a restart (FR-7.6).

### 2026-10-31, pre-v0.1: Live tests use a scoped token on Adam's own Lichess account
- Context: live tests need a real Lichess account to push solves.
- Decision: a separate personal access token (`puzzle:read`, `puzzle:write` only) on Adam's account, stored as `weaksquare-test`; unrated solves only, at most 3 per run (SR-13).
- Alternatives: a second Lichess account, rejected because Lichess's Terms of Service don't list testing as an allowed reason for one.
- Consequences: a few unrated solves per live run appear in Adam's puzzle history. The test token can be revoked without touching the app's own sign-in.

### 2026-11-01, v0.1 (planning): macOS and Linux deferred to v1.1; keep the code portable meanwhile
- Context: Adam wants macOS and Linux support eventually. Porting while features are still being added would triple CI and manual testing at every checkpoint.
- Decision: a dedicated v1.1 (ROADMAP.md) after v1.0. Until then, OS-specific code stays in adapters, and new features don't assume Windows. `engine_manifest.json` is keyed by OS and architecture from v0.4, with only the Windows entry filled in. The dark-mode option is named "Match system". Linux (Debian stable, Ubuntu LTS) is the fully tested target. macOS is best effort, CI only, until a real Mac is available, because macOS may only be virtualized on Apple hardware.
- Alternatives: porting now, rejected for the testing cost; folding the port into a feature version, rejected for the same reason; never porting, which leaves the door closed for no saving.
- Consequences: v1.1 is mostly adapter, setup and CI work. It needs per-CPU Stockfish selection on Linux, a Secret Service check that refuses rather than storing plaintext, and a non-WebView2 approach for the real-app smoke tests.
