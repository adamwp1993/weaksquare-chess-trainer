# QA report: v0.2 (mixer complete + basics)

**Round 1, 2026-11-01.** Branch `v0.2` at `42e862c`. Independent QA. No product code, migrations, config or docs were changed. New tests are only under `tests/`. `%LOCALAPPDATA%\WeakSquare` still doesn't exist. The dev `puzzles.db` was only opened read-only (mtime unchanged, 13:42). No real shortcuts were created.

## Verdict: **FAIL** (one major bug)

All *Done when* items pass with evidence, and so do the static checks, the full-DB tests, the real-app smoke flows and the docs check. One **major** bug blocks the gate: **B1**. The **Enter** shortcut, which the User Guide documents as "Next puzzle", restarts the whole session in the most common flow (click Start with the mouse, solve, press Enter). Everything else is minor (B2 to B10).

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder: **369 passed**, 140 deselected (68 s). With QA tests: **400 passed** |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 133 files already formatted |
| `uv run mypy src` | Success: no issues found in 52 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean |
| `uv run pre-commit run --all-files` | gitleaks Passed; keyring-only Passed |
| `uv run pytest -m e2e` | builder: **68 passed** (141 s). With QA tests: 76 passed, 1 xfailed (B1) |
| `uv run pytest -m fulldb` (full DB **is** imported: 6,157,341 puzzles, schema v2, export 2026-10-02) | builder: **50 passed** (104 s). QA file: 5 passed, 1 xfailed (B2) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | Builder's 13 tests over 6 full runs: 5 × all passed, **1 × `test_reimport_during_a_session_keeps_the_filters` failed** (B3). 9 single runs of that test passed. QA smoke file: 2 passed (after fixing a race in my own test) |
| `python scripts/check_docs.py --strict` and without `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.2]` (both) |
| `uv run python scripts/gen_types.py` | rc 0; `types.ts` unchanged (no git diff) |
| `uv run pytest -m docs_screenshots` | 9 passed. `solved.png` now byte-identical (**v0.1-B14 fixed**). `update-banner.png` differs from the committed file and `presets.png` differs from run to run (B5). Restored with `git checkout docs/img` |
| `uv run python scripts/make_icon.py`, then `--check` | rebuilt 25,339 bytes (16 to 256 px), no git diff; "icon is up to date" |
| `uv run python tests/fixtures/tools/record_db_update.py` (network) | re-recorded; **no git diff**, so the fixtures aren't stale (Lichess page: 6,193,530 puzzles, file 2026-11-01) |
| `uv lock --check` | lockfile up to date |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db` (not the bare command: see the note below) | rc 0: uv found, `uv sync --locked`, `npm ci` (11 moderate npm-audit advisories; `package-lock.json` unchanged since v0.1), build, Chromium, pre-commit already installed, puzzle and shortcut steps skipped. Last line: "Start WeakSquare Chess Trainer from the Start menu or your desktop" even though no shortcut was made (B6) |
| `python scripts/setup.py --help` | Flags listed; **no** mention of the entire DB, 300 MB or 1.5 GB (B6) |
| `uv run python scripts/fetch_puzzle_db.py --help` | ok. Not run for real: it would replace the dev DB, which is read-only for QA. The same import path was timed below |
| `npm.cmd --prefix web run build` + `uv run python -m weaksquare --dev` (with `WEAKSQUARE_DATA_DIR` set to a temp folder) | app starts; user.db migrations 0001 and 0002 applied; log banner says **"WeakSquare 0.1.0"** (B7) |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` (temp data folder) | starts with no errors (window not inspected) |
| `npm.cmd --prefix web run dev -- --mode mock` and open http://127.0.0.1:5173 | served HTTP 200 after 1 s |
| Samples under `powershell -ExecutionPolicy AllSigned` | `npm.cmd … typecheck`, `uv run python scripts/make_icon.py --check`, `python scripts/check_docs.py --strict` all work. Bare `npm` is blocked (`npm.ps1 is not digitally signed`), and no doc uses it |
| Full-DB upgrade path, timed (QA probe: `ExistingPuzzleDb` → `PuzzleDbWriter` from the dev DB, read-only, into a scratch file) | 6,157,341 rows: load 76 s plus indexes and the new/removed comparison 36 s, **112 s total** (the guide says "about 2 minutes"). New/removed against itself: 0 / 0 |

