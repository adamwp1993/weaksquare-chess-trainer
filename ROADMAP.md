# Roadmap: versions and test checkpoints

Each version is a **checkpoint**. Claude Code builds that version, an independent QA agent verifies it, then Claude Code **stops** and hands it to Adam for manual testing. The next version starts only after Adam signs off. Requirement IDs refer to REQUIREMENTS.md.

## How every version is built and tested

Each version lives on a branch (`v0.x`), merged to `main` only after Adam signs off.

| Step | Who | What |
|---|---|---|
| 1. Plan | Builder (plan mode) | Reads CLAUDE.md, ARCHITECTURE.md, this version's section and its requirement IDs, then proposes a plan: files, interfaces, tests, any new dependency with its purpose, and anything out of scope. **Adam approves** before any code is written. The approved plan is saved to `plans/v0.x.md` as a checklist and ticked off as work lands, so a `/clear` or context reset can resume from the file. |
| 2. Build | Builder | Implements in small commits, running unit and integration tests as it goes. Each commit that changes behavior also updates CHANGELOG `[Unreleased]` and the affected docs (CLAUDE.md "Documentation"). |
| 3. Self-check | Builder | Full suite, `ruff`, `mypy`, `tsc --noEmit`, ESLint, `pre-commit run --all-files`, Playwright, the full-DB tests if the DB is imported, regenerate the user-guide screenshots, `python scripts/check_docs.py --strict`. Everything green before QA. |
| 4. Independent QA | `qa-tester` subagent | Fresh context. Verifies every *Done when* item and requirement ID with evidence, writes missing tests under `tests/`, runs a real-app smoke test (Playwright attached to the app's WebView2), explores edge cases, checks scope and security, and checks the docs against the app (runs every Developer Guide command, follows the new User Guide steps). Writes `qa/QA-v0.x.md`. Never fixes product code. |
| 5. Fix loop | Builder, then QA | The builder fixes every blocker and major issue, adding a regression test per bug. QA re-verifies those bugs and re-runs the full suite. At most 3 rounds, then escalate to Adam. |
| 6. Handoff | Builder | Add the rc to the CHANGELOG `Candidates:` line, commit, tag **`v0.x-rc1`**, and post: what's in, how to run it, known limits, the QA verdict, and the manual checklist below. Then **stop**. |
| 7. Manual test | **Adam** | Run the checklist, plus free exploration. Read this version's User Guide sections and CHANGELOG entry against what you see; wrong or confusing docs are bugs too. Log issues in `qa/manual-v0.x.md` (steps, expected, actual, screenshot). |
| 8. Fix and re-test | Builder, QA, Adam | Fix with regression tests → QA re-verifies → Adam re-checks only those items. Re-tag `-rc2`, `-rc3`… as needed. |
| 9. Sign-off | Adam, then builder | Rename CHANGELOG `[Unreleased]` to `[v0.x] - <date>` and open a new empty `[Unreleased]`, update the README status line, tag **`v0.x`**, merge to `main`. The next version starts in a **fresh session** (`/clear`). |

### Checkpoint gate (all must be true at step 6)
- [ ] All unit, integration, contract and Playwright tests pass; QA verdict is PASS or PASS WITH ISSUES (minor issues only).
- [ ] Static checks clean (`ruff`, `mypy`, `tsc`, ESLint), `pre-commit run --all-files` clean (gitleaks included), and CI green on the branch once the repo is on GitHub.
- [ ] No dependency added that wasn't in the approved plan; `uv.lock` and `package-lock.json` committed.
- [ ] Nothing from a **later** version was built (interfaces only, per ARCHITECTURE.md).
- [ ] `python scripts/check_docs.py --strict` passes (changelog and guides changed with the code, links resolve, no `TODO(v0.x)` left for this version or earlier).
- [ ] CHANGELOG `[Unreleased]` covers every user-visible *Done when* item.
- [ ] User-guide screenshots regenerated; QA ran every Developer Guide command as written.
- [ ] ARCHITECTURE.md §2 and §7 updated if the structure changed or a decision was made.

---

## v0.1: The puzzle mixer (MVP)
**Goal:** pick any mix of puzzles and solve them. Offline, no account, no engine.

v0.1 is too big for one sitting, so it's built in three internal steps, each committed and ticked off in `plans/v0.1.md`. QA runs once, at the end.
- **v0.1a Foundations:** scaffold, `setup.py`, data folder and single-instance lock, migrations with backup and newer-schema refusal, logging, the `@bridge_call` decorator with its allowlist test, injected clock and RNG, the real-app smoke harness, CI, About screen.
- **v0.1b Puzzle DB:** download, verify, import into a new file and swap.
- **v0.1c Mixer:** filters, queue, trainer, attempts.

Scope:
- Scaffold: repo layout, `pyproject.toml`, React/Vite/Mantine app, pywebview window, composition root, job runner, both DB migrations, `mockClient`.
- `scripts/setup.py`: one command for a fresh clone (uv if missing, the Python virtual environment from `uv.lock`, npm packages with `npm ci`, the Playwright browser, pre-commit hooks, the puzzle DB, a Start-menu shortcut). Safe to re-run. Later versions add their own steps to it.
- Robustness basics (§3 decisions 12–17; NFR-1 to NFR-7): thread-local SQLite connections, the bridge decorator and allowlist test, no browser storage, injected clock and RNG, the data-folder override and dev folder, backup before migrating and refusing a newer schema, rotating logs with crash hooks, clean shutdown, and an About screen.
- `.github/workflows/ci.yml` (Windows runner): `uv sync --locked`, `npm ci`, static checks, unit, integration and contract tests on the fixture, `check_docs.py`.
- **Real-app smoke harness:** a pytest fixture that launches the app with the WebView2 CDP port enabled (SR-16) and attaches Playwright, so QA can drive the real window and not just the mock.
- Puzzle DB: download plus hash check script, resumable background import with progress bar, into `puzzles.db` (FR-2.1–2.3, §4.2 semantics).
- Filters (FR-3.1–3.5): theme dropdown with grouped checkboxes, search, Select all/Clear, ANY/ALL; excluded themes; rating range slider; move-count dropdown (1/2/3/4+/All); side to move; **live match count**.
- Queue: random order, fixed N or endless (FR-3.11 random only, FR-3.12).
- Trainer: chessground board, **Standard mode** only, mate-in-1 acceptance, themes hidden until the puzzle ends (FR-3.14), wrong move = loss (FR-5.1, 5.3).
- Attempts saved in `user.db`. A session bar shows solved / failed / accuracy.
- **Docs:** every `TODO(v0.1)` in the Developer Guide filled in; User Guide chapters for first run, choosing puzzles and solving; a Playwright spec that regenerates the user-guide screenshots into `docs/img/` from the mock client with fixed data.

**Done when:**
- Unit tests prove FEN semantics against 10 known puzzles (color, first move, solution), plus the mate-in-1 alternative case.
- The filter count matches a direct SQL query for 20 random FilterSpecs, and returns in under 500 ms on the full DB (`-m fulldb`); building a 50-puzzle random queue from a 1M-puzzle pool also takes under 500 ms.
- A test proves the bridge exposes exactly the allowlisted methods; a test proves a newer-schema `user.db` is refused untouched; a test proves a migration writes a backup first.
- A cancelled import leaves the existing `puzzles.db` working.
- Playwright: set filters → solve 3 puzzles via the mock → session stats update.

**Adam's manual test:** run `setup.py` from a fresh clone → launch from the Start-menu shortcut → import the full DB → `fork AND long`, rating 1200–1600 → solve 10 → try ANY vs ALL and excludes → close and reopen (attempts persisted) → launch a second copy (the first window comes forward) → check the About screen paths.

---

## v0.2: Mixer complete + basics
- Remaining filters: phase/goal/origin groups, opening multi-select, quality thresholds, history excludes ("solved here", "only my misses") (FR-3.6–3.9).
- Ratios, ordering options, presets save/load/rename/delete (FR-3.10, 3.11, 3.13).
- Stuck ladder steps 1–2 **from the dataset solution**: Hint and Show answer, both counting as a loss (FR-5.2, §7.2). There's no engine yet.
- Basic Stats page: accuracy per theme, length and rating band (FR-9.1, 9.2).
- Keyboard shortcuts, auto-orient the board, coordinates toggle.
- **Dark mode** (FR-1.12): Light / Dark / Match system, saved in `user.db` through the bridge.
- **Importer wording** (FR-2.1a): the importer page and the User Guide say the download is the **whole** Lichess puzzle database, about 300 MB compressed (~6M puzzles, ~1.5 GB once imported).
- **Desktop shortcut and app icon** (NFR-8a): `setup.py` makes a desktop shortcut too (`--no-desktop-shortcut` to skip). The new icon (2×2 board squares with the black cburnett queen) is used on both shortcuts, the window and the taskbar.
- **Move sounds** (FR-1.13): move, capture, check, checkmate, castling, puzzle solved and failed; an on/off toggle and volume, saved in `user.db` through the bridge; licensed sound files with credits.
- **Puzzle DB update check** (FR-2.5): daily background check against database.lichess.org, a banner with export dates, download size and an approximate puzzle count, Update now / Not now / Skip this export, and exact new/removed counts after the import.

**Done when:** preset round-trip test; ratio sampling test (±5% over 1,000 draws); hint/answer recorded as a loss; the color-scheme setting round-trips through the bridge and is applied on relaunch, and a test proves no browser storage is used for it; Playwright checks the main screens in both Light and Dark; the importer page text names the full database and its ~300 MB size; User Guide screenshots include one dark-mode shot; update-check tests with recorded, scrubbed HTTP fixtures cover same hash (no banner), new hash (banner with dates and size), no hash in `meta` (falls back to dates), offline (silent), an unreadable puzzle count (line omitted), the once-a-day limit via the injected clock, and Skip this export; a test proves the new/removed counts against two fixture databases; unit tests map each move to the right sound (quiet move, capture, check, mate, castling, en passant, promotion with capture) and prove a mate plays only the mate sound; Playwright with a stubbed audio player proves sounds play when on, never when off, and that the setting persists through the bridge; `CREDITS.md` lists every sound file with an AGPL-compatible license; `setup.py` tests (with a fake shell call) prove it creates both shortcuts with the icon, honors `--no-desktop-shortcut` and `--no-shortcut`, uses the known-folder Desktop path, and doesn't duplicate on re-run; the `.ico` contains every size from 16 to 256 px and matches what the icon script builds from the SVG.
**Adam's manual test:** build a "Combo night" preset with a 50/30/20 ratio, save, reload, play 15 puzzles, check Stats. Switch to Dark, solve a puzzle and open every dialog (nothing unreadable), relaunch (still Dark), try Match system while toggling the Windows theme. Open the importer (☰ → Update puzzle database…) and check that the wording makes clear it's the full database. Relaunch with an older DB installed and check that the update banner appears with sensible details. Run the update and check the new/removed counts, then confirm that relaunching the same day doesn't check again. With sounds on, play puzzles with captures, checks and a mate, and listen for the right sounds, including the opponent's first move. Change the volume, turn sounds off (silent), relaunch (still off), and turn them back on. Re-run `setup.py`: a WeakSquare icon appears on your desktop (one, not two) and in Start, the icon looks right at desktop and taskbar size, and launching from the desktop works.

---

## v0.3: Lichess account + sync
- Startup page: Sign in with Lichess (PKCE, loopback), Continue as `<username>`, gear settings (FR-1.1–1.8, 1.11 Lichess part, FR-6.1–6.7).
- `secret_store` via keyring (SR-7 to SR-10).
- History import (FR-6.17), the "exclude played on Lichess" filter, and the "already played" badge.
- Sync queue: batches under 100, backoff, offline mode, Rated toggle, angle rule (FR-1.7, 1.9, FR-6.8–6.16).
- Sign-out revokes the token.
- **Puzzle rating display** (FR-6.11a–d, FR-9.4): your Lichess puzzle rating in the header, the +/− change per puzzle on the result panel (with Syncing… / Will sync later / Unrated states), the session total in the session bar, the change stored per attempt, and a rating trend chart on Stats.
- `scripts/set_test_token.py`: prompts for the live-test token with hidden input (`getpass`) and stores it through `secret_store` under `weaksquare-test`. Adam runs it himself in a normal PowerShell window, never inside Claude Code.

**Done when:** angle-rule unit tests cover all FR-6.13/6.14 cases; sync integration tests run against the fake client; the live test (`-m live`) syncs 3 `rated:false` solves using the separate test token (SR-13), and records the real response shape for the fake client; rating-display tests cover a positive change, a negative change, offline then synced, Rated off, already played, a 0 or missing change, and the session total, all against the fake client; a test proves the header rating only ever comes from Lichess responses.
**Adam's manual test:** sign in (your rating appears in the header and matches lichess.org) → solve a few rated `mix` puzzles (each shows +/− and the header and session total update; compare with lichess.org) → solve offline (Wi-Fi off; Will sync later) → reconnect → queue drains and the changes fill in → solves appear on Lichess → check the rating trend on Stats → sign out → token is gone from Credential Manager.

---

## v0.4: Stockfish
- Engine install (FR-7.5): `engine_manifest.json` pinned to `sf_19` with its SHA-256, `services/engine_install.py`, `scripts/fetch_stockfish.py`, a Stockfish step in `setup.py`, and the in-app *Stockfish isn't installed* banner with Install.
- `EngineClient` with its interactive engine, position validation and crash recovery (FR-7.1, 7.6; ARCHITECTURE §3 decision 12); engine settings, including the custom engine path (FR-7.4, 7.5).
- Refutation of wrong moves in Show answer; post-puzzle eval and top lines, never shown during a puzzle (FR-7.2, 7.3).
- After the puzzle: the start-position eval, the eval and top lines that follow the board, and an **Analyze** board you can move pieces on with the engine (FR-7.7, added at v0.4 planning). Evals read from your side.

**Done when:** engine integration tests (a known position gives the expected best move); no eval is visible while solving (Playwright check); installer tests against a local fake download: a hash mismatch refuses and leaves nothing behind, a zip with `..` paths is rejected, and a second run does nothing; an invalid position sent past validation causes one restart and a clean error, not a hang.
**Adam's manual test:** compare the SHA-256 in `engine_manifest.json` with the digest GitHub shows next to the asset on the sf_19 release page → delete the `engines` folder in the data folder you run (`%LOCALAPPDATA%\WeakSquare` or `WeakSquare-dev`) → the app shows the Install banner → Install works → deliberately play wrong moves → refutations make sense and evals read "for you" → after a puzzle, step through the answer with the engine panel and open Analyze to play moves on the board; check engine CPU usage is sane.

---

## v0.5: Training modes I
- **Commit the line** (FR-4.2), with the solution length hidden by default and a **Show move count** switch; **Spaced repetition** with exact repeats (FR-4.6); **Depth ladder** as an **order** (FR-3.11, FR-4.5; changed from a mode at v0.5 planning).
- **Modes** control at the top of the filters panel; switching mode starts a new session (§6).
- **Collapsible filters panel** (FR-1.14, added at v0.5 planning).
- Stats: accuracy **per mode** (FR-9.1).

**Done when:** mode state-machine unit tests (Commit grading, help before and after Submit); SRS scheduling tests (box moves on win/loss, graduation, misses from any mode, calendar-day due); depth-ladder level tests (window, threshold, never drops); the angle with the ladder and with Show move count; Playwright: one flow per mode, a mode switch starts a new session, no engine output before Submit, collapse/expand keeps the filters and survives a relaunch through the bridge.
**Adam's manual test:** one session in each mode plus one Depth-ladder session; in Commit the line, try Show move count on and off; misses resurface on schedule (in a `--dev` run, use Settings → Debug → fast-forward time); switching mode starts a new session; hide the filters while playing, relaunch (still hidden), show them again (nothing changed).

---

## v0.6: Training modes II + mistake reasons
- **Name the idea first** (setup and payoff motifs, graded as ideas found + extras; no target square, v0.6 planning) and **Danger spotting** (with Stockfish-verified safe candidates within 50 cp of best; a correct Unsafe is followed by the refutation's first move; local only) (FR-4.3, 4.4).
- **Mistake reasons** for puzzles: chips, keyboard 1–6, suggestions, misclick handling (§7.3, FR-5.6–5.11). The ask setting is *Always* / *Off* until Game Review ships.
- Stats: reason breakdown, Commit/Name/Danger accuracy (FR-9.3, 9.7).

**Done when:** safe-candidate verification test; reason-suggestion rule tests; a misclick is excluded from local stats but still sent as a loss.
**Adam's manual test:** 20 Danger-spotting puzzles (roughly half should be safe), tag reasons on misses, check the breakdown.

---

## v0.7: LLM Explain + cost guardrails
- Provider interface, Anthropic and OpenAI, model field, **Test key** (FR-1.2–1.4).
- **All guardrails first:** price table, usage log, estimates, per-run cap, monthly budget, `max_tokens`, reasoning setting, spend indicator (§9.3, FR-1.10).
- Explain (stuck ladder step 3): grounded context, structured output, validation, board annotations, caching (FR-8.1–8.8).
- Planning decisions (Adam, 2026-11-03): no model pre-selected (pick from the price table); the budget blocks at 100%; Explain requires Stockfish; Explain also works in Danger spotting. No new dependencies: both providers are called through `adapters/http.py`.

**Done when:** budget and cap enforcement tests (blocked when over); annotation-validation tests drop illegal moves and squares; the live test makes 1 real Explain call with Haiku or nano under the cap.
**Adam's manual test:** set a $0.05 monthly budget → Explain until blocked → raise it → compare one puzzle across two models.

---

## v0.8: Game library + Game Review (engine)
- Linked chess.com username with Verify; library page with filters and incremental sync for both platforms (§11.5).
- Import: paste, file, Lichess URL, chess.com URL (§11.1).
- Analysis pipeline, `game_analysis` and the analysis queue on the **background engine** (§11.2; ARCHITECTURE §3 decision 12). Review screen: eval graph, move symbols, key moments, refutations (§11.3).
- Retry mode; Save as puzzle plus the **My games** puzzle source (FR-3.15, 11.15, 11.16); mistake reasons on game moves.
- **Import puzzles from your own files** (PGN / EPD / CSV) into `custom_puzzles` with a set label, strict solving, an import report (FR-10.46–10.50; added 2026-11-02). No puzzle collections are shipped or downloaded.

**Done when:** PGN edge-case tests (multi-game file, bad PGN, variants rejected); chess.com optional-field tests; the serial-request rule is enforced in the chess.com client; analysis is reused on re-import; a puzzle refutation returns promptly while a game analysis is running; recorded game fixtures are anonymized (SR-12a); puzzle-file import tests (each format, bad entries reported and skipped, re-import adds nothing, mate-in-1 alternatives accepted).
**Adam's manual test:** link both accounts → sync → review one Lichess and one chess.com game → retry mistakes → save 2 puzzles → drill them → import a small PGN or EPD puzzle file of your own → check the import report → drill the set.

---

## v0.9: Game Review AI
- Explain this move; **Explain my game** (narrative plus key moments) with the cost estimate and Confirm; SAN-only anonymized context; caching (FR-11.17–11.21).
- **A model per AI feature** (FR-1.15; Adam, 2026-11-03): puzzle Explain and Game Review each get their own provider and model (e.g. Haiku for puzzles, Sonnet or Opus for games), sharing the keys, the price table and the monthly budget. The Coach plugs into the same setting in v0.10.

**Done when:** an anonymization test (no names, URLs, dates or clocks in the prompt); cache-hit test; budget enforcement; each feature's request uses that feature's model and is logged under its feature.
**Adam's manual test:** Explain my game on a recent loss; check the explanations match the engine lines. Set Haiku for puzzle Explain and a stronger model for Game Review, and check each feature uses its own.

---

## v0.10: Coach
- lichess-puzzler tagger and **habit tags** (FR-10.11–10.13, 10.27).
- Multi-game aggregation reusing the v0.8 pipeline; puzzle-history source; free report; gap table (§10.1–10.5).
- **Suggested default mix** with "Why this mix", the Apply/Compare/Dismiss banner, and reasons picking drill modes (§10.7).
- Optional LLM coaching with validated presets (§10.6), with its own provider and model in the per-feature setting from v0.9 (FR-1.15).
- **Puzzles from your games** (§10.9, FR-10.39–10.45): the analysis turns qualifying mistakes into `custom_puzzles` (new migration), with a severity-level setting (Blunders only / Mistakes and blunders / plus inaccuracies). Includes a quality check, Missed solved as you and Allowed solved as your opponent, the 30 cp tolerance with engine continuation, My games filters, a share of these puzzles in the Suggested mix, and archive.

**Done when:** each habit tag has positive and negative unit tests; tagger output matches the theme names in the puzzle DB; the suggestion never overwrites manual filters (test); quality-check tests accept and reject known positions (unique best move, several equal moves, already-decided position); each severity level produces the right set from fixture analysis, and narrowing archives (never deletes) with attempts kept; re-runs create no duplicates; Missed and Allowed puzzles have the right side to move and orientation; an alternative move within tolerance is accepted, and the engine continues from it; changing the level runs no new game analysis (test).
**Adam's manual test:** run the Coach on 50 rapid games → sanity-check the top 3 weaknesses against your own sense of your games → apply the Suggested mix. Analyze your last 100 games with *Mistakes and blunders* → drill 10 of the generated puzzles (each should be a real mistake from your games, with a sensible answer and correct orientation) → switch to *Blunders only* (the count drops, no re-analysis) and back → try an Allowed puzzle as your opponent → open one in Game Review from its link.

---

## v0.11: Whole-game coaching
**Goal:** a Coach that reads your games like a tutor does: tactics, but also strategy, openings, endgames and time use, including weaknesses nobody listed in advance (REQUIREMENTS §10.11; Adam, 2026-11-03).
- **Game digests** built from the v0.8 analysis: opening, key moments, castling and development, pawn structure, trades, endgame type, summarised time use and your mistake reasons (FR-10.52). A new migration stores them along with the new weakness kinds.
- **Whole-game measures** in the free report: per opening, phases and conversion, endgame types, time use, king safety (FR-10.53).
- **Open-ended LLM diagnosis** with the evidence rule: every weakness cites real games and plies, which the app checks and links to Game Review; anything with fewer than 3 games is tentative (FR-10.54, 10.55).
- **Advanced analysis** (off by default): adds the games' SAN move lists, with a cost warning against a standard run and a game cap (FR-10.56). This is the FR-8.16 rule change.
- Measurable findings become **tracked weaknesses**; the rest stay observations (FR-10.57). Each weakness gets something to do (FR-10.58).
- **Lesson pointers:** the in-app drill first, then a curated map of stable free pages plus search links for YouTube, chess.com and a site of your choice. The LLM picks topics only and never writes URLs (FR-10.59).
- **Include my notes**, opt-in, with a preview (FR-10.60).
- **Docs:** a User Guide section on whole-game coaching, and the privacy section updated with exactly what a standard run, an Advanced run and Include my notes send.

**Done when:**
- Each digest field and whole-game measure has unit tests on fixture games: castling move, moves before castling, endgame-type classification, conversion from +2 and saves from −2, low-clock blunders.
- The sample-size guard applies to every whole-game measure.
- Prompt tests:
  - a standard run's prompt has no full move lists
  - an Advanced run's prompt has SAN only, with no headers, names, dates, URLs, clocks or comments
  - notes appear only with Include my notes
- Evidence-validation tests:
  - an invented game label or ply is dropped
  - a weakness with no valid evidence is dropped
  - fewer than 3 cited games makes it tentative
- Lesson links:
  - every curated link's domain is in the allowlist
  - a URL written by the LLM is never shown
  - search links are built only by the app
- The Advanced estimate is blocked by the per-run cap and the budget, and a checkpoint never uses Advanced.

**Adam's manual test:**
1. Run the Coach on 30 of your games, standard. Check whether the weaknesses it names (tactical and strategic) match your own sense of your games, then click through a few citations to the actual moves.
2. Run the same games with Advanced. Compare the cost against the estimate, and see whether it found anything new.
3. Open two lesson pointers.
4. Run once with Include my notes, and check the preview.

---

## v1.0: Fix tracking + release
- **Checkpoints** every 10 eligible games plus Run now; weakness metrics and statuses with the sample-size guard, including v0.11's whole-game weakness kinds; Progress page with line charts per weakness and for overall game health (blunders, mistakes and inaccuracies per 10 games, one point per checkpoint over the rolling window; FR-10.38); optional auto AI summary (§10.8).
- Release from source (NFR-8): a first-run wizard (puzzle DB download, Stockfish install, both through the existing install services), the setup script's Start-menu shortcut, and a GitHub Release from the `v1.0` tag with notes from CHANGELOG. No packaged `.exe`.
- Polish pass: error states, empty states, performance on the full DB.
- **Docs:** User Guide complete, including installing from source, updating and troubleshooting; README status reads "v1.0".

**Done when:** weakness status-transition tests cover every rule in FR-10.35, using synthetic data; a checkpoint runs end to end on recorded data; a fresh clone on a clean Windows user profile goes from `setup.py` to a working app through the first-run wizard.
**Adam's manual test:** clone and run `setup.py` from scratch on a clean Windows user profile → full first-run → play and sync 10 games over a few days → a checkpoint fires → Progress page updates.

---

## v1.1: macOS and Linux
**Goal:** the same app, run from source, on Linux and macOS as well as Windows. No new features.

Target platforms:
- **Linux (fully supported):** Debian stable and Ubuntu LTS, x86-64, GTK desktop. Manually tested on clean VMs. Kali is a convenient extra check but not the reference distro.
- **macOS (best effort):** Apple silicon and Intel. CI only, plus a manual pass when Adam has access to a real Mac (rented cloud Mac or borrowed hardware). macOS may only be virtualized on Apple hardware, so a VM on the Windows PC isn't an option. The README says "best effort" until a manual pass is done.

Scope:
- **Adapters:**
  - single-instance lock with `fcntl` plus a local "bring your window forward" message
  - open folders and links with `open` / `xdg-open`
  - a portable fatal-error dialog
  - the log banner records the WebKit/GTK version
- **Window:** pywebview's GTK backend on Linux and Cocoa (WebKit) on macOS. Record the choice in ARCHITECTURE.md §7.
- **Real-app smoke harness:** WebKit has no Chromium debugging port. Run the smoke tests through pywebview's Qt (Chromium) backend where possible, and document what can only be checked by hand.
- **`setup.py`:**
  - checks for the system packages pip can't install (WebKitGTK on Linux) and prints the exact install command
  - creates a `.desktop` launcher on Linux and an app launcher on macOS
- **Stockfish:** add the macOS and Linux entries to the manifest (FR-7.5).
  - Linux has per-CPU builds, so add a small CPU-feature check with a safe baseline fallback.
  - On macOS, mark the binary executable and clear its quarantine flag.
- **Secrets:** macOS Keychain; Linux Secret Service. With no Secret Service running, refuse to store credentials with a clear message, and never fall back to a plaintext keyring (SR-1). Reword FR-6.5, SR-1 and SR-15 to be OS-neutral.
- **Paths:** platformdirs locations per OS (NFR-2), shown on the About screen.
- **CI:** add Linux and macOS runners.
- **Docs:** README, Developer Guide and User Guide get per-OS install, launch and troubleshooting steps. REQUIREMENTS §2 drops "Windows only".

**Done when:**
- The full test suite and static checks pass on Windows, Linux and macOS CI.
- The real-app smoke tests pass on Windows and Linux.
- A test proves the Linux secret store refuses rather than writing plaintext when no Secret Service is available.
- The engine installer picks the right manifest entry for each OS and architecture, and refuses unknown ones.
- A fresh clone goes from `setup.py` to a working app on a clean Debian stable VM and a clean Ubuntu LTS VM.

**Adam's manual test:**
1. On clean Debian and Ubuntu VMs: clone → `setup.py` → launch from the app menu → import the DB → solve puzzles → install Stockfish → sign in to Lichess (token stored in the keyring) → review a game → relaunch (data persisted) → launch a second copy (the first window comes forward).
2. Spot-check on Kali.
3. On a Mac, if available: the same run. Otherwise record macOS as CI-only in the handoff.

---

## v2.0: Opening trainer
**Goal:** learn openings with grounded explanations, build your own repertoire including your answers to the opponent's sidelines, and drill it with spaced repetition (REQUIREMENTS §18). It needs the engine (v0.4), the LLM guardrails (v0.7) and, for the explorer, Lichess sign-in (v0.3).

Built in internal steps, like v0.1, each committed and ticked off in `plans/v2.0.md`. QA runs once, at the end.
- **v2.0a Book and repertoire:** import the `chess-openings` book (FR-12.1); match lines by position; the repertoire tree and its migration (FR-12.4); a browse-and-pick screen; Learn mode's step-through with engine evals (FR-12.3, 12.6, without the LLM).
- **v2.0b Explanations:** overviews and per-move Explain (FR-12.5, 12.6); the `opening_notes` cache and its migration; prefetch with the estimate and Confirm, plus Regenerate (FR-12.7); the optional explorer with caching (FR-12.2).
- **v2.0c Deviations and practice:** "What if they play…?" with engine replies and stored branches (FR-12.8); Practice mode with per-position spaced repetition (FR-12.9, 12.10); opening stats (FR-12.11).
- **Docs:** a User Guide chapter for the Opening trainer, including what it sends (FR-12.12).

**Done when:**
- Every book line passes python-chess validation at import, and transpositions map to the same position (test).
- A test proves no move shown on the board or stored in the repertoire ever comes from LLM output.
- Cache tests show a second request for the same position, move, provider and model makes no API call.
- Prefetch skips stored items and their cost, and is blocked by the per-run cap and the monthly budget.
- Each scope preset gives the right line and move counts, and Custom is clamped to its limits.
- The estimate's cost comes from `llm_prices` (test with a changed price).
- The warnings appear at the 25%-of-budget and 10-minute thresholds.
- Split-into-runs keeps every run under the cap.
- A cancelled prefetch keeps the finished items.
- An illegal deviation is rejected before it reaches Stockfish.
- A deviation branch is stored and then drilled in Practice.
- Spaced-repetition scheduling tests use the injected clock.
- The explorer is skipped cleanly when you're signed out or offline.
- Recorded LLM and explorer fixtures are scrubbed.

**Adam's manual test:**
1. Pick the Italian Game as White → read the overview → step through the main line with Explain on a few moves.
2. Open the prefetch dialog and switch between Light, Standard and Deep (the counts, cost and time update and read sensibly) → prefetch with Standard (confirm, then check the spend indicator against the estimate) → close and reopen, and check the notes load with no new spend.
3. Enter 2 sidelines for Black with "What if they play…?" and check the engine replies and explanations make sense.
4. Practice for 15 positions, including a deliberate mistake → come back the next day and check the due positions.

---

## After v1.0 (parked ideas from review, not committed)
Threat-scan habit trainer, "Is there a tactic?" mode, visualization mode, think-first lock and timers, conversion practice vs. Stockfish, Play from here, self-review-before-engine, "What if?" questions, adaptive difficulty, pattern-based SRS, daily session builder, confirm-move toggle, notes and pattern journal, CSV export, in-app Help panel that renders the User Guide, a packaged and code-signed installer if other people ask for one.
