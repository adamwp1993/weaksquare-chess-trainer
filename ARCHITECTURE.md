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
│  │  ├─ llm/                  # LLMProvider protocol, defaults (the only model names), cost, guardrails (v0.7)
│  │  ├─ srs.py                # Leitner scheduling                   (v0.5)
│  │  ├─ games.py              # PGN parsing, colors, URLs, time classes, Lichess game JSON, library types,
│  │  │                        #   the LichessGamesClient / ChesscomClient protocols  (v0.8)
│  │  ├─ chesscom.py           # chess.com archive games and months   (v0.8)
│  │  ├─ game_review.py        # grading, Missed/Allowed, phases, key moments, side summary (v0.8)
│  │  ├─ game_explain.py       # Game Review AI: the anonymized context, the narrative schema, validation (v0.9)
│  │  ├─ preset_suggestion.py  # an LLM-recommended puzzle preset, validated (v0.9; the Coach reuses it)
│  │  ├─ tolerance.py          # the 30 cp engine tolerance (Retry, game puzzles) (v0.8)
│  │  ├─ puzzle_files.py       # your own PGN / EPD / CSV puzzle files (v0.8)
│  │  ├─ ladder.py             # depth-ladder levels from the attempts log (v0.5)
│  │  ├─ tagging.py            # Lichess theme tags for a tactic line, via vendor/lichess_puzzler (v0.10)
│  │  ├─ habits.py             # habit tags from attack maps          (v0.10)
│  │  ├─ digest.py             # one game's digest from its analysis (v0.11)
│  │  ├─ game_measures.py      # whole-game measures and weaknesses, the 5-game guard (v0.11)
│  │  ├─ coach_diagnosis.py    # the whole-game AI prompt, schema and evidence rule (v0.11)
│  │  ├─ lessons.py            # lesson topics, the curated Lichess map, search links (v0.11)
│  │  ├─ urls.py               # strip web addresses from notes and AI text (v0.11)
│  │  ├─ plan.py               # the deterministic plan, ticks, carry-over and swap (v0.12)
│  │  ├─ plan_llm.py           # the AI plan's schema and validation, what v0.12 adds to the prompt (v0.12)
│  │  ├─ report_compare.py     # Since last report: guards, trend, the check on AI trend claims (v0.12)
│  │  ├─ daily_log.py          # one day's log, through stats.build_report (v0.12)
│  │  └─ weakness.py           # metrics + status rules               (v1.0)
│  ├─ services/                # one module per use-case area; created when first needed
│  │                           #   v0.1: puzzle_db.py (import and upgrade jobs), mixer.py (catalogs, counts), session.py
│  │                           #   v0.2: presets.py, stats.py, ui_settings.py, db_update.py (update check job)
│  │                           #   v0.3: account.py (sign-in, launch check, sign-out), sync.py (the queue),
│  │                           #         lichess_history.py (history import)
│  │                           #   v0.4: engine_install.py (the Stockfish installer), engine.py (EngineService)
│  │                           #   v0.6: reasons.py (saving mistake reasons)
│  │                           #   v0.7: llm_settings.py (provider, key, prices, Test key), llm_usage.py
│  │                           #         (the guardrail gate every LLM request goes through)
│  │                           #   v0.8: games.py (library, sync, imports), analysis.py (the queue on the
│  │                           #         background engine, Review settings), review.py (review, Retry,
│  │                           #         Save as puzzle, game reasons), puzzle_import.py (puzzle files)
│  │                           #   v0.9: game_explain.py (Explain this move, Explain my game)
│  │                           #   v0.12: plan.py (the training plan), journal.py (the journal, the daily log)
│  ├─ adapters/
│  │  ├─ db/
│  │  │  ├─ connection.py      # opens puzzles.db + user.db, ATTACH, pragmas
│  │  │  ├─ migrate.py         # numbered migrations, backup first, newer-schema refusal
│  │  │  ├─ puzzles_indexes.sql  # built after each puzzle import's bulk load
│  │  │  ├─ migrations/puzzles/0001_init.sql …
│  │  │  ├─ migrations/user/0001_init.sql …
│  │  │  └─ repos/             # one repository per aggregate; v0.12: plans.py, journal.py; v0.8: games.py, game_analysis.py,
│  │  │                        #   custom_puzzles.py (+ CustomPuzzleSource, RetryRepo), puzzle_sources.py
│  │  │                        #   (CombinedSource: Lichess DB + My puzzles)
│  │  ├─ http.py               # shared httpx client: UA, timeouts, retry/backoff, redaction
│  │  ├─ secret_store.py       # the ONLY module that imports keyring
│  │  ├─ system_clock.py       # SystemClock + the seeded Random, built only in app.py
│  │  ├─ logging_setup.py      # rotating logs, redaction, crash hooks
│  │  ├─ instance_lock.py      # single-instance lock + bring the window forward
│  │  ├─ desktop.py            # open a folder, pick a file, fatal-error box
│  │  ├─ stockfish.py          # StockfishEngine (python-chess UCI) + probe_engine  (v0.4)
│  │  ├─ lichess.py            # LichessHttp (v0.3); lichess_games.py, chesscom.py (v0.8: serial lock, ETags)
│  │  ├─ oauth_loopback.py     # one-shot 127.0.0.1 listener for the OAuth redirect (v0.3)
│  │  ├─ scheduler.py          # run-later timer for sync retries and reconnect checks (v0.3)
│  │  └─ llm/                  # anthropic.py, openai.py over http.py; error mapping (v0.7)
│  ├─ jobs/runner.py           # background jobs: queue, progress, cancel
│  └─ vendor/lichess_puzzler/  # Lichess's tagger (cook.py, util.py, model.py), AGPL-3.0, pinned; README.md
│                              #   gives the commit and the patch (v0.10)
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
│  │                           #   fake LLM provider (v0.7)
│  └─ fixtures/                # tiny puzzle CSV sample, scrubbed HTTP recordings (http/lichess_db/, http/llm/);
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
| `LichessGamesClient`, `ChesscomClient` (`core/games.py`; the two APIs differ too much for one `GameSource`, v0.8 planning). Pastes and files are parsed by `core.games.parse_pgn` | `LichessGames`, `ChesscomGames`, fakes | v0.8 |
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

### 2026-11-06, planning: Lichess studies and an analysis board tab become v0.14 and v0.15
- Context: Adam wants to browse Lichess studies, heart them and keep his place, and wants an analysis board as its own tab. The Lichess API can fetch a study by ID or list one author's, but can't browse or search all of them.
- Decision: the order is v0.13 opening trainer → v0.14 Lichess studies (FR-13) → v0.15 analysis board tab (FR-14) → v1.0 → v1.1. Studies are found through a Lichess window inside the app, a browser plus a pasted link, or a starter list of links only. The window has no bridge, and is dropped if that can't be proven.
- Alternatives: reading Lichess's study pages behind the scenes, rejected because it's undocumented, would break when the pages change, and breaks the documented-APIs-only rule. Bundling study content, rejected because authors keep their rights. Keeping studies in v0.13, rejected because of its size, its single QA run and the risk from the window.
- Consequences: the window is the first remote website the app shows, so its isolation gets tested first. v1.0's fix tracking and Progress page move two versions later. The opening trainer's repertoire schema must allow `source = study`.

### 2026-11-06, planning: The opening trainer moves before v1.0, and checkpoints gain a schedule and a report
- Context: Adam wants the opening trainer before the macOS and Linux port, and before v1.0. He also wants Coach reports generated automatically, by game count or on a schedule.
- Decision: the opening trainer is now v0.13, so the order is v0.12 → v0.13 → v1.0 → v1.1. Its FR-12 numbers don't change. A checkpoint can also run on a time schedule, and it saves a normal Coach report (FR-10.32, 10.33).
- Alternatives: a Windows scheduled task, so a schedule could run with the app closed, rejected for now because it's more OS-specific work, and the app opens the due checkpoint at the next launch anyway.
- Consequences: the trainer needs only the engine, the LLM guardrails and Lichess sign-in, which have all shipped. v1.0's polish pass, complete User Guide and first-run wizard now have the trainer to cover. Earlier plans and QA reports still say v2.0, as a record of the time.