Not run as written: `python scripts/setup.py` with no flags (it would write real Start-menu and Desktop shortcuts; that's in Adam's manual test) and `fetch_puzzle_db.py --dev` (it would replace the read-only dev DB). The Developer Guide and README contain no `.ps1`, bare `npm`/`npx` or venv-activation commands.

---

## Traceability

### Done when (ROADMAP v0.2)

| Item | Method | Result | Evidence |
|---|---|---|---|
| Preset round trip | existing + QA | PASS | `integration/test_presets.py::test_round_trip_every_field`, `::test_bridge_round_trip`; e2e `test_mixer_v02.py::test_presets_save_load_rename_delete`; QA real app `smoke/test_qa_v02_real_app.py::test_preset_hint_answer_stats_and_settings_survive_relaunch` (saved, loaded from the menu, survives a relaunch) |
| Ratio sampling ±5% over 1,000 draws | existing (allocator only) + **QA (real draws)** | PASS | `unit/test_queue.py::test_allocate_ratio_over_1000_draws` tests the pure allocator (exact 500/300/200). The fixture has only 337 puzzles, so QA added `fulldb/test_qa_v02_fulldb.py::test_ratio_50_30_20_over_1000_real_draws`: 1,000 puzzles served by `SessionService` from the full DB, no repeats, each group's share within ±5 |
| Hint/answer recorded as a loss | existing + QA | PASS | `unit/test_standard_mode.py` (6 help tests), `integration/test_session.py::test_hint_and_answer_recorded_as_a_loss`; QA `test_qa_v02_edges.py::test_hint_mid_line_points_at_the_next_player_move`, `::test_repeated_hints_record_one_loss`, `::test_hint_after_a_wrong_move_is_free`; real app: `help_used='hint'` row in user.db |
| Color scheme round-trips, applied on relaunch, no browser storage | existing | PASS | `integration/test_ui_settings.py`, `smoke/test_real_app.py::test_dark_scheme_survives_relaunch`, `contract/test_no_browser_storage.py` (2 tests), `e2e/test_appearance.py::test_switching_applies_at_once…` |
| Playwright main screens in Light and Dark | existing + QA screenshots | PASS | `e2e/test_appearance.py` (WCAG AA on every text node, both schemes); QA `test_qa_v02_ui.py::test_screenshots_of_every_v02_screen[light/dark]` (12 screens each, reviewed) |
| Importer text names the full DB and ~300 MB | existing | PASS (UI and guide), minor gap in setup `--help` (B6) | `e2e/test_mixer_v02.py::test_importer_names_the_whole_database_and_its_size`, `::test_user_guide_uses_the_same_wording`; screenshots `light-first-run.png` / `light-update-dialog.png` |
| User Guide screenshots include a dark shot | existing | PASS | `docs/img/trainer-dark.png` |
| Update check: same hash, new hash, no hash in `meta`, offline, unreadable count, once a day, Skip | existing | PASS | `integration/test_db_update.py` (7 named cases plus Not now, auto-off, imported export, no DB, parse_count, bridge); fixtures re-recorded with no diff |
| New/removed counts against two fixture DBs | existing + QA probe | PASS | `integration/test_puzzle_db_v2.py::test_new_removed_counts`; at full scale, the QA probe gave 0/0 in 36 s including indexes |
| Move → sound mapping, mate plays only the mate sound | existing | PASS | `unit/test_move_sounds.py` (quiet, capture, check, mate, O-O, O-O-O, en passant, promotion with and without capture, capture+check, castle+check; mate by capture) |
| Sounds on/off and persistence (stubbed audio) | existing | PASS | `e2e/test_sounds.py` (4 tests); real app `smoke/test_real_app.py::test_sounds_may_play_without_a_click` |
| `CREDITS.md` lists every sound with an AGPL-compatible license | existing | PASS (license source not checked online) | `contract/test_sound_credits.py` (4 tests, SHA-256 checked) |
| `setup.py` shortcuts: both with icon, flags, known-folder Desktop, no duplicates | existing | PASS (fake shell) | `unit/test_setup_shortcuts.py` (7 tests, including the real known-folder lookup) |
| `.ico` has 16 to 256 px and matches the SVG build | existing + command | PASS | `unit/test_icon.py` (5 tests); `make_icon.py --check` |

