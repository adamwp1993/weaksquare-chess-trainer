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
│  │  ├─ puzzle.py             # Puzzle, PuzzleRef(source, id), PuzzleSource protocol
│  │  ├─ filters.py            # FilterSpec (+ JSON schema, validation)
│  │  ├─ queue.py              # ordering, ratios, queue building (pure; takes candidate ids)
│  │  ├─ scoring.py            # win/loss, help → loss, angle selection
│  │  ├─ modes/                # TrainingMode protocol + one module per mode
│  │  ├─ reasons.py            # mistake-reason suggestion rules      (v0.6)
│  │  ├─ srs.py                # Leitner scheduling                   (v0.5)
│  │  ├─ tags.py               # habit tags from attack maps          (v0.10)
│  │  └─ weakness.py           # metrics + status rules               (v1.0)
│  ├─ services/                # one module per use-case area; created when first needed
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
│  │  ├─ stockfish.py          # EngineClient impl (python-chess UCI)  (v0.4)
│  │  ├─ lichess.py            # (v0.3)   chesscom.py (v0.8)
│  │  └─ llm/                  # LLMProvider protocol, anthropic.py, openai.py (v0.7)
│  └─ jobs/runner.py           # background jobs: queue, progress, cancel
├─ web/
│  ├─ index.html  vite.config.ts  package.json  package-lock.json
│  └─ src/
│     ├─ api/                  # ApiClient interface + pywebviewClient + mockClient
│     ├─ components/           # Board (chessground wrapper), ThemePicker, RatingSlider, …
│     ├─ views/                # Startup, Trainer, Settings, Stats, Library, Review, Coach, Progress
│     └─ state/                # small store; no business logic
├─ tests/
│  ├─ unit/                    # core/ — fast, no I/O
│  ├─ integration/             # services + real SQLite (tmp) + fake clients
│  ├─ e2e/                     # Playwright against web/ with mockClient
│  ├─ smoke/                   # the real app over CDP (harness in conftest.py)
│  ├─ fulldb/                  # opt-in timings against the full puzzle DB
│  └─ fixtures/                # tiny puzzle CSV sample, scrubbed HTTP recordings
└─ scripts/                    # setup.py (one-command setup), fetch_puzzle_db.py, fetch_stockfish.py
                               #   (thin CLIs over services, download + hash check), check_docs.py,
                               #   gen_types.py (bridge/dto.py → web/src/api/types.ts)
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
| `TrainingMode` | `Standard` → `CommitLine`, `SpacedRepetition`, `DepthLadder` → `NameIdea`, `DangerSpotting` | v0.1 → v0.5 / v0.6 |
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
  - Build backend: `uv_build`, which is part of uv and is only used to install the package into the venv.
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
