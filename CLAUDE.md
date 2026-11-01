# CLAUDE.md: WeakSquare Chess Trainer

An open-source (AGPL-3.0-or-later), single-user Windows desktop app for chess tactics training on the Lichess puzzle database. Read these before starting any work:
- **REQUIREMENTS.md**: what to build (the source of truth for behavior)
- **ARCHITECTURE.md**: how the code is organized (layers, layout, locked decisions)
- **ROADMAP.md**: which version you're building now, and its *Done when* checklist
- **docs/DEVELOPER_GUIDE.md**: the commands to set up, run and test the app

## Stack
- Python 3.12+ backend, pywebview window (WebView2), SQLite
- python-chess (rules plus UCI control of a native Stockfish 19, downloaded by the engine installer (FR-7.5) and never committed)
- Front end: React + TypeScript + Vite + Mantine (components), chessground (board) + chess.js (legal moves). All assets local, no CDNs. The UI talks only to the `ApiClient` interface (real pywebview client + mock client).
- keyring (Windows Credential Manager) for secrets
- LLM providers: Anthropic and OpenAI behind one `explain()` interface

- Game Review + Coach: Lichess + chess.com game import/fetchers, Stockfish analysis, lichess-puzzler tagger (AGPL-3.0)

## Build order (ROADMAP.md)
- Build **one version at a time**, in order (v0.1 → v1.0 → v1.1 macOS/Linux → v2.0 opening trainer). Ask Adam which version is current if it's unclear.
- **Build only what the current version lists.** You may add an *interface* a later version will implement (ARCHITECTURE.md §4), but no placeholder code, no dead UI and no "while I'm here" features.
- Follow the 9-step process in ROADMAP.md ("How every version is built and tested"): plan → build → self-check → **run the `qa-tester` subagent** → fix loop → tag `v0.x-rc1` + handoff → **stop** for Adam's manual test → fixes → Adam signs off → tag `v0.x`. Don't start the next version until Adam signs off.
- Every bug fix (from QA or Adam) comes with a regression test.
- Respect the layers: `core/` does no I/O; only `app.py` wires concrete adapters; only `adapters/secret_store.py` imports keyring; every external call goes through `adapters/http.py`.
- Follow ARCHITECTURE.md §3 decisions 12–17 exactly:
  - **Threads:** never share a SQLite connection between threads; get one from `adapters/db/connection.py`. Trainer engine requests use the interactive engine, never the background one.
  - **Bridge:** `Api` keeps dependencies in underscore attributes. Every public method uses `@bridge_call`. Adding a method means updating the allowlist test in the same commit.
  - **Front end:** never use localStorage, sessionStorage, IndexedDB or cookies. Persist through the bridge.
  - **Time and randomness:** never call `datetime.now()`, `time.time()` or the global `random` in `core/` or `services/`. Use the injected `Clock` and `rng`.
  - **Data:** dev runs and tests never use the default data folder (NFR-2).
- **Saving the plan:** save the approved plan to `plans/v0.x.md` as a checklist and tick items as they land. After a `/clear` or a context reset, re-read it before doing anything else.
- **Dependencies (SR-14b):** add a package only if it's in the approved plan. Check the exact name on PyPI or npm first. Use `uv add` and npm so `uv.lock` and `package-lock.json` stay in sync, and commit both. New dependencies get an ARCHITECTURE.md §7 entry.
- **Windows shells:** Adam's PowerShell runs with the **AllSigned** execution policy, which blocks unsigned `.ps1` files such as `npm.ps1`, `npx.ps1` and a venv's `Activate.ps1`. You run in Git Bash, where `npm` works, so a command that passes for you can still fail for him.
  - Commands written for humans (Developer Guide, README, handoff run command) use `npm.cmd`, `npx.cmd` and `uv run …`. They work in PowerShell under any policy, in cmd and in Git Bash.
  - Never write `.ps1` scripts or tell anyone to activate the venv.
  - Python scripts find npm with `shutil.which("npm")`, which resolves `npm.cmd`. A bare `subprocess.run(["npm", …])` fails on Windows.
- **Full-DB tests** are marked `@pytest.mark.fulldb` and skip when the full puzzle DB isn't imported. The normal suite uses the small fixture and must stay fast.
- Schema changes are **new migration files only**. Never edit an applied migration.