### Requirement IDs in scope

| ID | Method | Result | Evidence |
|---|---|---|---|
| FR-1.12 dark mode | e2e + smoke | PASS (live OS switch is manual) | above; `e2e/test_appearance.py::test_match_system_follows_the_os_live` (emulated) |
| FR-1.13 sounds (defaults on/70/sfx; no "standard" set) | e2e + unit + QA | PASS | QA `test_qa_v02_edges.py::test_sound_defaults_match_fr_1_13`, `::test_bad_sound_settings_refused` (rejects `standard`, volume 101 and -1) |
| FR-2.1a wording | e2e | PASS (B6, B8 minor) | above |
| FR-2.5 update check | integration + e2e | PASS | `test_db_update.py`, `e2e/test_update_banner.py` (6) |
| FR-3.6 phase/goal/origin | e2e + screenshots | PASS | theme picker groups (`docs/img/theme-picker.png`) |
| FR-3.7 openings | oracle + QA | PASS | `integration/test_filter_count.py` (random specs with openings), fulldb "biggest family" / "smallest variation" match the oracle; QA `::test_unknown_opening_matches_nothing`, `::test_a_family_includes_its_variations` |
| FR-3.8 quality (default 50/100) | oracle + QA | PASS | fulldb oracle; QA `::test_popularity_threshold_is_inclusive`, bounds tests. The defaults remove **21.9 %** on the full DB (1,348,637 of 6,157,341), the same as the builder's figure |
| FR-3.9 history | oracle + e2e + QA | PASS | QA `::test_history_filters_follow_the_latest_result` (fail → win → fail sequence; Only my misses overrides Exclude solved); fulldb "only my misses" 7 ms |
| FR-3.10 ratios | integration + fulldb QA | PASS (B2 timing) | `test_ratios_order.py` (8); QA `::test_ratio_groups_with_an_unknown_theme_and_overlaps`, `::test_ratios_respect_exclude_solved`, fulldb `::test_ratio_count_matches_the_oracle` ×3 |
| FR-3.11 order | integration + e2e | PASS | `test_ratios_order.py`, `unit/test_queue.py`, `e2e::test_easy_to_hard_starts_with_the_easiest` |
| FR-3.13 presets | integration + e2e + QA | PASS | above; QA `::test_preset_name_of_exactly_60_characters`, `::test_preset_with_invalid_filters_is_refused_over_the_bridge`, e2e `::test_preset_name_of_61_characters_is_refused` |
| FR-5.2, FR-5.4, FR-5.5 `help_used`, §7.2 steps 1–2 | unit + integration + e2e + QA | PASS | above; QA `::test_hint_after_solving_is_refused_but_answer_is_free`, `::test_answer_from_mid_line_is_legal_from_its_start`, e2e `::test_rapid_hint_clicks_fail_the_puzzle_once`, `::test_hint_key_after_solving_does_nothing` |
| FR-9.1 / FR-9.2 Stats | unit + integration + e2e + real app | PASS | `unit/test_stats.py` (5), `test_user_db_v2.py` (3), `e2e::test_stats_page`; real-app screenshot `qa-v02-real/stats.png` |
| NFR-8a icon and shortcuts | unit + smoke | PASS (taskbar and real shortcuts are manual) | `smoke/test_real_app.py::test_window_has_the_app_icon` |
| Keyboard shortcuts, coordinates, auto-orient | e2e + QA | **FAIL: B1** | `e2e/test_trainer_v02.py` (5); QA `::test_shortcut_keys_ignored_in_the_preset_dialog` passes; `::test_enter_after_a_mouse_session_goes_to_the_next_puzzle` **xfail (B1)** |
| v0.1-B14 (`solved.png`) | command | **Fixed** | the docs-screenshot run reproduces it byte for byte |
| v0.1-B15 (when a typed rating applies) | doc read | **Fixed** | the *Choosing your puzzles* Rating row says "applies when you press Enter or click elsewhere" |
| Puzzle DB upgrade (v1 → v2, no download) | integration + real app + probe | PASS | `test_puzzle_db_v2.py::test_upgrade_v1_db_without_download`; QA `smoke/test_qa_v02_real_app.py::test_v1_puzzles_db_is_upgraded_in_the_real_app`; full-scale probe 112 s |