### 2026-11-05, v0.12: What QA round 1 changed in the plan and journal
- Context: QA v0.12 round 1 found the carry-over limit reset on each read, a group's guard ignored, an ended plan still changing, and more (`qa/QA-v0.12.md`).
- Decision:
  - **`to_carry`** counts what's already carried into today against the limit, so reads are safe to repeat and the limit holds.
  - **`report_compare._group_enough`** applies FR-10.73's guard to a whole-game weakness's own group, from the measures in each report.
  - **`user/0012_plan_manual_at.sql`** records when you ticked by hand, so the daily log counts it. `done_at` stays what the app saw.
  - **`_facts` has an upper limit,** `plan.ended_at`, so an ended plan stays as it was.
  - **`ReviewPassesRepo.start`** resumes only the task's own pass, and `completed_games` needs a pass begun since the plan began.
  - **The timeline** looks at all entries when a search or filter can only match entries. Only the daily log, computed day by day, comes in 30-day windows, and `older` is true only when something is there.
  - **`JournalService.add`** checks links, moves and dates, and accepts only a real weakness key as a tag, since tags go to the AI.
- Alternatives: editing 0011 for `manual_at`, rejected by the rule that migrations are never edited.
- Consequences: the journal composer has no date control, so a future date can only come from a direct bridge call, and it's refused.

### 2026-11-05, v0.12: Plan ticks are worked out from stored events when read, not pushed by hooks
- Context: a task ticks from puzzle sessions, Retry, Game Review and journal entries (FR-10.64), four services that know nothing about plans.
- Decision: `services/plan.py` reads the events when the plan is read: attempts through the new `sessions.plan_task_id`, `retry_attempts` since the plan began, `review_passes`, and `journal_entries.plan_task_id`. The time it first sees a task done goes in `plan_tasks.done_at`, for the daily log. `plan_tasks.manual_state` (done / undone) is your hand choice, and it always wins. A lesson's `done_at` is set when you open it, because nothing else records that. A swapped task stays, marked `removed`, so its sessions stay linked.
- Alternatives: listeners in each service, rejected because every new task type would touch another service, and a missed event would leave a box wrong for good.
- Consequences: nothing can fall out of step, and the session and review services stay unaware of plans. A read does some queries and may write `done_at` or carried tasks; it's safe to repeat (a task with a copy is never copied again).

### 2026-11-05, v0.12: The plan is a pure function, and a puzzle task builds its own filters
- Context: the plan must fit your minutes and days, weight by score, and never change your Mixer (FR-10.61–10.63).
- Decision: `core/plan.build_plan` shares slots by smooth weighted round-robin over the weakness scores, so time follows the score and weaknesses stay mixed across days. `core/plan.task_spec` builds a task's `FilterSpec` from the defaults. `PlanService.start_task` starts the session directly, and the front end has a separate path for it (`planSession` in `App.tsx`). `fit_task` widens a task's rating band until it has enough puzzles.
- Alternatives: one weakness per day, rejected because a test showed it capped your worst weakness at one slot a day.
- Consequences: a test can compare `settings` byte for byte across a task's Start. The Mixer panel keeps showing your filters during a plan session, so a banner says the session uses the task's own.

### 2026-11-05, v0.12: Review passes, not a single "reviewed" flag
- Context: a review task ticks when you've visited every key moment and the final move (Adam, v0.12 planning), and the daily log counts games reviewed per day (FR-10.68). A game can be reviewed twice.
- Decision: `review_passes` has one row per pass, with the plies visited. A new pass starts once the last was completed, and a new plan deletes unfinished passes, because moves looked at before a plan don't count towards it (`PlansRepo.add`). `Api.mark_review_ply` is called as the cursor moves; `ReviewService.mark_visited` decides completion. `games.analyzed_at` records analysis time for the log. FR-10.68's "no extra tracking" was reworded: these are the two additions.
- Alternatives: `games.reviewed_at`, rejected because a second review would overwrite the first day's count, and a task couldn't tell a fresh pass from an old one.
- Consequences: one bridge call per move viewed. Passes for games reviewed before v0.12 don't exist, so those days show none.