## Rules
- **Secrets (REQUIREMENTS.md §13, SR-7 to SR-16):**
  - Only `secret_store.py` may import `keyring`. Every other module calls `secret_store`.
  - Never read, print, echo or log a credential, including from the shell. A PreToolUse hook blocks attempts. If a step needs a real credential, stop and ask Adam to run it.
  - Never write a real-looking token or key into any file. Test placeholders are `lip_FAKE…` / `sk-ant-FAKE…`.
  - Recorded HTTP fixtures must be scrubbed when recorded. A test enforces this.
  - Fixtures are also **anonymized** (SR-12a): no real usernames, game IDs or URLs in a public repo.
  - Tests mock `secret_store`. Live tests are opt-in (`-m live`), use the separate `weaksquare-test` keyring entry (a scoped personal access token on Adam's own account, not a second account), always send `rated: false`, and push at most 3 solves per run.
  - Don't try to edit `.claude/`, `.gitleaks.toml` or `.pre-commit-config.yaml`. They're Adam's guardrails, and edits are denied.
- **Puzzle semantics:** FEN is *before* the opponent's move. Apply `Moves[0]` first, then the player solves from `Moves[1]`. Mate-in-one accepts any mating move. See §4.2.
- **Scoring:** any help (hint, answer, explain) before completion is a loss. Follow the angle reporting rules in §8.3 exactly. Never inflate ratings.
- **LLM output is untrusted:** validate every move and square before drawing, and render text escaped (never raw HTML).
- **No hard-coded LLM model names** outside the provider defaults module. **No hard-coded prices.** Costs come from the `llm_prices` table.
- **LLM spend guardrails are mandatory** (§9.3): pre-run estimate, per-run cap, monthly budget, hard `max_tokens` on every call. Never send raw PGNs (headers, clocks, comments) or batches of games to an LLM. Game Review may send **one** game's SAN move list, anonymized as You/Opponent. The Coach sends aggregates plus a few example positions, anonymized.
- **Fix tracking (§10.8):** a weakness's status is decided by its **game rate** over the rolling window against a frozen baseline, never by puzzle accuracy alone. Respect the sample-size guard. The Suggested preset never silently overwrites the user's manual filters.
- **Stockfish (§9.1):** never commit, vendor or hard-code a download of the binary. Install it only through `services/engine_install.py` (pinned manifest, SHA-256 checked before extracting). Validate every position and move list with python-chess before sending it, because Stockfish 19 terminates on invalid input.
- **One analysis pipeline:** Game Review (v0.8) builds `game_analysis`, and the Coach (v0.10) reuses it. Don't write a second analyzer.
- **chess.com API:** one request at a time (no parallel calls), descriptive User-Agent with the repo URL as contact, ETag caching. Use the Published-Data API only, **never** chess.com's internal "callback" endpoints. Treat every archive field except the documented core as optional.
- **Game sync fetches metadata and PGNs only.** Analysis runs only when the user asks (Review / Analyze selected / Coach).
- Read the puzzle CSV by header name. Never touch user tables during a re-import.
- Keep the backend thin and testable. Use pytest for the importer, filters, scoring, angle rules, sync batching and annotation validation.
- If a decision changes, update REQUIREMENTS.md in the same change.

## Documentation (update as you go, not at the end)
Docs change **in the same commit** as the code they describe. A version isn't done until its docs are.
- **CHANGELOG.md:** one line under `[Unreleased]` per user-visible change, following the rules at the top of that file.
- **docs/USER_GUIDE.md:** every feature, setting and screen the user can see, written for the person using the app ("you"), not for a developer.
  - Document **shipped features only**. The planned outline is the HTML comment at the top of the file; add a chapter when its version ships.
  - Task-first: what it's for, then the steps, then what each control does and any gotchas. Mark each section *Added in v0.x* (or *Changed in v0.x*).
  - Screenshots come from the Playwright docs spec (mock client, fixed data) into `docs/img/`. Regenerate them at every handoff; never hand-edit them.
  - Any feature that sends data off the PC says exactly what it sends, matching the "Your data and privacy" section.
- **docs/DEVELOPER_GUIDE.md:** the single source for commands. When you add or change a command, path, setting, migration step or workflow, update it there and replace the matching `TODO(v0.x)` marker. QA runs every command in it as written.
- **ARCHITECTURE.md §7 decision log:** add an entry for every new dependency, schema shape, protocol change or workaround, and update §2 if the layout changes.
- **README.md:** keep the one-paragraph description and status line true.
- Run `python scripts/check_docs.py` during the self-check and `--strict` before the handoff. Both must pass.

## Commands
See the Commands table in docs/DEVELOPER_GUIDE.md. Read it at the start of each session; it replaces this section.