### Performance on the full DB (graded)

| Measurement | Target | Measured | Grade |
|---|---|---|---|
| Default count (quality on, Exclude solved, 5,000-attempt history) | < 500 ms | 311 ms | pass |
| Other v0.2 filter counts (8 specs) | < 500 ms | 7–307 ms | pass |
| v0.1 count suite (20 random specs) | < 500 ms | all pass | pass |
| **3-group ratio count, full rating range** | < 500 ms | **median 551 ms** (5 runs: 547–566) | **fail by ~10 % (B2, minor, known)** |
| Ratio session start + first puzzle | — | 554 + 9 ms | informational |
| Upgrade job (6.16 M rows) | "about 2 minutes" | 112 s | pass |

---

## Bugs

### v0.2-B1: **major**: Enter restarts the session instead of moving to the next puzzle
- **Steps:** click **Start** with the mouse and solve the puzzle with the mouse. Focus stays on the Start button, because clicking the board doesn't move it. Then press **Enter**, which the User Guide's *Keyboard shortcuts* table says is "Next puzzle".
- **Expected:** puzzle 2 of the same session; the session bar keeps "Solved 1, Played 1/20".
- **Actual:** the focused Start button is clicked again, so a **new session** starts: "Solved 0, Played 0/20, Puzzle 1 of 20". `useShortcuts` deliberately ignores Enter on a focused button, so the shortcut never fires. The same thing happens mid-puzzle: Enter starts a new session without recording the skip. Also, after a mouse click on Hint, Enter re-clicks Hint instead of going to the next puzzle.
- **Evidence:** `tests/e2e/test_qa_v02_ui.py::test_enter_after_a_mouse_session_goes_to_the_next_puzzle` (xfail strict). Probe output: `BEFORE: Solved 1 … Played 1 / 20` → `AFTER: Solved 0 … Played 0 / 20`.

### v0.2-B2: minor (known limit): 3-group ratio count takes ~551 ms on the full DB
- **Steps:** `uv run pytest -m fulldb -s tests/fulldb/test_qa_v02_fulldb.py`.
- **Expected:** < 500 ms (REQUIREMENTS §5). **Actual:** median 551 ms, which matches ARCHITECTURE §7. The live count is debounced, so this is about 10 % over the target with no functional impact.
- **Evidence:** `::test_ratio_count_full_range_under_500ms` (xfail, non-strict); `::test_ratio_count_full_range_within_known_limit` guards against it getting worse than 700 ms.

### v0.2-B3: minor: intermittent failure of the real-app "re-import during a session keeps the filters" test
- **Steps:** `uv run pytest -m smoke` (the full file).
- **Expected:** every puzzle after a mid-session re-import is rated 400–600. **Actual:** once in 6 full runs, the first puzzle after the swap was rated **953** (`[953, 562, 527, 520, 429, 413, …]`). The other 5 full runs and 9 single runs passed. I couldn't reproduce it with logs kept, so the root cause is unknown. It could be a real stale-key or ordering race in `SessionService._follow_reimport`, which now matters more because the update banner invites updating mid-session ("You can keep training meanwhile").
- **Evidence:** `tests/smoke/test_qa_v01_real_app.py::test_reimport_during_a_session_keeps_the_filters`; first run's output in this report.

### v0.2-B4: minor (test harness): real-app smoke tests make live requests to database.lichess.org
- **Steps:** run `uv run pytest -m smoke` and read any test's `app-data/logs/weaksquare.log`.
- **Expected:** tests don't depend on the network (fixtures replay recorded responses). **Actual:** every launch (about 15 per run, each with a fresh data folder) runs the automatic update check against the live site. The log shows "a newer puzzle database is available", and the real banner appears in the middle of the tests. The results are nondeterministic offline and online, and Lichess gets an extra ~15 requests per run.
- **Evidence:** `…/test_preset_hint_answer_stats_0/app-data/logs/weaksquare.log:7` (`puzzle_db_update_check-job-1 … newer puzzle database is available`). Suggested fix: the harness turns `puzzle_db.auto_check` off or points the HTTP client at a local stub.

