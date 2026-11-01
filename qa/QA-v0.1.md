# QA report: v0.1 (the puzzle mixer)

**Round 1, 2026-11-01.** Branch `v0.1` at `51719b1`. Independent QA; no product code, migrations, config or docs were changed. New tests only under `tests/`.

## Verdict: **FAIL**

Three major product bugs (B1, B2, B3) and one major test-harness bug (B4). Everything else on the checklist passes with evidence: all five *Done when* items, the static checks, the full-DB timings, the real download, cancel and swap, and the real-app smoke flow. The checkpoint gate needs B1 to B4 fixed, each with a regression test. The xfail tests listed below already serve as those regression tests.

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` (before QA tests) | 177 passed, 57 deselected (12.7 s) |
| `uv run pytest` (with QA tests) | 186 passed, 1 xfailed (B2) |
| `uv run ruff check .` / `uv run ruff format --check .` | clean / 101 files formatted |
| `uv run mypy src` | no issues, 43 files |
| `npm.cmd --prefix web run typecheck` / `run lint` | clean / clean |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `uv run pytest -m e2e` | builder 4/4; with QA tests 16 passed, 2 xfailed (B1, B3) |
| `uv run pytest -m fulldb` (full DB **is** imported: 6,157,341 puzzles, 2026-10-02) | 42 passed (136 s); QA fulldb tests 3 passed |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | builder file over 6 runs: 5/7, 6/7, 7/7, 7/7, 7/7, 7/7 (**B4**); final full run 8 passed, 2 xfailed (B1, B2) |
| `python scripts/check_docs.py --strict` and without `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.1]` |
| `uv run python scripts/gen_types.py` | rc 0, `types.ts` unchanged |
| `uv run pytest -m docs_screenshots` | 4 passed, `docs/img/*.png` byte-identical (no git diff) |
| `python scripts/setup.py --dev`, with APPDATA set to a temp folder | rc 0: uv note shown, `uv sync --locked`, npm ci skipped (lock unchanged), build, Chromium, pre-commit already installed, puzzle step skipped (dev DB present), shortcut created with target `.venv\Scripts\pythonw.exe`, args `-m weaksquare`, working dir = repo |
| `uv run python scripts/fetch_puzzle_db.py --dev`, with `WEAKSQUARE_DATA_DIR` = temp | **Real download**: checked against Lichess `sha256sums.txt`, 6,157,341 puzzles imported in 150 s, `meta.sha256` recorded, download removed afterwards, rc 0 |
| `… fetch_puzzle_db.py --file tests/fixtures/puzzles_sample.csv` (temp folder), then `--skip-if-present` | 337 imported, rc 0; then "already imported; skipping" |
| `npm.cmd --prefix web run build` + `uv run python -m weaksquare --dev` | Window "WeakSquare Chess Trainer (dev)", closes rc 0 |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` (temp data folder) | App loads `http://localhost:5173/` and shows the import view; closes rc 0 |
| `npm.cmd --prefix web run dev -- --mode mock`, then open http://127.0.0.1:5173 | Mock UI shows "615,730 puzzles match", no page errors |
| Sample commands under `powershell -ExecutionPolicy AllSigned` | `npm.cmd`, `python -m uv run ruff`, `check_docs` all work; bare `npm` is blocked (`npm.ps1 … not digitally signed`) |

Not run as literally written: `python scripts/setup.py` without `--dev` and `fetch_puzzle_db.py` without a data-folder override. Both would download into the real `%LOCALAPPDATA%\WeakSquare`. I ran the equivalents above. `%LOCALAPPDATA%\WeakSquare` still doesn't exist after QA, and the real Start menu was not changed.

---

## Traceability

### Done when

| Item | Method | Result | Evidence |
|---|---|---|---|
| FEN semantics, 10 known puzzles + mate-in-1 alternative | existing + QA real-app | PASS | `tests/unit/test_chess_rules.py::test_known_puzzle[×10]`, `::test_mate_in_one_accepts_alternative_mate`, `::test_mid_line_mate_alternative`; real app: 001KR solved with the alternative mate d1d8 (`tests/smoke/test_qa_v01_real_app.py::test_main_flow_alternative_mate_wrong_move_persistence`); mock: `tests/e2e/test_qa_v01_ui.py::test_mate_in_one_alternative_mate_is_accepted` |
| Count = direct SQL for 20 random specs | existing | PASS | `tests/integration/test_filter_count.py::test_count_matches_oracle[0..19]`, `::test_edge_specs`; full DB `tests/fulldb/test_perf.py::test_count_matches_oracle_fulldb[0..19]`; QA cross-bitmask-column ALL/exclude `tests/fulldb/test_qa_v01_fulldb.py::test_all_and_exclude_across_bitmask_columns` |
| Count < 500 ms on the full DB | existing + QA | PASS | `test_count_under_500ms[0..19]`; through the real bridge on the full DB: 67–290 ms (fork AND long 1200–1600: 89,722 in 67 ms; ANY 2 themes: 261 ms; 10 excludes: 242 ms; first count after launch: 181 ms) |
| 50-puzzle queue from a ≥1M pool < 500 ms | existing + QA | PASS | `test_queue_50_from_1m_pool_under_500ms`; sparsest rejection-sampling case `test_sparse_rejection_sampling_under_500ms` |
| Bridge exposes exactly the allowlist | existing | PASS | `tests/contract/test_bridge_allowlist.py` (3 tests); 16 methods, matching the plan |
| Newer-schema `user.db` refused untouched | existing + QA | PASS | `tests/integration/test_migrations.py::test_newer_schema_refused_untouched`; app level: `tests/integration/test_qa_v01_edges.py::test_app_refuses_newer_schema_user_db_untouched` (rc 1, same SHA-256 and mtime, no WAL, no backup) |
| A migration writes a backup first | existing | PASS | `::test_backup_before_migration`, `::test_failing_migration_leaves_backup_and_original`, `::test_keeps_last_five_backups` |
| A cancelled import leaves `puzzles.db` working | existing + QA real app | PASS | `tests/integration/test_puzzle_import.py::test_cancel_midway_keeps_existing_db`; real app, real 6.16M-row export: cancelled at "Importing puzzles… 1,020,000", `puzzles.new.db` removed, count still 337, a new session starts on the old DB, verified download kept for reuse |
| Playwright: filters → solve 3 → stats update | existing | PASS | `tests/e2e/test_mixer_flow.py::test_filters_then_solve_three` |

### Requirement IDs in scope

| ID | Method | Result | Evidence |
|---|---|---|---|
| FR-2.1 | real download, real-app cancel/resume, tests | PASS | Real download above. Real app: cancel at 33 MB keeps `.part`, the next Download resumes at 34 MB; `test_download_resumes_with_range`; UI not blocked (training continued during an update) |
| FR-2.2 | tests + real export | PASS | `tests/unit/test_csv_rows.py`, `test_reads_by_header_name_with_extra_columns`; real export (with `DailyDate`): 0 skipped rows |
| FR-2.3 | tests + real app | PASS | see the cancelled-import row; `test_failed_integrity_keeps_existing_db`, `test_swap_with_open_connections_on_other_threads`, `test_checksum_mismatch_refuses_and_deletes` |
| FR-2.4 | QA tests | **FAIL** | **B2**: after a re-import, a running session's queued keys point at different puzzles |
| §4.2 | tests | PASS | as Done when 1; promotion: `test_promotion_to_queen_solves`, `test_underpromotion_is_wrong` |
| FR-3.1 | e2e | PASS | `test_select_all_ticks_only_the_searched_themes`, `test_all_with_themes_that_never_co_occur_gives_zero`, `test_filters_then_solve_three` |
| FR-3.2 | e2e + oracle | PASS | `test_exclude_everything_included_gives_zero`; oracle specs with excludes |
| FR-3.3 | e2e | **FAIL** | **B3**: the maximum rating box can't be typed into. The slider and bounds work (`test_rating_slider_bounds_mean_no_limit`, `test_rating_filter_at_exact_dataset_bounds`) |
| FR-3.4, FR-3.5 | oracle + session tests | PASS | `test_count_matches_oracle[*]`, `test_puzzles_follow_the_filters_and_never_repeat` |
| FR-3.11 (random) | tests | PASS | `tests/unit/test_queue.py`, `test_same_seed_same_queue`, `test_rng_used_for_queue_is_the_injected_one` |
| FR-3.12 | tests + e2e | PASS | `test_endless_session_refills`, `test_fixed_queue_larger_than_pool_ends_when_exhausted`, `test_endless_session_has_no_total` |
| FR-3.14 | tests + e2e + real app | PASS | `test_bridge_round_trip` (no `themes` in PuzzleView), `test_themes_hidden_until_decided_and_skip_counts`, real-app flow |
| FR-4.1, FR-5.1, FR-5.3 | unit + QA | PASS | `tests/unit/test_standard_mode.py`; `test_attempt_fields_for_wrong_then_finished_line`, `test_moves_after_the_end_are_ignored`, `test_concurrent_wrong_moves_record_one_attempt` |
| FR-5.5 | QA test | PASS | `test_attempt_fields_for_wrong_then_finished_line` (time_ms 7000 from the injected clock), `test_first_move_right_then_wrong_records_first_move_correct`. B1 can record attempts that never happened. |
| NFR-1 | smoke + script | PASS | `test_second_launch_exits_and_first_keeps_running`; script: second `uv run python -m weaksquare --dev` exits 0 in 0.5 s, and the minimized first window is restored to the foreground |
| NFR-2 | test + observation | PASS | `tests/integration/test_data_dir_guard.py`; the real data folder was never created during QA |
| NFR-3 | tests | PASS | migration tests + QA app-level test |
| NFR-4 | test + real app | PASS with minor | Rotating log, version banner, crash hooks; front-end errors forwarded, rate limit 20/min plus a "dropped" note, redacted (`Bearer [REDACTED]`). WebView2 version not recorded (**B6**) |
| NFR-5 | tests | PASS | `tests/integration/test_bridge_errors.py`, `test_bridge_rejects_bad_arguments_without_crashing` (13 malformed calls, none `internal`) |
| NFR-6 | real app | PASS | Closing during a download: rc 0 in 1.4 s, job cancelled, `.part` kept, "Shutting down" logged |
| NFR-7 | smoke + screenshots | PASS with minor | About shows version, both paths with Open, export date, license, source link. Open buttons clipped with long paths (**B7**) |
| NFR-8 | setup run + pythonw launch | PASS | setup rc 0; the shortcut target `pythonw.exe -m weaksquare` starts the app with no console, title without "(dev)", closes rc 0. Fresh clone: manual (below) |
| SR-1 | grep | PASS (n/a) | No keyring use, no secrets in v0.1 |
| SR-2 | QA test | PASS | `test_bridge_rejects_bad_arguments_without_crashing` |
| SR-3 | tests + real app | PASS | `tests/contract/test_csp_local_assets.py`; smoke `test_no_browser_storage_and_csp_active` |
| SR-5, SR-10 | tests + real app | PASS | `tests/unit/test_logging_redaction.py`; front-end probe redacted |
| SR-6 | real download | PASS | Verified against Lichess's published SHA-256 |
| SR-12, SR-12a | tests + grep | PASS with minor | `tests/contract/test_fixtures_clean.py`; fixture GameUrls are `GAMEID01…`. See **B12** |
| SR-14b | review | PASS with minor | Python and npm dependencies match the plan; `uv lock --check` OK; lockfiles committed. `uv_build` (**B11**) |
| SR-16 | tests + grep | PASS | `tests/unit/test_sr16_refusal.py`, smoke `test_debug_port_refused_without_dev`; only `tests/smoke/conftest.py` sets the variable |

---

## Bugs

### v0.1-B1: major: two quick clicks on Next/Skip fail a puzzle you never saw
- **Steps:** Start a session, then click **Next puzzle** (or **Skip**) twice in quick succession (a double-click or an impatient second click).
- **Expected:** One move-on. You're on the next puzzle, and only the puzzle you skipped (if any) is a loss.
- **Actual:** Each click calls `next_puzzle`. The second one gives up the puzzle the first click just served, so it's recorded as a failed attempt and the session jumps ahead. Real app: after one Skip done as a double click, the bar shows **Failed 2** on **Puzzle 3 of 20**. In the mock, the same thing after a solve ends a 2-puzzle session at "1 solved, 1 failed". `TrainerView.load` has no in-flight guard, and the button stays enabled while it runs.
- **Impact:** False losses in the append-only `attempts` log. From v0.3 these would sync to Lichess as real losses.
- **Evidence:** `tests/smoke/test_qa_v01_real_app.py::test_two_quick_clicks_on_skip_fail_only_one_puzzle` (xfail strict: `('2', 'Puzzle 3 of 20') != ('1', 'Puzzle 2 of 20')`), `tests/e2e/test_qa_v01_ui.py::test_double_click_next_does_not_fail_an_unseen_puzzle`.

### v0.1-B2: major: a re-import during a session serves puzzles that don't match the filters
- **Steps:** Start a session (e.g. rating 400–600, Endless). Choose **☰ → Update puzzle database…** and let it finish (the User Guide says "You can keep training while it runs"). Then keep pressing Skip/Next.
- **Expected:** The session keeps serving only puzzles that match its filters, skips puzzles the new export dropped (FR-2.4), and never repeats one.
- **Actual:** The queue holds the dense `n` keys of the old `puzzles.db`. After the swap, those keys belong to different puzzles. Real app: after the swap, the 400–600 session served ratings `[1582, 1270, 499, 765, 468, 593, …]`. Integration: a Mate-in-1 session served `9i8sr` (themes `endgame mate mateIn2 rookEndgame short`). Dropped puzzles are never detected, and the no-repeat set is meaningless after the swap.
- **Evidence:** `tests/smoke/test_qa_v01_real_app.py::test_reimport_during_a_session_keeps_the_filters`, `tests/integration/test_qa_v01_edges.py::test_reimport_mid_session_keeps_serving_matching_puzzles` (both xfail strict).

### v0.1-B3: major: the Maximum rating box can't be typed into
- **Steps:** Click the **Maximum rating** box, select its contents and type `1600`.
- **Expected:** The maximum becomes 1600. User Guide: "type exact numbers in the boxes". Adam's manual test sets 1200–1600.
- **Actual:** Each keystroke is clamped at once (`Math.max(Math.min(v, hi), vmin)`). `1` becomes the minimum (339), and the next digits push it over the dataset maximum, which reads as "no limit". The box ends at `003297` and the count is unchanged. Per-keystroke values: `['339', '3297', '03297', '003297']`, and the same for `2500`. The Minimum box happens to work, because a clamp to the lower bound emits `null` and leaves the typed text alone. Playwright's `fill()` sets the whole value at once, which is why the builder's e2e test didn't catch it.
- **Evidence:** `tests/e2e/test_qa_v01_ui.py::test_typing_a_maximum_rating_keystroke_by_keystroke` (xfail strict); `::test_typing_a_minimum_rating_keystroke_by_keystroke` passes.

### v0.1-B4: major (test harness): the real-app smoke run is flaky
- **Steps:** `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` several times.
- **Expected:** Passes reliably (gate: "all … Playwright tests pass"; the Developer Guide command must work as written).
- **Actual:** `tests/smoke/test_real_app.py` over 6 runs: 5/7, 6/7, then 7/7 four times. Each error is `TimeoutError: timed out waiting for the app page`, raised by `page_ready()` in `tests/smoke/conftest.py::attach`. `/json/list` already listed the page, but `browser.contexts[*].pages` stayed empty for 30 s after `connect_over_cdp`. The failures came on the first, cold runs. This is test infrastructure only, with no product impact.
- **Evidence:** the run outputs above.

### v0.1-B5: minor: "1 puzzles match"
The count text is always plural (`MixerView.tsx`). Seen in the real app with Mate in 1 at rating 563–563 (`tests/e2e/artifacts/qa-v01-real-solved.png`).

### v0.1-B6: minor: the log banner never records the WebView2 version (NFR-4)
Every run logs `… | WebView2 unknown | …`, both in the dev folder's log and in QA runs, because `app.py` calls `setup_logging()` without `webview_version`.

### v0.1-B7: minor: About's Open buttons are clipped with a long data-folder path
With a long path, the **Open** buttons show as "Op" (`tests/e2e/artifacts/qa-v01-real-about.png`). Adam's real path is short, so this mostly affects dev and test paths.

### v0.1-B8: minor (docs): the CHANGELOG `[Unreleased]` first line is stale
It still says "…documentation set and repo guardrails. **No app code yet.**", while the lines below it describe the app.

### v0.1-B9: minor (docs): the Developer Guide tells humans to run bare `npm`
The §Dependencies prose says "add it with `uv add` or `npm install` … (`uv sync --locked`, `npm ci`)". Bare `npm` resolves to `npm.ps1`, which AllSigned PowerShell blocks (verified). It should say `npm.cmd`. The Commands table itself is correct.

### v0.1-B10: minor (docs): the privacy section doesn't list the browser links
"Nothing leaves your PC unless you use a feature that needs the internet. Those features are listed…" lists only the puzzle download. **Open this puzzle on Lichess** (which opens lichess.org/training/<id> in your browser) and About's source link aren't mentioned.

### v0.1-B11: minor (process): `uv_build` isn't in the approved plan's dependency list
`pyproject.toml` uses `uv_build>=0.13,<0.14` as its build backend. The plan says "Nothing else gets added". It is recorded in ARCHITECTURE §7 ("First dependencies"), but Adam should acknowledge it (SR-14b).

### v0.1-B12: minor (SR-12a): a real Lichess game URL in a test file
`tests/contract/test_fixtures_clean.py:43` uses `https://lichess.org/787zsVup/black#48`, the example game from the Lichess API docs, as the checker's positive control. SR-12a asks for no real game IDs or URLs in the public repo; a synthetic 8-character ID works just as well.

### v0.1-B13: minor: a docstring promises seed logging that doesn't happen
`adapters/system_clock.py::make_rng`: "The seed is logged so a session can be replayed". Nothing logs it.

---

## Tests added (all under `tests/`, ruff clean and formatted)
- `tests/integration/test_qa_v01_edges.py`: `test_attempt_fields_for_wrong_then_finished_line`, `test_first_move_right_then_wrong_records_first_move_correct`, `test_moves_after_the_end_are_ignored`, `test_concurrent_wrong_moves_record_one_attempt`, `test_fixed_queue_larger_than_pool_ends_when_exhausted`, `test_rating_filter_at_exact_dataset_bounds`, `test_reimport_mid_session_keeps_serving_matching_puzzles` (xfail B2), `test_app_refuses_newer_schema_user_db_untouched`, `test_bridge_rejects_bad_arguments_without_crashing`, `test_rng_used_for_queue_is_the_injected_one`
- `tests/fulldb/test_qa_v01_fulldb.py`: `test_all_and_exclude_across_bitmask_columns`, `test_count_with_many_excludes_under_500ms`, `test_sparse_rejection_sampling_under_500ms`
- `tests/e2e/test_qa_v01_ui.py`: `test_typing_a_minimum_rating_keystroke_by_keystroke`, `test_typing_a_maximum_rating_keystroke_by_keystroke` (xfail B3), `test_rating_slider_bounds_mean_no_limit`, `test_all_with_themes_that_never_co_occur_gives_zero`, `test_select_all_ticks_only_the_searched_themes`, `test_exclude_everything_included_gives_zero`, `test_mate_in_one_alternative_mate_is_accepted`, `test_double_click_next_does_not_fail_an_unseen_puzzle` (xfail B1), `test_wrong_move_then_finish_line_counts_once`, `test_themes_hidden_until_decided_and_skip_counts`, `test_endless_session_has_no_total`, `test_screens_for_visual_review`, `test_promotion_to_queen_solves`, `test_underpromotion_is_wrong`
- `tests/smoke/test_qa_v01_real_app.py`: `test_main_flow_alternative_mate_wrong_move_persistence`, `test_two_quick_clicks_on_skip_fail_only_one_puzzle` (xfail B1), `test_reimport_during_a_session_keeps_the_filters` (xfail B2)

The xfail tests are `strict=True`. When a bug is fixed, its test XPASSes and fails the run until the builder removes the marker, so each one becomes that bug's regression test.

---

## Scope, architecture, security
- **Scope:** nothing from a later version was found (grep for hint, engine, Stockfish, preset, ratio UI, OAuth, token, sync, LLM, SRS). The v0.2+ `FilterSpec` fields exist as the approved schema and are rejected (`unsupported_in_this_version`, tested). No `secret_store.py`, as planned.
- **`core/` does no I/O:** `test_core_purity.py` passes, and a grep found no `open`/`sqlite3`/`os`/`subprocess`/`httpx` in `core/`.
- **Composition root:** concrete adapters are built only in `app.py::build_services`/`main`. `scripts/fetch_puzzle_db.py` reuses `build_services` and constructs `SystemClock`/`make_rng` itself; that's acceptable for a CLI.
- **keyring:** not imported anywhere. **HTTP:** `httpx` is imported only in `adapters/http.py`.
- **Migrations:** first version; both `0001` files were added in one commit (`f740948`) and never edited.
- **§3 decisions 12–17:** one connection per thread (`test_connection_threads.py`; cross-thread access only under the exclusive swap lock, as documented). `Api` keeps its dependencies in underscore attributes, and the allowlist test passes. No browser storage in `web/src` (grep, contract test, smoke `localStorage.length == 0`). No `datetime.now`/`time.time`/global `random` in `core/` or `services/` (only `random.Random` type hints). Tests use temp folders (guard test; the real folder was never created).
- **Dependencies:** as planned, plus `uv_build` (B11). `uv.lock` and `web/package-lock.json` are committed.
- **Secrets:** no token or key patterns in tracked files, test artifacts or logs. pre-commit gitleaks passes. Fixture `GameUrl`s are `https://lichess.org/GAMEID01…`. Puzzle IDs are real Lichess puzzle IDs, which are public CC0 data, not personal. One real game URL in a test (B12).
- **SR-16:** only the smoke harness sets `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`. The app refuses it without `--dev` (tested in a subprocess), and the Start-menu shortcut has no `--dev` (verified on the `.lnk`).

## Docs
- `check_docs.py --strict`: 0 errors, 0 warnings. No `TODO(v0.1)` left.
- Developer Guide Commands table: every row run (see Evidence). All passed except the smoke row, which is flaky (B4). Prose problem: B9.
- User Guide sections followed against the app:
  - *Getting started*: the first-run screen, the Download progress stages, Cancel, resume and update via ☰ all match.
  - *Choosing your puzzles*: controls, labels and order match the screenshots. The "type exact numbers" step misleads for the maximum (B3).
  - *Solving a puzzle*: opponent move first, click moves, promotion chooser, Solved/Failed, themes revealed, Skip counts as failed, session bar and all-time totals all match.
  - *Installing from source*: setup steps and the "uv isn't on your PATH" gotcha match. `git clone` not run (no public repo yet).
  - *The About screen*: matches (B7 cosmetic).
  - *Your data and privacy*: B10.
- Screenshots in `docs/img/` regenerate byte-identically and match the text and captions.
- CHANGELOG `[Unreleased]` covers every user-visible Done-when item (import, cancel, filters, live count, solving, session bar, persistence). Stale first line: B8.
- Visual review (`tests/e2e/artifacts/qa-v01-*.png`, real app `qa-v01-real-*.png`): no layout breakage at 1280×900 or at the window's minimum size of 1000×700. Clipped Open buttons with long paths (B7).

## For Adam's manual test
- **Fresh clone → `python scripts/setup.py` → Start-menu shortcut → import into the real folder.** Not done by QA, because it would write to `%LOCALAPPDATA%\WeakSquare` and the real Start menu. The equivalent steps passed (temp APPDATA, temp data folder, pythonw launch).
- **Typing the rating range 1200–1600 will hit B3.** Use the slider for the maximum until it's fixed.
- Avoid double-clicking Next/Skip until B1 is fixed, or your all-time failures will include puzzles you never saw.
- **Open this puzzle on Lichess** and the About **Source code** link should open your default browser, not a window inside the app. Not verifiable over CDP.
- About → **Open** buttons should open File Explorer at the right folder (only the bridge call was tested, with a fake desktop).
- Drag-and-drop moves: QA drove only click-click moves.
- Ctrl+C during `fetch_puzzle_db.py` in a PowerShell window (it should print "cancelling…" and stop). It can't be sent from this shell.
- Close the **Update puzzle database** dialog while an update runs, then reopen it. Check that it still shows the progress, not fresh Download buttons. Not verified by QA.
- The live count on the first launch after a reboot (cold disk cache). QA measured ≤ 290 ms only with the file already cached.

---

# Re-verification: round 2, 2026-11-01

Fix commit `784155a` (branch `v0.1`). I re-tested B1–B10, B12 and B13. B11 (`uv_build` not in the plan) is left for Adam to decide and doesn't count against this round. No product code or docs were changed by QA. After a docs-screenshot run I restored `docs/img/solved.png` with `git checkout` (see B14).

## Verdict: **PASS WITH ISSUES** (minor only)

Every major bug is fixed and verified. The remaining items are minor: B11 (Adam's call), plus two new minor ones, B14 and B15.

## Fixed bugs re-tested

| Bug | Result | Evidence |
|---|---|---|
| B1 double click on Next/Skip | **Fixed** | Strict-xfail tests now pass: `tests/smoke/test_qa_v01_real_app.py::test_two_quick_clicks_on_skip_fail_only_one_puzzle` (real app: Failed 1 on Puzzle 2 of 20) and `tests/e2e/test_qa_v01_ui.py::test_double_click_next_does_not_fail_an_unseen_puzzle`. New: `test_double_click_skip_mid_puzzle_fails_only_the_shown_puzzle` |
| B2 re-import mid-session | **Fixed** | Real app: `test_reimport_during_a_session_keeps_the_filters` now keeps every rating in 400–600. Integration: `test_reimport_mid_session_keeps_serving_matching_puzzles`. New edge tests: `test_puzzle_in_progress_survives_a_swap_that_drops_it`, `test_two_swaps_in_one_session_never_repeat` (covers the whole pool exactly once across two swaps), `test_swap_to_an_export_with_no_matches_ends_the_session` |
| B3 typing the maximum rating | **Fixed** | `test_typing_a_maximum_rating_keystroke_by_keystroke` passes. New: `test_typed_maximum_updates_the_count_on_tab`, `test_typed_maximum_applies_when_start_is_clicked_straight_away` (the blur on clicking Start commits it; the served puzzle is rated 485), `test_maximum_below_minimum_pulls_the_minimum_down`, `test_cleared_rating_box_reverts_on_blur` |
| B4 flaky smoke harness | **Fixed** | `uv run pytest -m smoke` 6 runs in a row: 10 passed every time (60/60), about 66 s per run |
| B5 "1 puzzles match" | **Fixed** | Real app shows "1 puzzle matches" (`tests/e2e/artifacts/qa-v01-real-about.png`) |
| B6 WebView2 version | **Fixed** | Real-app log banner: `WebView2 156.0.4314.50` |
| B7 clipped Open buttons | **Fixed** | Real-app screenshot with a long pytest path: both Open buttons fully visible; `tests/smoke/test_real_app.py` now checks their bounds at 1000×700 |
| B8 stale CHANGELOG line | **Fixed** | "No app code yet." removed |
| B9 bare `npm` in the Developer Guide | **Fixed** | Now `npm.cmd --prefix web install` / `npm.cmd --prefix web ci` |
| B10 privacy section | **Fixed** | New bullet "Links that open your browser" |
| B12 real game URL | **Fixed** | Now `lichess.org/Xy12Ab34` |
| B13 seed not logged | **Fixed** | Log shows `random seed: <n>` right after the banner |

## Full suite (round 2)

| Command | Result |
|---|---|
| `uv run pytest` | 192 passed (includes 3 new round-2 integration tests) |
| `uv run pytest -m fulldb` | 45 passed (143 s) |
| `uv run pytest -m e2e` | 23 passed (includes 5 new round-2 tests) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` ×6 | 10 passed ×6 |
| `uv run pytest -m docs_screenshots` | 4 passed; `solved.png` differs from the committed file (B14) |
| ruff check / format, mypy, tsc, ESLint, `pre-commit run --all-files`, `uv lock --check` | all clean |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings |

`%LOCALAPPDATA%\WeakSquare` still doesn't exist; the real Start menu was not touched.

## New findings (round 2)

### v0.1-B14: minor: the committed `docs/img/solved.png` isn't what the screenshot spec produces
Four runs of `uv run pytest -m docs_screenshots` all produce the same `solved.png` (sha1 `1585b4af…`), but it differs from the committed file (`ee74d92c…`). The two look identical, so the difference is pixel-level only. The other six images match byte for byte. The builder should regenerate and commit it at the handoff.

### v0.1-B15: minor (docs): the User Guide doesn't say when a typed rating applies
After the B3 fix, a typed rating takes effect when you press Enter or leave the box; the count doesn't change while you type. The *Choosing your puzzles* table still just says "type exact numbers in the boxes". Suggested addition: "…then press Enter or click elsewhere."

## Tests added in round 2
- `tests/integration/test_qa_v01_edges.py`: `test_puzzle_in_progress_survives_a_swap_that_drops_it`, `test_two_swaps_in_one_session_never_repeat`, `test_swap_to_an_export_with_no_matches_ends_the_session`
- `tests/e2e/test_qa_v01_ui.py`: `test_typed_maximum_updates_the_count_on_tab`, `test_typed_maximum_applies_when_start_is_clicked_straight_away`, `test_maximum_below_minimum_pulls_the_minimum_down`, `test_cleared_rating_box_reverts_on_blur`, `test_double_click_skip_mid_puzzle_fails_only_the_shown_puzzle`

## Still for Adam's manual test
Everything listed in round 1 still applies, except the B1 and B3 warnings, which are no longer needed. Also decide on B11 (`uv_build`).