### 2026-11-05, v0.12: The AI's plan is validated task by task, and trend claims must match the numbers
- Context: the plan is LLM output (CLAUDE.md "LLM output is untrusted"), and FR-10.73 says a trend finding is checked like any other. `validate()` drops a finding with no game citation, but a weakness that's gone has no game to cite.
- Decision: `core/plan_llm.validate_plan` drops an unknown type, theme, mode, game or topic, writes every title itself (only a reflection's question is AI text, cleaned), and fills each day from the deterministic plan. A trend statement is a separate `trend` field: its key must have been sent and its `change` must equal `core/report_compare`'s guarded verdict, or it's dropped. Both schemas are extended by `add_to_schema` rather than edited: `plan` only for your own reports.
- Alternatives: asking for the plan in a second request, rejected because FR-10.66 has it in the answer and it would need a second Confirm.
- Consequences: Coach `max_tokens` rise to 7,500 and 10,000 and `COACH_TIMEOUT_S` to 300 (Adam, v0.12 planning: flat limits). Worst-case estimates rise on every Coach run, so costly models at High reasoning can now be blocked by the default $0.50 cap.

### 2026-11-05, v0.12: A saved AI answer stands only for what it was given
- Context: `_cached_run` matched on options and model. An answer from before plans would hide the plan, and a saved answer reused after you edit your journal would mean the preview showed text that was never sent.
- Decision: `coach_ai_runs` gains `include_journal` and `journal_hash` (SHA-256 of the lines sent, no text). A stored answer is reused only with the same hash and, for your own reports, with a `plan`. The hash, not the text, is stored in those columns.
- Alternatives: never reusing with the journal on, rejected because it would re-bill you for an unchanged request.
- Consequences: Plan settings aren't in the key: a saved answer keeps the shape it was made with, so changing settings never re-bills you.

### 2026-11-05, v0.12: Since last report replaces the unguarded trend in the UI
- Context: the v0.10 column said better or worse with no sample check, and `core/coach.trend` treated a new weakness as a rise from zero. FR-10.73 requires guards.
- Decision: `core/report_compare.compare` is the only source of better / worse, and the weakness tables read `CoachWeakness.change` from it. Reports save `analysis_settings` from v0.12; older ones show *settings unknown*. Puzzle accuracy per weakness is worked out from `attempts` by time window, and kept in memory once worked out because both windows have closed.
- Alternatives: storing the comparison with the report, rejected because it would be wrong after the older report's numbers were read differently, and it isn't expensive to compute.
- Consequences: `core/coach.trend` stays for its existing callers but no longer reaches the screen. v1.0's statuses can reuse the comparison.

### 2026-11-05, v0.12: One tooltip table, checked by a walk over the real screens
- Context: FR-10.72 puts a tooltip on every option, app-wide, and later versions must not forget one.
- Decision: `web/src/text/tooltips.ts` holds all the text under typed ids. `OptionInfo` renders the mark, and `Labeled` puts it in a Mantine label. `tests/e2e/test_v012_tooltips.py` walks the screens and requires each control to have its own mark: inside its label, in its `data-option-group`, or named by `data-option-for`. `data-no-tip="<reason>"` opts out free text and row selectors. The first test plants a bare control to prove the walk catches one.
- Alternatives: Mantine's `description` prop, rejected because it takes up room on every control; a lint rule, rejected because it can't see what renders.
- Consequences: the mark sits inside the `<label>`, so a click on it has to `preventDefault`, or it would toggle the option (a test checks this). It's an SVG with no text, so a control's accessible name stays exactly its label (a first version with an `aria-label` turned "Puzzles" into "PuzzlesMore about this option", caught by the older tests); the tooltip's words reach assistive tech through `aria-description`.

### 2026-11-04, v0.11: QA fixes (v0.11-B1 to B14)
- Context: QA round 1 (`qa/QA-v0.11.md`), FAIL: three major and five minor bugs; round 2, FAIL: B9 (major) and B10 (minor) in the URL filter; round 3, PASS WITH ISSUES: B11–B14 (minor), also in the URL filter.
- Decision:
  - **B1, B2:** one `core/urls.strip_urls`, used on your notes, on all AI text (the diagnosis, the v0.10 keyed coaching) and on AI preset names. It catches any `scheme://`, `www.` and bare domains on a list of common top-level domains (`youtu.be`, `bit.ly`, `.co.uk`, `.de`…), and needs a word boundary after the domain, so "Qd1.Coming back" is left alone.
  - **B3:** `user/0010_observation_reports.sql` adds `coach_observations.report_ids` (backfilled from the first and last report), and `times_seen` counts distinct reports in any order.
  - **B4:** `Measures.phases_enough` (5 games) guards mistakes per phase, shown with *not enough data yet*.
  - **B5:** `CoachService.start_ai` is single-flight per report and options (a second call while that job runs returns the same job), and the Confirm button holds a guard until the job ends, so a double-click sends and bills one request.
  - **Round 2, B9, B10:** `strip_urls` also removes IPv4 addresses and **any** dotted host followed by a path, query or fragment, whatever its top-level domain; a bare host without a path counts on the TLD list, and an ending that is also a short English word (No, To, It, At, Be…) counts only in lower case, so a missing space ("Blundered.No time") isn't taken for a link while "Lichess.Org" still is.
  - **Round 3, B11–B14:** `strip_urls` is rewritten to check one whitespace-separated word at a time (linear time, no regex backtracking: B14). A word is an address with a scheme, `www.` or `//`; as an IPv4 address or any host with a port (B13); as a dotted host (Unicode letters and `_` allowed, B13) followed by a path, query or fragment; or as a bare host on the TLD list. The ending must be letters in lower case or all capitals; a capitalized ending is a missing space ("blunder.Today", "Nf3.Why?", B11, B12) except `.Com` and `.Org`; and a bare host whose ending is a short English word needs a path.
  - **B6:** the diagnosis prompt keeps v0.10's puzzles-vs-games table; the privacy section lists the key moments' themes and reason labels. **B7:** "1 game" in the measures. **B8:** the plan ticks lesson pointers.
- Consequences: each fix has a regression test (QA's xfail tests now pass).

### 2026-11-04, v0.11: Lesson links are built and opened by the backend (`open_lesson`)
- Context: FR-10.59: the LLM picks topics only and never writes URLs; Adam chose Lichess Practice and Learn only for the curated map.
- Decision: **`core/lessons.py`** holds the topic catalog (themes, endgame types, concepts, and the opening families of the report's games), the curated map (Lichess Practice study links and Lichess Learn, checked against lichess.org/practice on 2026-11-04; Lichess resolves the study id and ignores the slug), `ALLOWED_HOSTS = {"lichess.org"}`, and the YouTube and chess.com search templates. The screen receives titles and site names only. **`Api.open_lesson(report_id, topic, target)`** asks `CoachService.lesson_url` for the URL (a curated index re-checked against the allowlist, or a search template you turned on in Settings → Coach) and calls `Desktop.open_in_browser`. The custom search site is validated (https, one `{q}`, a host with a dot) when saved and when used.
- Alternatives: sending URLs to the screen as `<a href>` links (rejected: the screen would hold URLs the user can't tell apart, and a bug could let an AI string through); fetching the pages to check them at run time (rejected: the app never visits those sites).
- Consequences: a new curated page is a code change with a test (every curated URL's host must be on the allowlist).

### 2026-11-04, v0.11: Adam's requests during the build: Explain in Retry, preset management
- Context: Adam asked mid-build for Explain this move in Retry your mistakes, and for overwriting, renaming and deleting presets more easily.
- Decision: **Retry** renders the existing `MoveExplain` for the mistake's ply once there's a result (never before the attempt), with its Show me drawn on the Retry board. **Presets:** front end only, since `save_preset(overwrite)`, `rename_preset` and `delete_preset` already existed: Update (overwrite the loaded preset), a Manage presets list (overwrite, rename or delete any preset, unusable ones included, without loading it), and Replace or another name on a Coach preset's name clash.
- Consequences: REQUIREMENTS FR-3.13 and FR-11.15 note both.

### 2026-11-04, v0.11: The whole-game diagnosis: G labels, the evidence rule, per-run options, stored runs
- Context: FR-10.54–10.60: an open-ended diagnosis that must cite real games and plies, an opt-in Advanced run with move lists, opt-in notes, and every answer kept (Adam, v0.11 planning).
- Decision:
  - **`core/coach_diagnosis.py`** builds the prompt from the report's allow-listed aggregates, the measures, one digest per game labelled `G1…` (in the report's game order), the v0.10 examples (now with a game label and 1-based ply), and only with the options the SAN move lists (`core/game_explain.san_moves`, from the parsed moves, so no PGN text) or your notes (`strip_urls`). It returns the text and a `Sent` record (citable plies per label, measured keys, topic ids) that `validate` checks every citation, key and topic against. The label → game id map is stored with the run, never sent.
  - **`services/coach.CoachAiOptions`** (advanced, game cap 10–50, include notes) is an argument of `quote_ai` / `start_ai` only. It's not part of `CoachParams`, so it's never in `coach.last_params`, and a call with no options is a standard run.
  - **Advanced's comparison** builds the standard prompt too and quotes both; the minutes come from `TYPICAL_INPUT_TOKENS_PER_S` and `TYPICAL_OUTPUT_TOKENS_PER_S` in `core/llm/defaults.py`. Coach requests use `COACH_TIMEOUT_S` (180 s) through a new `timeout_s` argument of `LlmUsageService.run`.
  - **Runs** go to `coach_ai_runs`. A cached answer means the same report, options (and cap), format, provider and model. `ai_runs` marks the findings no earlier run had, matched by key, else topic, else category and normalized title. Puzzle-history reports keep the v0.10 keyed prompt (`format = 'keyed'`).
- Alternatives: one prompt for both report kinds (rejected: a puzzle-history report has no games to cite); storing options on the report (rejected: several runs per report).
- Consequences: v1.0's checkpoint summary must call `quote_ai` / `start_ai` with no options, which can't be Advanced.

### 2026-11-04, v0.11: Whole-game schema (`user/0009_whole_game.sql`): digests, AI runs, observations
- Context: FR-10.52 stores the digests; FR-10.57 asks for a migration for the new kinds and recurring observations; Adam wants every AI answer of a report kept, so a standard and an Advanced run can be compared (v0.11 planning).
- Decision:
  - **`game_digests(game_id, color, analysis_key, digest_json, built_at)`**, one per game and side, since a game you played against another player you ran the Coach on counts for both. `analysis_key` holds the analysis think time, engine, thresholds and `core/digest.DIGEST_VERSION`; a different key rebuilds the digest from the stored analysis, with no engine.
  - **`coach_ai_runs`**: every AI answer, with its options (`advanced`, `include_notes`, `game_cap`), model and cost, and `format` `keyed` (v0.10) or `diagnosis` (v0.11). The migration copies each v0.10 `coach_reports.llm_json` in as a `keyed` run and leaves `llm_json` alone.
  - **`coach_observations`**, unique per subject plus `topic_key` (or category plus a normalized title when there's no topic); `times_seen` counts reports, not runs.
  - **The new weakness kinds aren't a table.** `opening`, `endgame`, `phase`, `time` and `habit:castledLate` live in the report JSON, as v0.10's kinds do; v1.0's `weaknesses` and `weakness_metrics` tables will take them all.
- Alternatives: digests inside the report JSON (rejected: they're per game and reused across runs); a column per option on `coach_reports` (rejected: one report has several answers).
- Consequences: `coach_reports.llm_json` is no longer written; the AI runs table is the source.

### 2026-11-04, v0.11 (pre-planning): npm override pins minimatch to ^11.0.4 (Dependabot alert #1)
- Context: Dependabot alert #1: minimatch 10.2.6 (>= 7.0.0, < 11.0.1) can be made to use excessive CPU and memory by a crafted glob pattern. It reaches `web/package-lock.json` only as a transitive **dev** dependency of `eslint` 10.14.0 and `typescript-eslint` 8.72.1, both already at their latest versions, which still ask for minimatch 10. ESLint only reads our own config's globs, so the real risk was low.
- Decision: an `overrides` entry in `web/package.json` (`"minimatch": "^11.0.4"`) with the lock file regenerated. `npm audit` reports 0 vulnerabilities; ESLint, `tsc --noEmit` and the build pass, and ESLint still ignores `dist/` and still reports errors.
- Alternatives: waiting for eslint to move to minimatch 11, rejected because the alert stays open in the meantime; dismissing the alert as dev-only, rejected because the fix is one line.
- Consequences: remove the override once `eslint` and `typescript-eslint` depend on minimatch 11 themselves (check at each version's dependency review). If a future eslint breaks on minimatch 11, the override is the first thing to suspect.

### 2026-11-04, v0.10: QA fixes (v0.10-B1 to B8)
- Context: QA round 1 (`qa/QA-v0.10.md`), PASS WITH ISSUES: two major and six minor bugs.
- Decision:
  - **B1:** "yours" means the `me` row in `game_subjects`, not `games.user_color` (which holds another player's color for their games). `stats.game_reason_rows` joins it, and Review offers Retry and reason chips only on your games (`ReviewService._mine`).
  - **B2:** `missed_or_allowed`: a move that walks into a forced mate is **Allowed** even from a winning position. A missed win that only loses ground stays Missed (checked with the real engine both ways). REQUIREMENTS FR-10.11 notes it.
  - **B3:** `App.tsx` reloads the filters and the suggestion when any `coach_run` job ends, whatever page is open.
  - **B4:** with Show best moves off, Explain this move hides its step-by-step line (the better line), as FR-11.35 hides the AI's better lines.
  - **B5:** the Coach page chooses all your games, Lichess only or chess.com only (`platforms`, FR-10.3).
  - **B6:** "1 game" in Saved reports; the User Guide states Lichess's mate-in-one rule.
  - **B7:** `get_theme_catalog` returns no themes before a puzzle database exists, instead of crashing.
  - **B8:** the v0.9 smoke test reads the first two of the three AI features.
  - **Round 2, B9:** while a puzzle session runs, a finished Coach run updates the filters but its mode waits for the session to end (App keeps it pending), so the Mixer and the session agree (§6). **B10:** the User Guide covers the account choice and the hidden explanation line; screenshots regenerated. Also from round 2: the one-time backfill regrades stored moves first (`AnalysisService.regrade_stored`), so games analyzed before v0.10 get the B2 rule.
  - **Manual test M1 (Adam):** the Coach's model picker sits in the AI coaching box; **Ask <model> instead** when the saved answer is from another model. **Round 3, B11:** a held-back suggested mode also applies at the next **Start**, and a mode you pick yourself clears it. **B12:** screenshots regenerated.
- Consequences: each fix has a regression test (QA's xfail tests now pass).

### 2026-11-04, v0.10: AI coaching on a report: allow-listed prompt, the Coach feature, stored on the report
- Context: FR-10.21–10.25 and FR-1.15 (the Coach gets its own model).
- Decision:
  - **`core/coach_llm.py`**: `build_prompt` copies only allow-listed report fields (rates, severities, reasons, the gap table) and up to 12 (Summary) or 20 (Detailed) example positions labelled E1…, rebuilt as SAN from the stored analysis. Game ids, dates, labels and usernames never enter the prompt, whoever the report is about. `validate` keeps weakness notes only for keys that were sent (3–5), and presets through `preset_suggestion.validate_coach_preset` (up to 6 motif or mate themes, a valid range, move counts 1–4, a known mode, 5–100 puzzles); with none left, the report's deterministic preset is offered (`fallback_preset`).
  - **The `coach` feature** in `core/llm/defaults.py`, with kinds `coach_summary` (2,500 `max_tokens`) and `coach_detailed` (5,000), typical prompts of about 5k and 20k tokens; `llm.feature.coach.*` keys, "Same as Explain" by default. The usage log records `coach`.
  - **Stored on the report** (`coach_reports.llm_json`) with its provider and model: the same report and model shows again for free (`quote_ai` returns `cached`). A new model asks again.
- Alternatives: `llm_cache` (rejected: the answer belongs to one saved report, and the report row already exists).
- Consequences: v1.0's auto AI summary can reuse `build_prompt` at the Summary level.

### 2026-11-04, v0.10: The Coach run, the report and the Suggested mix
- Context: §10.1–10.7 for v0.10, without checkpoints or statuses (v1.0).
- Decision:
  - **`services/coach.CoachService`** runs one `coach_run` job: your library after a sync (it waits on the `games_sync` job), or another player's games through `GameLibraryService.fetch_player_games` (stored under their subject; Lichess with your token when signed in, chess.com newest month first, one request at a time); then the analysis queue (it waits on the `game_analysis` job, with a time estimate from the queue's progress), `retag`, puzzles for your games, and the report. Jobs run on their own threads, so one job can wait on another; a cancelled Coach run cancels the job it's waiting on.
  - **`core/coach.build_report`** aggregates the `game_errors` view by subject. Weakness keys are `missed:<theme>`, `allowed:<theme>`, `habit:<habit>` and `puzzle:<theme>` (puzzle history). Rates are per 10 games; severity is the average cp loss capped at 1000; the score is rate × severity / 100. Only themes in the Motifs, Advanced, Mates, Mate patterns and Special moves groups are weaknesses. Reports are stored as JSON in `coach_reports`, with the preset and notes; the trend compares with the subject's previous games report.
  - **`core/suggested_mix.build_suggestion`**: ratio groups for the top 4 weaknesses by score, plus a `long`/`veryLong` group (10% exploration plus the share of multi-move Missed tactics, at most 50%). **FilterSpec** gains `my_severities` and `my_share`, and ratios are allowed with source Both (each group's slots go to My puzzles with probability `my_share`). Per-group move counts (`RatioBucket.lengths` in the plan) were dropped: they'd need a per-group length condition in the bucket-count SQL, and Lichess's length themes do the same job. The new fields default to "no restriction", so `SAVED_FILTERS_VERSION` stays 3.
  - **Suggestion state** in `settings`: `mixer.suggested` (report id, run number, spec, mode, "why" lines, `pending`, the filters it would replace) and `mixer.suggested_applied`. A run replaces `mixer.filters` and `trainer.mode` only when the filters are the default or the last applied suggestion; otherwise `pending` shows the banner.
- Alternatives: a `coach_suggestions` table (rejected: one current suggestion, a setting is enough); applying the LLM's preset to the mix (rejected for v0.10: Load preset is your click, FR-10.24).
- Consequences: v1.0's checkpoints can reuse the run (minus the sync and the report UI) and replace the score ranking with statuses.

### 2026-11-04, v0.10: Puzzles from your games: a hook on the analysis job, checks cached per move
- Context: FR-10.39–10.43 with Adam's planning answers (puzzles after any analysis; Lichess's rules).
- Decision:
  - **`services/game_puzzles.GamePuzzlesService`** is registered with `AnalysisService.add_listener`, so it runs inside the `game_analysis` job right after each game is stored, on the same background engine. A failure there is logged and never fails the analysis (except a missing engine). Wired in `app.py`, the only place that knows both.
  - **`core/puzzle_gen.check_position`** takes the stored MultiPV 3 lines for the first position and an `analyse(board, multipv)` callback for the rest (the background engine at `coach.puzzle_think_s`, default 1.0 s). It ports `analyze_position`, `cook_mate`, `cook_advantage`, `is_valid_attack` and `is_valid_mate_in_one`, with the differences listed in its docstring (no tiers, the ±500 cp "decided" rule, a cap of 8 solver moves).
  - **Positions:** Missed is solved from `fen_before` as the mover, with the eval before the opponent's previous move as Lichess's `prev_score`; Allowed from the next row's `fen_before` as the opponent (`solve_as = 'opponent'`), using that row's stored lines. Inaccuracies use the Missed/Allowed rule as if they were mistakes. Moves before ply 12 are skipped.
  - **The cache:** `coach_candidates` keeps each verdict with a `check_key` (generator version, the analysis think time and engine, the puzzle think time and margin). A level change archives and restores from the cache (`status` `archived`), then checks only uncached mistakes in a `game_puzzles` job. `hidden` is reserved for puzzles you archive yourself.
  - **The backfill** (`coach.backfill_version`): retags all stored analysis, tags untagged custom puzzles (saved ones with the previous move from the game, imported ones with a null move and no goal themes), then makes puzzles for your analyzed games. Without Stockfish it stops after tagging and tries again at the next launch.
  - **The session** gets `solve_as_opponent`, `game_id` and `game_ply` on `PuzzleView` (the label and the link to Game Review).
- Alternatives: a separate job after each analysis (rejected: it would race the next game for the background engine); re-checking on every level change (rejected: FR-10.40 says no engine pass).
- Consequences: Review, Analyze selected and Coach runs all make puzzles with no extra wiring. A changed generator needs `GEN_VERSION` bumped.

### 2026-11-04, v0.10: The Coach schema (`user/0008_coach.sql`): whose games, tags, checks, reports
- Context: the Coach can run on another player (FR-10.3, Adam), whose games must stay out of yours; the tagger and habits need storage; the puzzle quality check must not re-run on a level change (FR-10.40); reports are saved (FR-10.20).
- Decision:
  - **`game_subjects(game_id, subject, color)`**: `subject` is `me` or `<platform>:<lowercase username>`. A game is stored once (the v0.8 dedupe rules) and can count for both. All games before v0.10 are backfilled as `me` with their `user_color`. `games.user_color` stays "your color" for your games; for a game that's only another player's, it holds that player's color (the side Game Review shows). When a game becomes yours, your color wins. `LibraryFilter.player` (default `me`) filters the library through it.
  - **`game_analysis.habits`** (JSON list) next to the v0.8 `themes`, written by `GameAnalysisRepo.replace` and `set_tags`; `MoveRow` gains `themes` and `habits`.
  - **`coach_candidates`** caches each quality check per (game, ply) with a `check_key` of the analysis and generator settings.
  - **`coach_reports`** with `subject` and `subject_label`; the AI coaching is stored on its report (`llm_json`).
  - **The `game_errors` view** (planned at v0.8): the graded errors of each subject's own moves.
- Alternatives: a `players` table (rejected: the subject string is the key, and the label lives on the report); a separate table for other players' games (rejected: a game you played against them would be stored twice, with two analyses).
- Consequences: every query of "your games" must filter on `subject = 'me'` (the library does; the Coach reads `game_errors` by subject).

### 2026-11-04, v0.10: The lichess-puzzler tagger is vendored; its generator's rules are ported
- Context: FR-10.12 wants themes that match the puzzle DB exactly, and FR-10.41 wants Lichess-quality puzzles from your games. lichess-puzzler isn't on PyPI and isn't a package. Its tagger (`tagger/cook.py`, `util.py`, `model.py`) needs only python-chess; its generator needs MongoDB, a tablebase server, `zstandard` and 30-second searches.
- Decision:
  - **Vendor the tagger** at commit `8e24b6d5e2b9` under `src/weaksquare/vendor/lichess_puzzler/` with its AGPL-3.0 `LICENSE`, and record the commit and the patch in `vendor/README.md`. The patch makes the imports relative and drops the module-level `logging.basicConfig` and the `log()` helper. ruff skips `vendor/`, and mypy ignores its errors, so the files stay diffable against upstream. `tests/contract/test_vendored_tagger.py` keeps the imports to python-chess, typing and dataclasses, and checks that the pin is recorded.
  - **`core/tagging.tag_line`** is the only caller. It builds the Lichess puzzle shape (the position before the opponent's move, that move, then the solver's line trimmed to end on a solver move), stops at the first illegal move, and keeps only the keys in `core/themes.py` (`themes.is_known`). The tagger's internal keys `coercion`, `collinearMove`, `overloading` and `simplification` aren't Lichess puzzle themes and are dropped. A puzzle with no previous move (an imported file) gets a null move in its place.
  - **The generator's rules are ported** into `core/puzzle_gen.py` (Adam, v0.10 planning), not copied: they're small, and the code around them is the part we can't use.
- Alternatives: a git dependency through uv (rejected: the repo has no package metadata); writing our own tagger (rejected: the themes must match the DB exactly); copying `generator.py` (rejected: its MongoDB, tablebase and server imports).
- Consequences: an upstream tagger fix needs a manual re-vendor (Developer Guide, *Dependencies*). The combined work was already AGPL (REQUIREMENTS §15).

### 2026-11-04, v0.9: QA fixes (v0.9-B1 to B6)
- Context: QA round 1 (`qa/QA-v0.9.md`), PASS WITH ISSUES: six minor bugs.
- Decision:
  - **B1:** `FeatureModelPicker` keeps the choice being saved in state, and every change builds on it, so a reasoning change made before a model change's save returns no longer resends the old model.
  - **B2:** the cache key includes the grading thresholds, since the grades are in the prompt (the User Guide already said new thresholds give a new explanation).
  - **B3:** Train these keeps Match ANY/ALL. It switches **Puzzles from** to Lichess only when it was My puzzles, and clears ratios, because themes need both; the dialog and the User Guide say so.
  - **B4:** the Game Review picker is searchable and offers **Use “<typed ID>” with Anthropic / OpenAI** for a valid ID that isn't listed (FR-1.3's typed IDs).
  - **B5:** Settings and the startup page always show the Game Review block, so it can be set up on its own provider with puzzle Explain off.
  - **B6:** the mock's move explanation no longer contains literal markup (the user-guide screenshot showed it). Escaping stays covered by the puzzle Explain mock and tests.
- Consequences: each fix has a regression test (QA's xfail tests now pass).

### 2026-11-04, v0.9: Game Review AI from the stored analysis, cached with the analysis settings
- Context: Explain this move and Explain my game (FR-11.17–11.21) need grounded, anonymized context and the v0.7 guardrails, without a second analyzer (CLAUDE.md: one pipeline).
- Decision:
  - **Built from `game_analysis` only** (`core/game_explain.py`): no engine call. Explain this move turns a `MoveRow` into Explain's own `ExplainInput` (the position before the move, `NO_PREMOVE`, Stockfish's best line cut by `saved_line` as the "solution", the played move as the refutation, and a new optional `GameMoveFact`), so `core/explain.validate()`, `Explanation`, the DTO and `ExplainPanel`'s view are reused unchanged. Explain my game has its own strict schema and `validate_narrative`: a moment must be one of the key moments sent and name the move played there; its better line must start with Stockfish's best move and be legal; annotations need valid squares.
  - **Anonymized by construction** (FR-8.16, 11.19): the narrative's move list is rebuilt as SAN from the UCI moves, never cut from the PGN text, so headers, names, ratings, dates, URLs, clocks and comments can't leak. `tests/unit/test_game_explain.py` checks a PGN full of them, and the live test checks the request that really went out.
  - **Cache keys** in the existing `llm_cache` (no migration): `game:<id>:<think_s>|<engine>|<thresholds>:move:<ply>` (thresholds added for v0.9-B2) and `…:narrative:<N>:<the key-moment plies>`, with provider and model, hashed. Including the analysis settings and the plies goes beyond FR-11.20's (game, ply / N, provider, model): a re-analysis or new thresholds never bring back an answer grounded on other evals (REQUIREMENTS FR-11.20 updated).
  - **`ai_reviewed`** is a value of the existing `games.analysis_status` (foreseen in `0007_games.sql`). `GamesRepo.mark_ai_reviewed` sets it only from `analyzed`; re-analysis writes `analyzed` again.
  - **The recommended preset** (FR-11.18, minimal per Adam): `core/preset_suggestion.validate_preset` keeps up to 3 known motif or mate theme keys and a rating range that passes `FilterSpec.validate`; anything else is dropped and counted. The prompt lists the allowed keys. Train these is a front-end action on your click, after a confirm.
- Alternatives: a `game_ai` table (rejected: `llm_cache` already holds validated results by key, and the status is one column); passing the PGN with headers stripped (rejected: a stripping bug would leak; rebuilding from moves can't).
- Consequences: the Coach (v0.10) can reuse `preset_suggestion` and the narrative validators. A game's AI notes are lost from view, never from the cache, when its analysis changes.

### 2026-11-04, v0.9: A model per AI feature: request kinds, `llm.feature.*` keys, one gate
- Context: FR-1.15. Puzzle Explain and Game Review need different models; keys, prices, the cap and the budget stay shared.
- Decision:
  - `core/llm/defaults.py` gains `FEATURES` (`explain`, `game_review`), request **kinds** (`explain`, `game_move`, `game_narrative`) with their own `MAX_TOKENS` (1,500 / 1,500 / 4,000, FR-8.14), and `FEATURE_OF` (kind → feature). `LlmUsageService.quote/run` take the kind; the feature picks the config and is what `llm_usage.feature` records.
  - `LlmSettingsService.config(feature)` resolves a feature's provider, model and reasoning. Explain keeps the v0.7 keys, so nothing migrates. Other features use `llm.feature.<feature>.provider` (`same` or unset: follow Explain's provider and model), `.model` and `.reasoning` (Low by default). The launch check (FR-1.6) tests each distinct provider and model in use.
  - Bridge: `set_llm_feature`; `LlmSettings.features[]` lists each feature's choice, effective provider and model, readiness, this month's spend (`LlmUsageRepo.spent_by_feature`) and its model options with the cost of that feature's typical request (Explain my game for Game Review).
  - Front end: `FeatureModelPicker` is the one Game Review picker, used in Settings → AI, on the startup page (both pickers, Adam) and on the Review page next to Explain my game (Adam). It shows a key field when the chosen provider has no key.
- Alternatives: per-feature caps (rejected at planning: one cap and one budget are simpler to reason about); copying Explain's model into Game Review's setting (rejected: "Same as Explain" keeps following it).
- Consequences: the Coach (v0.10) adds `coach` to `FEATURES` and its kinds to `MAX_TOKENS` / `FEATURE_OF`; the bridge and the picker pick it up from `features[]`.

### 2026-11-04, v0.8: QA fixes (v0.8-B1 to B12)
- Context: `qa/QA-v0.8.md` round 1: FAIL, with one major bug (B4) and eight minor ones.
- Decision:
  - **B1:** changing the grading thresholds regrades every stored move from its stored evals (`core.game_review.regrade`, `GameAnalysisRepo.regrade`), with no engine pass.
  - **B2:** a puzzle file over 20,000 entries, or a game file over 500 games, says so in the report or the list, instead of dropping the rest silently.
  - **B3:** without Stockfish, a Retry move that isn't in the stored lines can't be graded. It's neither recorded nor counted, and it gets no reason chips.
  - **B4:** Name the idea and Danger spotting always start on Lichess DB. The front end switches the source along with the mode, so the locked control and the session agree.
  - **B5:** the chess.com username typed for a URL import is linked when none is, so it detects your color and isn't asked again.
  - **B6:** My puzzles show no Lichess link, no rating change and no empty Themes line, and the Rated text says they never count.
  - **B7:** Review shows at most 8 moves of an engine line, and the lines wrap.
  - **B8:** a puzzle from your games says so when Stockfish is missing and only its saved line counts (`PuzzleView.strict_without_engine`).
  - **B9:** the User Guide states the decided-position rule exactly.
  - **Round 2 (B10–B12):** a game analyzed while the thresholds changed is graded with the new ones at the end (B10). The chess.com name typed for a URL import is linked only once the game is found, and it's used for the color either way (B11). Blank CSV rows don't count toward the 20,000-entry cap (B12).
- Alternatives: B1, marking games *not current* to force a re-analysis (slow, and the evals don't change); B4, unlocking the control in those modes (they can't serve your puzzles).
- Consequences: each bug has a regression test. QA's strict-xfail tests for B1–B6 now pass unmarked, and B2 (game files), B7 and B8 have their own.

### 2026-11-03, v0.8: My puzzles in the session: negative keys, no pre-move, the engine tolerance
- Context: decision 3 promised `my:` puzzle refs. The session's queue holds integer keys into `puzzles.db`, every mode applies `moves[0]` (the opponent's move) first, and puzzles saved from games need the 30 cp tolerance (Adam, v0.8 planning).
- Decision:
  - **One source for the session and the mixer:** `adapters/db/repos/puzzle_sources.py` (`CombinedSource`) wraps `LichessDbSource` and `CustomPuzzleSource`. Your puzzles use the **negated** `custom_puzzles.id` as their key, so one queue and one served set hold both. Their keys never change, so they survive a puzzle-DB re-import. **Both** gives each slot to your pool with probability (your pool) / (both pools).
  - **No pre-move:** a custom puzzle is an ordinary `Puzzle` whose `moves[0]` is `NO_PREMOVE` (empty). `start_position` then starts from the FEN itself. Lengths (`len(moves) // 2`), Commit the line, Show answer and the outcome's solution (`moves[1:]`) work unchanged. The front end already handles an empty opponent move (Danger spotting).
  - **The tolerance lives in the session, not the mode:** before Standard mode sees a move on a tolerance puzzle, `SessionService._tolerate` asks the interactive engine (best line, then the position after your move). If your move is within the tolerance, the rest of the line is rewritten from your move with the engine's continuation, cut to end on your move. The mode then sees it as the expected move. Without Stockfish, or if the engine fails, the stored line is checked as it is. Commit the line always grades the stored line.
  - **What reads attempts:** Spaced repetition replays `my:` attempts too (`srs_rows` names them `my:<id>`). The history filters use `MY_SOLVED` and `MY_MISSED` on the `my` source. Stats take a `my:` puzzle's length from `custom_puzzles`. A `my:` attempt is always `local` and stores no puzzle rating.
  - **Lichess-only:** ratios, the non-random orders, Name the idea and Danger spotting (validated in `FilterSpec` and `SessionService.start`). No `SAVED_FILTERS_VERSION` bump is needed, because the new fields' defaults are what older presets mean.
- Alternatives: a separate queue per source (every queue path would branch); synthesizing an opponent pre-move for custom puzzles (an imported book position has none); tolerance inside `StandardMode` (core does no I/O).
- Consequences: a tolerance move costs one or two interactive searches (about the engine think time each). A wrong move on a tolerance puzzle is only wrong after the engine has looked.

### 2026-11-03, v0.8: The background engine and the analysis queue
- Context: decision 12 reserved a second Stockfish process for game analysis, so the trainer never waits behind it. FR-11.31 asks for one job at a time and no repeat analysis at the same settings.
- Decision:
  - **`EngineService` owns the background engine** as a second `EngineClient` instance with its own lock, started lazily on the first game search and closed with the interactive one. It gets one thread fewer than the interactive engine (at least 1). `analyse_background` returns raw White-relative lines. No new `EngineClient` methods.
  - **`services/analysis.py` (`AnalysisService`)** keeps an in-memory FIFO queue drained by one `game_analysis` job. A `_draining` flag, set under the queue lock, decides whether a newly queued game joins the running job or starts a new one, so a game queued as the job exits can't be stranded. Cancel clears the queue. Each game's rows are stored in one transaction, so a cancelled game keeps its previous analysis or none.
  - **"The same settings"** means the same think time and the same `engine_id()` (the engine's name). Changing either makes a game *not current*, but nothing re-analyzes until you ask.
  - **Grading is pure** (`core/game_review.grade_game`): it takes the engine lines of every position, and the final position's lines give the last move's refutation. The refutation of every move is stored (`refutation_uci`), so the Review screen needs no live engine call.
- Alternatives: one engine with a priority queue (a 0.3 s background search would still delay a refutation); a fresh engine process per game (slow to start, and no shared hash).
- Consequences: a second Stockfish process (about the hash size in memory) while games are analyzed. A test proves a puzzle refutation returns at once while the background engine is blocked mid-search.

### 2026-11-03, v0.8: Game clients: chess.com serialized by a lock, ETags in `http.py`, hand-written fixtures
- Context: chess.com's Published-Data API answers parallel requests with 429 and asks for ETag caching (FR-10.7). Lichess exports your own games fastest with your token. Neither API had a client yet.
- Decision:
  - `adapters/chesscom.py` (`ChesscomGames`) holds **one lock around every request**, so calls from any thread go out one at a time. It accepts only `api.chess.com/pub/…` URLs (FR-11.32), waits on 429 (`Retry-After`, else a doubling backoff, 4 tries), and maps 404 to `ChesscomNotFound` and 410 to `ChesscomGone`.
  - `HttpClient.get_json_cached(url, etag)` sends `If-None-Match` and returns a 304 as data, not an error.
  - `adapters/lichess_games.py` (`LichessGames`) streams `/api/games/user/{u}` as ndjson and fetches single games from `/game/export/{id}` as JSON, both with the documented flags.
  - There's no single `GameSource` protocol: `core/games.py` has `LichessGamesClient` and `ChesscomClient`, because the two APIs share nothing but the PGN.
  - The fixtures under `tests/fixtures/http/chesscom/` and `lichess_games/` are generated from the API docs with legal PGNs, until Adam's live recorder replaces them. The scrub test now also rejects real chess.com game URLs, player API paths, PGN player tags and player names or ids in these responses (SR-12a).
- Alternatives: a delay between chess.com requests instead of a lock (it doesn't stop two threads overlapping); retrying 429 inside `http.py` for every caller (Lichess's batch sync must never resend).
- Consequences: a sync and a URL import can't hammer chess.com together. They queue behind the lock instead.

### 2026-11-03, v0.8: The game library and custom-puzzle schema (`user/0007_games.sql`)
- Context: §4.3 sketched `games`, `account_sync`, `game_analysis` and `custom_puzzles`. v0.8 fills them in and adds Retry mode results.
- Decision:
  - **`games`** is keyed by `(source, source_game_id)` when the platform gives an id. Pastes and files are deduplicated by `moves_hash` (SHA-256 of the start FEN and the UCI moves), so identical moves reuse the stored analysis (FR-11.7). Two platform games with different ids are never merged, even with identical moves (a short trap gets played many times); a platform copy adopts an earlier paste of the same moves.
  - Player names and ratings are stored per color (`white`, `black`, …) rather than as *user/opponent*, because your color can be unknown at import, and *Review both sides* exists.
  - `analysis_think_s` and `analysis_engine` record what the stored analysis used, so a game is never analyzed twice at the same settings (FR-11.31).
  - **`game_analysis`** keeps one row per ply with evals as `{"cp"}`/`{"mate"}` JSON from the mover's view. `themes` stays NULL until the v0.10 tagger.
  - **`custom_puzzles`** holds puzzles saved from games (`origin` manual) and imported files (`origin` import). `fen` is the position you solve, with no opponent pre-move, unlike §4.2. `strict` picks exact checking (imports) or the engine tolerance (games). It has two partial unique indexes: one per game and ply, and one per imported set, position and line.
  - **`retry_attempts`** is a separate log: retries aren't puzzle attempts and never sync.
  - The `game_errors` view waits for its first reader, the v0.10 Coach.
- Alternatives: storing Retry results in `attempts` (they have no `PuzzleRef`, and every attempts reader would need to exclude them); a full UNIQUE on `(game_id, ply)` (SQLite treats NULLs as distinct anyway, but the partial index states the intent).
- Consequences: the Coach (v0.10) and fix tracking read `game_analysis` directly. Coach-made puzzles reuse `custom_puzzles` with `origin = coach`.

### 2026-11-03, v0.7: QA fixes (v0.7-B1 to B7)
- Context: `qa/QA-v0.7.md` round 1: PASS WITH ISSUES, seven minor bugs.
- Decision:
  - **B1:** python-chess's `parse_san` accepts a null move (`--`, `Z0`, `0000`, `@@@@`) without a legality check, so `_variation` now also requires the move to be in `legal_moves`.
  - **B2:** a key for one provider is refused if it also matches a *longer* prefix that belongs to another provider: `sk-ant-` starts with OpenAI's `sk-`. The same rule is in `set_test_token.py`'s `KEY_SHAPE`.
  - **B3:** a price row's "as of" must be a real date (`date.fromisoformat`), not just the right shape.
  - **B4:** an emptied cap or budget field keeps the saved amount instead of saving $0.
  - **B5:** the spend indicator opens Settings scrolled to AI explanations (`focusAi`).
  - **B6:** the model field's dropdown lists every model while a picked model is in the box; typing anything else filters it.
  - **B7:** the version is 0.7.0. `test_version_matches_the_branch_being_built` now derives the expected version from the newest `plans/v0.x.md`, so it can't go stale again.
- Alternatives: B4, refusing an empty field with an error (keeping the old value is what the engine settings do); B7, keeping a hard-coded version in the test (it's what let 0.6.0 slip through).
- Consequences: each bug has a regression test: QA's pinned tests (B1–B5) now pass, and B6, B7 and the script side of B2 have their own.

### 2026-11-03, v0.7: Front end for the AI settings, the spend indicator and Explain
- Context: FR-1.2–1.4, 1.6, 1.8, 1.10 and FR-8.1–8.8 on screen.
- Decision:
  - **One store for the settings:** `web/src/state/llm.ts` keeps one copy of `LlmSettings` for the header's `SpendIndicator`, `AiSettingsPanel` (on the startup page and in Settings → AI), and `ExplainPanel`. Every setter's result is published, and finished `explain` / `llm_key_test` / `llm_launch_check` jobs refresh it. Nothing is kept in browser storage, and the store holds no key.
  - **The key field** is a masked input that empties after **Save key**: the key crosses the bridge once, inward.
  - **The model field** is a Mantine `Autocomplete`: the price table's models with their cost per Explain, or any typed ID.
  - **Show me** reuses the trainer's existing line-preview stepper, extended with per-position `shapes` (drawn through `Board`'s new `shapes` prop on chessground's auto shapes) and `notes`.
  - **The fast path (FR-1.6)** hides the full form unless the launch check failed.
  - **The mock's AI side** is its own module, `web/src/api/mockLlm.ts`, with `?ai=on|warn|over|failed|nomodel` scenarios. Its explanations follow the real solution and always carry one discarded annotation, so the FR-8.4 note can be tested.
  - **Text rendering:** the AI's text goes into React text nodes only; a test checks that the HTML in the mock's summary shows as text.
- Alternatives: a modal confirm before each Explain (FR-8.11 says inline, no confirm); a separate board for the explanation (the stepper already exists).
- Consequences: Game Review AI (v0.9) can reuse `ExplainPanel`'s pattern and the same stepper.

### 2026-11-03, v0.7: Explain: grounded facts, a strict schema, validation against the real position, a cache
- Context: FR-8.1–8.8; Adam's v0.7 planning decisions (Explain requires Stockfish; it also works in Danger spotting).
- Decision:
  - **When:** `SessionService.explain_facts` gathers the facts only once the puzzle is over (`_finished`, the same gate as the engine, FR-7.3) and only with Stockfish ready.
  - **Scoring:** the ladder puts Explain after Show answer, which already decided the attempt, so Explain never changes a result (`help_used = 'explain'` stays unused).
  - **The facts (`core/explain.py`, an allowlist, SR-11):**
    - the position and side, the opponent's move, and the solution in SAN and UCI per ply;
    - the themes (display names);
    - python-chess facts per ply: the piece, any capture, check or mate, what the moved piece attacks, and who attacked and defended the square;
    - Stockfish's top 3 from the solving position (evals worded from the solving side, also in Danger spotting) and the refutation of your wrong move;
    - Commit the line's entered line, and Danger spotting's candidate, call and truth.
    - Never the puzzle ID, its rating or any setting (a test checks the ID).
  - **Schema:** strict-mode shaped for both providers: every property required, `to` nullable, no extra properties. Each step echoes its ply's `move`, and an optional `variation` of SAN moves gives the legality check (FR-8.4) something to replay.
  - **Validation drops and counts** a step whose move isn't the solution's at that ply (or a ply that doesn't exist, or a repeat), any variation with an illegal move (the whole variation), any annotation with a bad square, kind or color, and annotations over 6. It also caps text and strips control characters.
  - **Text:** HTML in the text is kept as text: the UI renders it escaped (FR-8.7).
  - **The quote** builds the prompt without the engine plus a 700-character allowance, so the price on the button costs no search.
  - **The run:** a job that searches, calls `LlmUsageService.run`, and validates. Truncated, refused or unparseable answers are errors (the usage is still logged, since they were billed), and nothing is cached for them.
  - **The cache** holds the validated result, keyed by SHA-256 of (puzzle ref, mode + call/entered line + wrong move, provider, model), as FR-8.6 lists. A result is shown only while its puzzle is on the board.
- Alternatives: letting the LLM name arbitrary moves in free text (unverifiable); Show me drawing the LLM's own move list (it could disagree with the solution); keying the cache on the prompt text (engine output varies run to run, so it would never hit).
- Consequences: Game Review AI (v0.9) can reuse the schema-and-validate pattern with its own facts builder.

### 2026-11-03, v0.7: Anthropic and OpenAI over `adapters/http.py`, no SDKs
- Context: FR-8.1 needs both providers behind one interface, and ARCHITECTURE §3 decision 9 sends every external call through the one HTTP client.
- Decision:
  - **Raw JSON adapters:** `adapters/llm/anthropic.py` (`POST /v1/messages`, `anthropic-version: 2026-10-21`, `x-api-key`) and `adapters/llm/openai.py` (`POST /v1/responses`, Bearer key, `store: false`). They implement `core/llm/provider.py`'s `LLMProvider`.
  - **Request shape:** structured output is a JSON schema (`output_config.format` / `text.format` strict). The reasoning setting becomes `output_config.effort` / `reasoning.effort`; there's no "off" because current Claude models such as Opus 5.5 refuse `thinking: disabled` (FR-8.15). `max_tokens` / `max_output_tokens` is always set (FR-8.14).
  - **Never retried:** generation requests use `retry=False`, so a timeout that was still processed can't be billed twice.
  - **Test key:** `GET /v1/models/{id}`, which is free (FR-1.4). The model ID is URL-quoted.
  - **`http.py` additions:** per-request `headers=` and `timeout=`, `HttpError.timeout`, and `HttpError.error_code`. The error code is the API's short machine code from a JSON error body (`insufficient_quota`, `authentication_error`), kept only if it matches `[a-z][a-z0-9_]{0,39}`; the provider's message text is never kept or shown (SR-7).
  - **Errors:** `adapters/llm/__init__.py` maps status and code to the readable kinds in `core/llm/provider.py` (FR-8.8). For example, OpenAI's 429 `insufficient_quota` is *quota*, not *rate limited*.
  - **Redaction:** log redaction also covers `x-api-key` headers and JSON fields.
  - **Fixtures:** the shapes come from Anthropic's docs and the openai-python SDK's types. `anthropic_messages.json` in `tests/fixtures/http/llm/` was recorded from Adam's live run (2026-11-03: the Anthropic request shape, `anthropic-version: 2026-10-21` and `output_config` confirmed against the real API). `openai_responses.json` stays hand-written until a live run with an OpenAI key.
- Alternatives: the `anthropic` and `openai` packages (two dependencies, their own HTTP stacks bypassing `http.py`'s User-Agent, timeouts and redaction, and their own retries, which could double-bill).
- Consequences: provider API changes are ours to follow; the adapter tests pin the shapes. Adding a provider is one adapter file plus a `PROVIDERS` entry (Developer Guide recipe).

### 2026-11-03, v0.7: The cost guardrails: price table, usage log, one gate for every request
- Context: REQUIREMENTS §9.3 and Adam's v0.7 planning decisions (no model pre-selected; the budget blocks at 100%).
- Decision:
  - **user.db `0006`:** `llm_prices` (primary key provider + model, with an optional long-context tier), `llm_usage` (one row per response that reported usage, including truncated and refused ones, with `local_month`) and `llm_cache`.
  - **Seeding:** the price table is seeded from `core/llm/defaults.py`, the only module that names models (a contract test checks `src/` and `web/src`, mock data aside). Seeding runs lazily and once per `SEED_VERSION`, adding missing rows only, so a row you edited or deleted stays as you left it.
  - **`services/llm_usage.py`'s `run()` is the only way to call a provider.** It resolves the provider, model, key and price row (no price row, no request), estimates the request, applies `core/llm/guardrails.check`, sends it with `max_tokens_for(feature, reasoning)`, and logs the reported usage priced from the table.
  - **The checks:** the budget is checked first (month spend ≥ budget blocks). Then the per-run cap is checked against the worst case: input estimated at characters ÷ 3, plus the full `max_tokens` of output.
  - **One at a time:** requests are serialized under a lock, so the budget always sees fully-logged spend.
  - **Local month:** the month is the local calendar month (`Clock.local_date`), stored on each row so SQL never does timezone math. Thresholds compare with a 1e-9 tolerance, so float sums like $0.02 + $0.02 still warn at exactly 80%.
  - **Settings and keys:** settings are `llm.*` keys in `settings`. Keys are in `secret_store` under the account names `anthropic` / `openai`. The service accepts a key only if it has the provider's prefix (`sk-ant-` / `sk-`), so a key pasted for the wrong provider is caught, and it never returns a key, only *stored: yes/no*.
- Alternatives: seed rows in the migration SQL (puts model names outside the defaults module, and a deleted row would be impossible to tell from a missing one); checking the budget against the worst case too (Adam chose "block only at 100%"); a provider tokenizer call for the estimate (OpenAI has none, and Anthropic's is an extra round trip).
- Consequences: every later LLM feature (Game Review AI, the Coach) calls `run()` with its own `feature` and `MAX_TOKENS` entry and gets the guardrails for free.

### 2026-11-03, v0.6: QA fixes (v0.6-B1 to B10)
- Context: `qa/QA-v0.6.md` rounds 1 (two majors, six minors) and 2 (B9, minor).
- Decision:
  - **B1:** `_danger_candidate` runs the MultiPV search for **every** Danger puzzle, before the coin flip, so a puzzle's load time no longer tells safe from blunder (it did on 14 of 14 in the real app). The trainer says "Preparing the position…" while it waits.
  - **B5:** `SessionService._player` words evals from the punishing side once you called the real blunder Unsafe (the refutation of a wrong punishing move, the engine panel and the analysis board after it).
  - **B3:** one refutation search per puzzle: concurrent `get_refutation` calls (the reason prompt and the "Why your move fails" panel) wait on the running search (`_Current.refuting`).
  - **B4:** think time for Rushed starts when the trainer has shown the position: `core/modes/base.py` `OPPONENT_DELAY_MS` / `REPLY_DELAY_MS`, equal to `TrainerView`'s animation delays (`tests/contract/test_trainer_delays.py`).
  - **B6:** the session bar's "All time" leaves Danger spotting out, like the Stats totals.
  - **B2:** the note you're writing lives in `TrainerView`, so keys 1–6 save it as clicks do; a note over 200 characters is left out and the reason still saved.
  - **B9:** Stockfish finishes a forced position early, and forced positions are the ones with no safe move, so a fast load still meant "Unsafe". `TrainerView` keeps every Danger load on "Preparing the position…" for at least the engine think time (read from `get_engine_settings` at every Danger load, so a think time changed mid-session counts at once: B10). It's padded in the UI, which is where the timing shows, rather than with a sleep in the session service.
  - **B7, B8:** the safe verdict's wording, whole-number evenly labelled y ticks on the reason trend (`interval: 0`), and no promise of an unshipped feature in the User Guide.
- Alternatives (B1): padding blunder loads with a sleep (still a timing side channel under load; and the search may as well be real); prefetching (see the session entry).
- Consequences: every Danger puzzle costs one engine search (about the think time) to appear.

### 2026-11-03, v0.6: Front end for Name the idea, Danger spotting and the reason chips
- Context: the trainer view and the filters panel for FR-4.3, FR-4.4 and §7.3, and the Stats additions.
- Decision:
  - The Modes control became a **vertical** segmented control: five modes don't fit one row in the panel. The depth-ladder order is disabled outside Standard and Commit (`LADDER_MODES` in `state/modes.ts`), with a note if it was already chosen.
  - `TrainerView` gains two branches like Commit's: **Name the idea** keeps the board read-only until `set_idea_tags` succeeds (`components/IdeaTags.tsx`); **Danger spotting** shows the raw position with an arrow on `candidate`, a call panel (`components/DangerCall.tsx`, keys **S**/**U**), and after a correct Unsafe flips the board to the punishing side for one move. The engine panel's start position is the raw FEN in Danger spotting (no opponent move).
  - The idea pickers' lists live in `web/src/state/ideas.ts` (keys and names), kept equal to `core/themes.py` by `tests/contract/test_idea_lists.py`, rather than another bridge call for a fixed list.
  - **Reason chips** (`components/ReasonChips.tsx`) sit **below the board** (FR-5.8): in the side column they pushed the engine panel off-screen and the page scrolled. They're asked for (`get_reason_prompt`) once the lost puzzle is over, and survive Try again. Keys 1–6.
  - Stats: a **Why you missed** tab (`components/ReasonStatsPanel.tsx`) with a stacked weekly bar chart. Its colors are categorical slots 1–5 of the dataviz reference palette, validated against Mantine's light (`#ffffff`) and dark (`#242424`) surfaces; three light steps are under 3:1, so the chart always has its legend (kept in stack order with `itemSorter: null`) and a table view.
- Alternatives: a Select for the Modes control (hides the choices behind a click); reason chips in the side column (see above); serving the idea lists over the bridge.
- Consequences: the trainer view has three mode branches now (Commit, Name, Danger). A new mode that is played move by move still needs none.

### 2026-11-03, v0.6: Session, bridge and Stats for the new modes and mistake reasons
- Context: wiring FR-4.3, FR-4.4 and §7.3 through `SessionService`, the bridge and the Stats page.
- Decision:
  - **Danger spotting picks its candidate in `next_puzzle`**: a coin flip on the injected `rng` (or the owed safe slot), then, for a safe slot only, `validate_fen` → the **interactive** `EngineService.analyse(..., multipv=5)` from the blunderer's side. The session refuses to start without a ready engine (`engine_not_installed`). An engine failure on one puzzle shows the blunder and owes a safe one, rather than failing the session. `PuzzleView` gains `candidate`, and `opponent_move` is empty in this mode, so the real blunder never crosses the bridge before the end (pinned by a test). Danger attempts are recorded with no sync fields (`local`), `rated` forced off, and are excluded from `srs_rows` and the FR-3.9 history subqueries (`SOLVED_IDS`, `MISSED_IDS`).
  - **The reason prompt lives on the session** (`reason_prompt`): what the FR-5.9 rules need is captured when a loss is recorded (`_ReasonBase`), and the refutation part comes from the cached `get_refutation` (fetched if an engine is ready). The front end asks once the puzzle is over. `ReasonsService.set_reason` validates and appends; it takes the suggestion from the session (`suggestion_for`) rather than from the UI. Try again keeps the chips' attempt.
  - **Misclicks are excluded in SQL by the latest reason** (`LATEST_REASON` / `NOT_MISCLICK` in `repos/user_data.py`): the session and all-time tallies, the depth-ladder window and the Stats rows. The sync queue never reads `mistake_reasons`, so a misclick is still sent as a loss.
  - **Stats**: Danger-spotting attempts count in By mode and the new mode details only, not overall or per theme, length or rating (spotting the danger isn't solving the puzzle). `get_reason_stats(theme, mode)` returns the breakdown and a trend by local calendar week (the injected clock's `local_date`).
  - Bridge: `set_idea_tags`, `call_danger`, `get_reason_prompt`, `set_mistake_reason` and `get_reason_stats` (allowlist updated); `UiSettings.reasons_ask` / `rushed_s` (`reasons.ask`, `reasons.rushed_s`); `dto.TrainingMode` names the five modes once.
- Alternatives: prefetching the next Danger candidate in the background (saves about the think time per safe puzzle, but needs a second engine request path and cancellation; not needed at a 1 s default); a `reason` column updated in place (see the entry below).
- Consequences: loading a safe Danger puzzle waits for one engine search (the UI shows "Preparing the position…"). Changing a reason re-counts everything at once, since nothing is cached.

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