### v0.2-B5: minor (docs): user-guide screenshots aren't reproducible, and `mixer.png` is cropped
- **Steps:** run `uv run pytest -m docs_screenshots` twice, then `git status docs/img`.
- **Expected:** byte-identical output, as v0.1-B14 asked for. **Actual:** `update-banner.png` comes out the same every time but differs from the committed file. `presets.png` differs between runs (sha1 `9a965c…` then `33201c…`). The differences are pixel-level only. Separately, `docs/img/mixer.png` is scrolled, so the panel title, the Preset row and the Mix by ratio switch are cut off, although step 1 of the section tells the reader about Mix by ratio.
- **Evidence:** the commands above. I restored `docs/img` afterwards.

### v0.2-B6: minor: `setup.py` wording
- `python scripts/setup.py --help` shows only the first docstring line. Plan decision 15 said setup's help text would name the **entire** database (about 300 MB, about 6 M puzzles, about 1.5 GB), but that text is only in the source docstring, not in `--help` and not in the console step.
- With `--no-shortcut`, setup still ends with "Start WeakSquare Chess Trainer from the Start menu or your desktop."
- **Evidence:** the outputs in the commands table.

### v0.2-B7: minor: the app still reports version 0.1.0
- **Steps:** launch the v0.2 build and open About, or read the log banner.
- **Expected:** a version that tells v0.2 apart from v0.1 (NFR-7). **Actual:** "WeakSquare 0.1.0 starting" (`pyproject.toml` `version = "0.1.0"`). Adam can't tell which build he's testing from About.

### v0.2-B8: minor (docs): "no filters" count versus the new quality defaults
- *Getting started* says "With no filters set, the match count equals the number of puzzles imported." Since v0.2, the quality filter is **on by default**, so right after importing "about 6 million" puzzles a new user sees **4,808,704 puzzles match** (21.9 % fewer). FR-2.1a's sentence is still true only after both quality boxes are cleared. Suggest saying that the default quality filter hides about a fifth of them, and how to see them all.

### v0.2-B9: minor (visual): the real window has a second, page-level scrollbar
- **Steps:** launch the real app at its default size (smoke harness).
- **Expected:** only the filter panel scrolls (plan build note, User Guide: "The panel scrolls on its own"). **Actual:** the page itself also overflows by a few pixels and shows an outer scrollbar next to the panel's.
- **Evidence:** `tests/e2e/artifacts/qa-v02-real/after-upgrade.png`, `answer.png` (right edge).

### v0.2-B10: minor (docs): ARCHITECTURE §2 layout not updated for v0.2's modules
- The tree doesn't list `core/move_sounds.py`, `core/db_update.py`, `core/stats.py`, the v0.2 services (`presets.py`, `stats.py`, `ui_settings.py`, `db_update.py`; the services comment still lists v0.1 only), `scripts/make_icon.py` or `tests/fixtures/tools/`. The checkpoint gate requires §2 to be updated when the layout changes.

Informational, not a bug: `npm ci` reports 11 moderate advisories, and `chessground@9.2.1` is flagged deprecated on npm. `package-lock.json` is unchanged since v0.1.

---

## Tests added (all under `tests/`)

- `tests/integration/test_qa_v02_edges.py` (31 tests): `test_history_filters_follow_the_latest_result`, `test_only_my_misses_with_no_history_cannot_start`, `test_hint_mid_line_points_at_the_next_player_move`, `test_answer_from_mid_line_is_legal_from_its_start`, `test_hint_after_a_wrong_move_is_free`, `test_repeated_hints_record_one_loss`, `test_hint_after_solving_is_refused_but_answer_is_free`, `test_unknown_opening_matches_nothing`, `test_a_family_includes_its_variations`, `test_popularity_bounds_accepted[-100,100]`, `test_bad_quality_and_ratio_values_refused[8 cases]`, `test_popularity_threshold_is_inclusive`, `test_ratio_groups_with_an_unknown_theme_and_overlaps`, `test_ratios_respect_exclude_solved`, `test_preset_name_of_exactly_60_characters`, `test_preset_with_invalid_filters_is_refused_over_the_bridge`, `test_volume_bounds_accepted[0,100]`, `test_bad_sound_settings_refused[4 cases]`, `test_sound_defaults_match_fr_1_13`.
- `tests/e2e/test_qa_v02_ui.py` (9 tests): `test_screenshots_of_every_v02_screen[light,dark]` (writes `tests/e2e/artifacts/qa-v02/`), `test_ratio_groups_without_themes_disable_start_and_say_why`, `test_rapid_hint_clicks_fail_the_puzzle_once`, `test_hint_key_after_solving_does_nothing`, `test_shortcut_keys_ignored_in_the_preset_dialog`, `test_only_my_misses_greys_out_exclude_solved`, `test_preset_name_of_61_characters_is_refused`, `test_enter_after_a_mouse_session_goes_to_the_next_puzzle` (**xfail strict, B1**).
- `tests/fulldb/test_qa_v02_fulldb.py` (6 tests): `test_ratio_50_30_20_over_1000_real_draws`, `test_ratio_count_matches_the_oracle[defaults, no quality, narrow]`, `test_ratio_count_full_range_within_known_limit`, `test_ratio_count_full_range_under_500ms` (xfail, B2).
- `tests/smoke/test_qa_v02_real_app.py` (2 tests): `test_preset_hint_answer_stats_and_settings_survive_relaunch`, `test_v1_puzzles_db_is_upgraded_in_the_real_app` (screenshots in `tests/e2e/artifacts/qa-v02-real/`).

---

## Scope / architecture / security

- **Scope:** nothing from a later version was built. `exclude_played_on_lichess` and `source` are still rejected by `FilterSpec.validate`, and the only v0.3 mention in `web/src` is a comment. There's no engine, sign-in, Explain or mode UI.
- **Layers:**
  - `core/` does no I/O (`unit/test_core_purity.py`, plus an import check of the new `db_update.py`, `move_sounds.py`, `stats.py` and `queue.py`: stdlib and python-chess only).
  - There's no `datetime.now`, `time.time` or global `random` in `core/` or `services/`; `random` appears only as the `random.Random` type.
  - Adapters are imported only by `app.py`. The bridge imports `Desktop` only as a type, as it did in v0.1.
  - `keyring` is imported nowhere; there's no HTTP outside `adapters/http.py`.
- **Bridge:** `contract/test_bridge_allowlist.py` passes with the 12 new methods.
- **Browser storage:** none in `web/src`, and Mantine's localStorage manager isn't used (`contract/test_no_browser_storage.py`). In the real app, `localStorage` and `sessionStorage` lengths are 0.
- **Threads and data:** no shared SQLite connections (no change to `connection.py`). Every QA test used a temp folder or the read-only dev DB, and `%LOCALAPPDATA%\WeakSquare` doesn't exist.
- **Migrations:** only new files (`puzzles/0002`, `user/0002`); `0001` is untouched (`git diff main..v0.2`).
- **Dependencies:** none added (`pyproject.toml` and `web/package.json` have no diff against `main`); `uv lock --check` is clean; both lockfiles are committed.
- **Security:**
  - gitleaks passes, and a repo-wide pattern scan for `lip_`, `sk-ant-`, `sk-`, `ghp_` and `Bearer` found only the guardrail configs and the REQUIREMENTS text.
  - The HTTP fixtures (`sha256sums.txt`, `head.json`, `page.html`) hold no usernames, game IDs or lichess.org URLs (links blanked to `#`). `contract/test_fixtures_clean.py` now scans every text file.
  - No secrets exist in v0.2.
  - The CDP port is set only by `tests/smoke/conftest.py`, and the app refuses it without `--dev` (`smoke/test_real_app.py::test_debug_port_refused_without_dev`, `unit/test_sr16_refusal.py`).

## Docs findings

- `check_docs.py --strict`: 0 errors, 0 warnings. There are no `TODO(v0.2)` markers left.
- **Developer Guide:** every command was run as written, except the two noted above, and each worked. No command uses `.ps1`, bare `npm`/`npx` or venv activation.
- **User Guide sections followed against the app** (mock UI and real app): Keeping the database up to date, Choosing your puzzles (v0.2 rows), Presets, Stats, Solving (Hint/Show answer), Getting unstuck, Keyboard shortcuts, Appearance and sounds, Installing from source (as far as is safe), Getting started (upgrade wording). Labels, defaults and step order match the UI, except:
  - **B1:** Enter is documented as "Next puzzle" but restarts the session after a mouse Start.
  - **B8:** the "no filters" count wording.
  - **B5:** `mixer.png` crop and screenshot reproducibility.
- **CHANGELOG `[Unreleased]`:** covers every user-visible *Done when* item (ratios, presets, Hint/Show answer, Stats, shortcuts, coordinates, dark mode, sounds, update check with exact counts, icon and desktop shortcut, importer wording, the one-time upgrade).
- **Privacy:** both features that send data off the PC say what they send. *Your data and privacy* lists the update check's three requests, and the update section links to it. The sounds are local.
- **v0.1 carry-overs:** B14 fixed, B15 fixed.

## For Adam's manual test

These couldn't be verified automatically:

- **Real shortcuts and icons:** a single desktop icon in your (OneDrive) Desktop folder and the Start-menu entry after re-running `setup.py`; how the icon looks at desktop and taskbar size; whether a pinned shortcut groups with the running window (ARCHITECTURE §7 notes it may not).
- **Match system:** whether it follows a live Windows theme change in WebView2. It's only emulated in Playwright.
- **First paint:** whether there's any flash of the wrong scheme at launch. The smoke test only checks the attribute at the first render.
- **Sounds:** whether they sound right per event and per set, including the opponent's first move. Autoplay itself is proven by `test_sounds_may_play_without_a_click`.
- **Real update import:** Update now from the banner with the 300 MB download, the exact new/removed message, and "no second check the same day" across relaunches.
- **Long session after an update:** play for a while after an update mid-session and watch for a puzzle outside your filters (B3).
- **Sound licenses:** the AGPL claim against lila's `COPYING.md` at the pinned commit. QA didn't fetch it.
- **B1 in the real window:** click Start, solve, press Enter.

---

# Round 2: re-verification, 2026-11-01

Branch `v0.2` at `4cde058`. Fix commits: `a3699e2` (B1), `b23835f` (B3), `e8fe8df` (B4), `4cde058` (B5–B10). As in round 1, QA changed no product code, docs or config. `%LOCALAPPDATA%\WeakSquare` still doesn't exist, and the dev `puzzles.db` is unchanged (mtime 13:42).

## Verdict: **PASS WITH ISSUES** (minor only)

B1 (major) and B3, B4, B6, B7, B8, B9 and B10 are fixed and verified. B5 is mostly fixed: 13 of the 14 screenshots now reproduce byte for byte, but `presets.png` still varies from run to run (pixel-level only). B2 remains a known minor limit. One new minor finding: the builder's B3 regression test doesn't catch the bug on the pre-fix code. QA added a test that does (R2-1).

## Commands (full suite after the fixes)

| Command | Result |
|---|---|
| `uv run pytest` | **406 passed** (75 s), including the new QA test |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 139 files formatted |
| `uv run mypy src` | no issues, 52 files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | gitleaks Passed; keyring-only Passed |
| `python scripts/check_docs.py --strict` and without `--strict` | 0 errors, 0 warnings |
| `uv lock --check`, `uv run python scripts/make_icon.py --check`, `uv run python scripts/gen_types.py` | clean; icon up to date; `types.ts` unchanged |
| `uv run pytest -m e2e` | **82 passed**, 0 xfailed (the B1 test now passes without its marker) |
| `uv run pytest -m fulldb` | **55 passed, 1 xfailed** (B2, kept) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke`, **6 full runs** | **16/16 passed in all 6 runs** (round 1: 1 failure in 6). QA smoke file with the new B1 test: 3 passed |
| `uv run pytest -m docs_screenshots`, twice | 9 passed both times. 13 images identical to the committed ones in both runs; `presets.png` differs between runs and from the committed file (B5). Restored with `git checkout docs/img` |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db` and `--help` | rc 0; ends "Setup complete. Start the app with: uv run python -m weaksquare". `--help` prints the full description, including the entire database, about 300 MB, about 6 million puzzles and about 1.5 GB |

## Bugs re-tested

| Bug | Result | Evidence |
|---|---|---|
| B1 Enter restarts the session | **Fixed** | Mock: `tests/e2e/test_qa_v02_ui.py::test_enter_after_a_mouse_session_goes_to_the_next_puzzle` passes (marker removed), plus the builder's `test_trainer_v02.py::test_enter_on_a_keyboard_focused_button_still_presses_it` and `::test_enter_after_clicking_hint_goes_to_the_next_puzzle`. **Real window (new):** `tests/smoke/test_qa_v02_real_app.py::test_enter_after_mouse_clicks_is_next_in_the_real_app`. Mouse Start then Enter gives Puzzle 2 and Failed 1; mouse Hint then Enter gives Puzzle 3 and Failed 2 |
| B2 ratio count ~550 ms | **Kept** as a known limit (as agreed) | xfail and the 700 ms guard are unchanged; fulldb run as above |
| B3 wrong puzzle after a mid-session re-import | **Fixed** | 6 full smoke runs with no failure. The fix checks the generation and reads the row in one shared-lock session, so a swap (exclusive lock) can't fall between them; `next_puzzle` then follows the re-import and retries. See R2-1 for the regression test |
| B4 smoke tests call Lichess | **Fixed** | Builder's `test_real_app.py::test_smoke_launches_never_call_lichess` passes. Across the 15 app logs of one full smoke run, none mentions the update check or a newer database |
| B5 screenshots not reproducible; `mixer.png` cropped | **Partly fixed (minor, open)** | `mixer.png` now shows the panel from the top (title, Preset row, Mix by ratio). 13 of 14 images are byte-stable. `presets.png` gave three different hashes (committed, `a000479…`, `de1fcc6…`). Playwright already hides the caret, so the source is something else in that modal |
| B6 `setup.py` wording | **Fixed** | `--help` and the final line, as above; `tests/unit/test_setup_shortcuts.py` passes |
| B7 version 0.1.0 | **Fixed** | the log banner in every smoke run reads "WeakSquare 0.2.0 starting"; `tests/contract/test_versions_agree.py` passes. The lockfile diffs are the project's own version only (no dependency change) |
| B8 "no filters" count wording | **Fixed** | *Getting started* now says the count equals the imported total "with every filter cleared, including the quality filter", and is lower with the default quality filter on |
| B9 page-level scrollbar | **Fixed** | `test_mixer_v02.py::test_no_page_scrollbar_beside_the_filter_panel` (3 sizes) passes; real-app screenshot `tests/e2e/artifacts/qa-v02-real/after-upgrade.png` has no outer scrollbar |
| B10 ARCHITECTURE §2 | **Fixed** | §2 lists `core/move_sounds.py`, `core/stats.py`, `core/db_update.py`, the v0.2 services, `scripts/make_icon.py` and `tests/fixtures/tools/` |

## New findings (round 2)

### v0.2-R2-1: minor (test): the builder's B3 regression test doesn't catch the bug on the pre-fix code
`tests/integration/test_session.py::test_swap_between_the_version_check_and_the_read_never_serves_a_wrong_puzzle` was described as failing on the pre-fix code. In a scratch worktree at `3c20bf5`, it fails there only with a `TypeError`, because the old `get()` has no `version` argument. With the call adapted to the old signature, it **passes** on the buggy code. The stale key happened to land on a 468-rated puzzle, which still matches its `rating_max=1000` filter, because the new file keeps many low-rated puzzles.

QA added `tests/integration/test_qa_v02_round2.py::test_stale_key_after_a_swap_inside_the_read_window_is_never_served`. Its new file keeps only puzzles rated above the filter, plus a few matching ones. Results:
- **Pre-fix `3c20bf5`:** fails with `[('MJXhc', 912), …]`, a 912-rated puzzle served under `rating_max=900`.
- **Fixed `4cde058`:** passes.

The fix itself is correct. Only the builder's test is weak. I deleted the worktree afterwards.

Note, not a bug: with the panel now scrolled to the top, `docs/img/mixer.png` cuts off the match count at the bottom edge ("307,865 puzzles match" is half visible). It's cosmetic, and the caption doesn't mention the count.

## Tests added in round 2
- `tests/integration/test_qa_v02_round2.py::test_stale_key_after_a_swap_inside_the_read_window_is_never_served` (R2-1; checked against both the pre-fix and fixed code).
- `tests/smoke/test_qa_v02_real_app.py::test_enter_after_mouse_clicks_is_next_in_the_real_app` (B1 in the real WebView2 window).

## Still for Adam's manual test
The round-1 list stands, except that B1 has now been checked in the real window. B3 can still be watched for after a real mid-session update.
