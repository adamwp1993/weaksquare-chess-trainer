# QA report: v0.4 (Stockfish)

**Round 1, 2026-11-02.** Branch `v0.4` at `0caa60e`. Independent QA. No product code, migrations, config or docs were changed; new tests are only under `tests/` (`test_qa_v04_*`). Not run, per the hard rules: `pytest -m live`, any keyring read, any call to lichess.org. Network used: github.com only (the pinned sf_19 asset, 3 times, plus the unauthenticated releases API for the published digest). The real app ran only with `--dev` and temp `WEAKSQUARE_DATA_DIR` folders. `%LOCALAPPDATA%\WeakSquare` still doesn't exist; the dev folder's `user.db` / `puzzles.db` / `engines\sf_19` mtimes are unchanged (08:29 / 11-01 13:42 / 12:34).

## Verdict: **FAIL** (two major bugs)

Every *Done when* item passes with evidence, and the real app works end to end (install from the banner, refutation, panel, analysis board, FR-7.3 enforced over the bridge). Two **major** bugs block the gate:
- **B1:** after an engine **timeout**, a python-chess thread never ends, so the Python process can't exit (NFR-6). As a direct consequence, `uv run pytest` (Developer Guide) prints its summary and then **never returns**; CI would hang until the job timeout.
- **B4:** the documented `--engine-path PATH` (and the older `--fulldb-path PATH`) fails with "unrecognized arguments" whenever PATH exists.

The rest are minor (B2, B3, B5, B6, B7).

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder: **682 passed**, 224 deselected (110 s), then the process **hangs at exit** (B1; killed after 2 min idle). With QA tests: **712 passed, 2 xfailed** (B1, B2), 237 deselected; summary printed at 302 s, then the process sat idle until `timeout 420` killed it (rc 124). The builder's own run from 12:48 (`pytest -v -p no:randomly`, PID 56148) was still alive and idle at 14:30 |
| `uv run pytest -m e2e` | builder: **120 passed** (281 s). QA file: **6 passed, 1 xfailed** (B3) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **19 passed, 1 failed, 1 skipped** under load (QA engine tests ran in parallel); the failure, `test_qa_v02_real_app.py::test_enter_after_mouse_clicks_is_next_in_the_real_app`, passes alone (3 passed). QA file: 1 passed + the download test (1 passed with `QA_V04_DOWNLOAD=1`) |
| `uv run pytest -m engine` (dev folder's managed sf_19) | builder: **6 passed** (5.6 s). With QA: 10 tests; QA refutation-length test is intermittent (B2) |
| `uv run pytest -m engine --engine-path PATH` | **fails**: `pytest: error: unrecognized arguments: --engine-path` when PATH exists (B4). `--engine-path=PATH` works (9 passed, 1 = B2) |
| `uv run pytest -m fulldb` (full DB imported: dev `puzzles.db`, 1.67 GB) | **58 passed, 1 failed, 1 xfailed** (v0.2-B2, known) in 531 s, run in parallel with the smoke suite; the failure (`test_ratio_count_full_range_within_known_limit`, 1.50 s vs 0.7 s) passes alone (5.3 s). Load flake, not a v0.4 regression |
| `uv run python scripts/fetch_stockfish.py` with a temp `WEAKSQUARE_DATA_DIR` | fresh install in 5.9 s: `installed Stockfish 19`; `downloads\` empty; `engines\` holds only `sf_19\{install.json, stockfish.exe}`; exe SHA-256 `45bc8e49…bcbd0` = the dev install's |
| same, second run | `already installed: Stockfish 19 (nothing to do)` in 1.2 s, no download |
| same, `--force` | `installed Stockfish 19`, no leftovers |
| `uv run python scripts/fetch_stockfish.py --dev` | `already installed: Stockfish 19 (nothing to do)`; dev install untouched (mtimes 12:34) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db` (temp `WEAKSQUARE_DATA_DIR`; not bare, it writes real shortcuts) | rc 0; the new **Stockfish** step ran `uv run python scripts/fetch_stockfish.py` and installed into the temp folder; ends "Setup complete. Start the app with: uv run python -m weaksquare". `--skip-engine` path prints "skipped (--skip-engine). You can install it from inside the app instead." |
| `uv run python -m weaksquare --dev` (temp data folder) | window up, WM_CLOSE, exit 0; banner `… WebView2 156.0.4314.58 \| Stockfish: not installed (sf_19 pinned)`; 0 ERROR lines |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` | window up, exit 0, 0 ERROR lines |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200 |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 198 files formatted (QA files formatted too) |
| `uv run mypy src` | no issues in 67 source files |
| `npm.cmd --prefix web run typecheck` / `lint` | clean / clean |
| `uv run pre-commit run --all-files` | gitleaks Passed; keyring-only Passed |
| `python scripts/check_docs.py --strict` (and without) | `check_docs: 0 error(s), 0 warning(s) [version v0.4]` |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run pytest -m docs_screenshots` | 15 passed; `docs/img` byte-identical (no git diff) |
| `uv run python scripts/make_icon.py --check` | up to date |
| `uv lock --check` | up to date |
| GitHub digest (`api.github.com/repos/official-stockfish/Stockfish/releases/tags/sf_19`, unauthenticated) | `stockfish-windows-x86-64-universal.zip sha256:3c8bf1f9…b48a7`, size 81431614, same URL: **matches** `engine_manifest.json` |
| `fetch_puzzle_db.py --dev`, `record_db_update.py`, `set_test_token.py`, `-m live` | not run (unchanged since v0.3; would replace the dev DB / call Lichess / need credentials) |

No Developer Guide, README or User Guide command uses `.ps1`, bare `npm`/`npx` or venv activation.

---

## Traceability

### Done when (ROADMAP v0.4)

| Item | Method | Result | Evidence |
|---|---|---|---|
| Engine integration tests: a known position gives the expected best move | existing (real sf_19) | PASS | `engine/test_real_stockfish.py::test_mate_in_one` (Ra8#, mate 1), `::test_takes_a_hanging_queen` (Rxd5), `::test_black_to_move_scores_are_white_relative` (…Ra1#), `::test_multipv_gives_three_distinct_lines`, `::test_probe_reports_stockfish_19`; also run against a fresh install from the temp folder (`--engine-path=`) |
| No eval visible while solving (Playwright) | existing + QA (mock, real app, bridge) | PASS | `e2e/test_engine_ui.py::test_no_eval_or_lines_while_solving` (start, correct move, wrong move, hint; no `analyze:`/`refutation` call made). QA bridge probe `integration/test_qa_v04_engine.py::test_qa_bridge_refuses_engine_output_at_every_step_until_the_end` (all three purposes + `get_refutation` refused with `conflict` at start, after a correct move, after a wrong move while still playing, after a hint; engine never started; allowed after the line ends; refused again after Next, even for the FEN cached on the previous puzzle). Real app `smoke/test_qa_v04_real_app.py::test_engine_flow_in_the_real_app` (`window.pywebview.api.analyze_position` / `get_refutation` return `conflict` after a wrong move; nothing on screen; same after Next). QA e2e `::test_qa_next_while_the_panel_is_thinking_leaks_nothing`, `::test_qa_next_while_the_refutation_loads` |
| Installer: hash mismatch refuses and leaves nothing behind | existing + manual | PASS | `integration/test_engine_install.py::test_hash_mismatch_refuses_and_leaves_nothing_behind` (no `.part`, temp folder, zip or `engines/sf_19`). Code order: hash (`_hash`) before `zip_names`/`extract` |
| Installer: a zip with `..` paths is rejected | existing | PASS | `::test_zip_with_unsafe_paths_is_rejected[..]` (+ absolute, drive letter), `unit/test_engine_core.py::test_check_zip_names_rejects_the_whole_archive` |
| Installer: a second run does nothing | existing + manual | PASS | `::test_second_run_does_nothing` (no HTTP request); real script second run 1.2 s "nothing to do" |
| Invalid position past validation: one restart and a clean error, not a hang | existing (fake UCI + real sf_19) + QA | PASS for the crash path; **B1** for the timeout path | `integration/test_stockfish_adapter.py::test_invalid_position_restarts_once_and_fails_cleanly` (CRITICAL ERROR logged, `engine_crashed`, next request works), `engine/test_real_stockfish.py::test_invalid_input_restarts_once_and_fails_cleanly` (real sf_19, 1 restart, < 15 s). The **timeout** recovery leaves a stuck thread: QA `::test_qa_process_exits_after_an_engine_timeout` (xfail strict) |

### Requirement IDs in scope

| ID | Method | Result | Evidence |
|---|---|---|---|
| FR-7.1 (universal build over UCI) | existing + manual | PASS | manifest asset `stockfish-windows-x86-64-universal.zip`, `exe_member` confirmed by the real install; probe reports "Stockfish 19" |
| FR-7.2 (refutation, MultiPV 3, evals "for you") | existing + QA + real app | PASS except **B2** | `unit/test_engine_core.py::test_format_score_from_your_side`; panel shows 3 lines (`test_panel_appears_after_the_puzzle`; real app screenshot `qa-v04-real/refutation-and-panel.png`: "+6.1 for you", lines in SAN from Black's move number "14… Ne5"); refutation 3–5 plies: QA real-engine `test_qa_refutations_are_3_to_5_plies_unless_the_game_ends` failed 1 run in 4 (B2) |
| FR-7.3 (nothing during the puzzle; backend refuses) | existing + QA | PASS | see Done-when row |
| FR-7.4 (think time, threads, hash; defaults) | existing + QA | PASS | `test_engine_service.py::test_settings_defaults_and_validation` (1.0 / CPUs−1 / 256); QA `::test_qa_bridge_rejects_bad_engine_settings[15]` (bool, NaN, inf, 0.19, 10.01, −1, 9 threads on 8 CPUs, 15/2049/256.5 MB, bad paths, `force:"yes"`; nothing saved), `::test_qa_engine_settings_bounds_are_accepted_and_persist` (0.2, 10, 1, 8, 16, 2048; persist in a fresh Api); UI rejects out-of-range input with the backend's message (QA probe; see B7) |
| FR-7.5 (pinned manifest, verify, extract only the exe, temp+rename, smoke test, idempotent, in-app Install, custom path) | existing + QA + real app | PASS | installer tests (18), `contract/test_engine_manifest.py`; GitHub digest matches; three real installs (script, setup step, in-app button). Real app `::test_install_from_the_banner`: banner → Install → progress → panel, no restart; `downloads\` empty, no temp folders, log "installed Stockfish 19". Custom path: `test_custom_engine_is_saved_only_after_the_probe`; QA real probe of `C:\Windows\System32\sort.exe` (refused within the bound, process gone) and of a text file renamed `.exe` (refused < 5 s) |
| FR-7.6 (validate everything; crash → log, one restart, clean error) | existing + QA | PASS (timeout path: **B1**) | `unit/test_engine_core.py::test_validate_fen_rejects`, QA `::test_qa_bad_positions_are_refused_before_the_engine[9]` (two kings, side not to move in check, castling rights without rooks, impossible e.p., pawn on rank 8, non-string, 200 chars; engine never called), QA real engine `::test_qa_awkward_positions_never_crash_the_real_engine` (castling both sides, e.p. both colours, promotions, capture-promotion, in check, 50-move counter 99: no restart, every pv move legal) |
| FR-7.7 (start eval pinned, follows the board, analysis board, Back/Forward/Reset/Close, not scored) | existing + QA + real app | PASS | `test_analysis_board` (move, eval, legal arrow, Reset, Close, "Solved 1" unchanged); QA `::test_qa_analysis_board_underpromotion` (a2a1 → Knight → `a1=N`, Back); QA `::test_qa_game_over_positions_never_reach_the_engine` (mate / stalemate / K v K answered without the engine); QA `::test_qa_rapid_stepping_asks_about_the_newest_position_only` (5 steps in a burst → ≤ 1 request); real app: move, legal arrow, Close |
| §7.2 step 2 (refutation in Show answer) | existing + QA + real app | PASS except B2, B3 | `test_refutation_comes_before_the_solution`; real app "Why Rg8 fails: −1.1 for you" then The solution |
| NFR-4 (Stockfish on the log banner) | existing + real app | PASS (B6 for custom engines) | `test_log_banner_names_the_engine`; real app first line `Stockfish: Stockfish 19 (sf_19, managed)` / `not installed (sf_19 pinned)`; `engine started: Stockfish 19 (pid …)`; **no `chess.engine` lines, no `<<`/`>>` UCI traffic, 0 ERROR lines** in the log (`test_engine_flow_in_the_real_app`) |
| NFR-6 (stop the engine on close) | existing + QA + real app | **FAIL (B1)**; B5 minor | `test_close_stops_the_engine`; real app: no `stockfish.exe` under the data folder after exit (exit took **5.4 s** when closed during a 5 s search: B5). After a timeout the process never exits (B1) |
| NFR-7 (About: version and path) | e2e + real app | PASS | `test_about_shows_stockfish`; real app `qa-v04-real/about.png` ("Stockfish 19 (sf_19)" + path) |
| SR-6 (HTTPS, official source, hash) | existing + manual | PASS | manifest URL is the https GitHub release asset; `parse_manifest` refuses non-`https://github.com/` URLs; hash checked before extraction; digest matches GitHub's |
| CPU sanity | QA real engine | PASS | `::test_qa_engine_is_idle_between_searches`: < 0.2 s CPU over 4 s idle after a search; the engine isn't even started until the first finished puzzle (lazy; `FakeEngine.instances == []` during solving) |

---

## Bugs

### v0.4-B1 (major): after an engine timeout the process can't exit; `uv run pytest` never returns
- **Steps:** any search that hits the timeout (think time + 10 s): a hung or slow engine, a custom engine that ignores `go movetime`, a frozen PC. Then close the app (or end the test run).
- **Expected:** NFR-6, the process exits. FR-7.6, "it never hangs". The Developer Guide's `uv run pytest` returns.
- **Actual:** `StockfishEngine.analyse` catches `TimeoutError` and `_restart_after` calls `SimpleEngine.close()`. When the killed process's pipes close, python-chess 1.11.2 raises `asyncio.InvalidStateError` in `connection_lost` (the analysis future was already cancelled by the timeout). So `protocol.returncode` is never set, and the **non-daemon** `SimpleEngine (pid=…)` thread waits forever. The interpreter can't exit, and stderr gets "Exception in callback BaseSubprocessTransport._call_connection_lost". In the app, the window closes but `python.exe` stays alive, holding `weaksquare.lock`. Every later launch then thinks the app is already running, until it's killed in Task Manager.
  - The default suite triggers this on every run: `tests/integration/test_stockfish_adapter.py::test_hang_times_out_restarts_and_fails`. Alone, that test passes in ~1 s, but the process never ends (`timeout 40` → rc 124). The whole suite prints "682 passed" and then sits idle.
  - The builder's own run, PID 56148, started 12:48, was still idle at 14:30. QA left it running because it isn't QA's process.
- **Evidence:**
  - `tests/integration/test_qa_v04_engine.py::test_qa_process_exits_after_an_engine_timeout` (xfail strict). It runs in a child Python, so it doesn't hang pytest itself.
  - The same happens with the **real sf_19**: a scratch script forced a 0.5 s timeout on a 3 s search. After `close()`, `threading.enumerate()` showed `['MainThread', 'SimpleEngine (pid=55924)']` and the process didn't exit.
  - The crash path (`EngineTerminatedError`) is fine: those tests exit normally.
- **Note:** `test_qa_close_during_a_hung_search_returns_within_the_bound` passes: `close()` itself returns in time, and the search fails with `engine_timeout`. Only the exit is broken.

### v0.4-B4 (major, docs/test harness): `--engine-path PATH` as documented fails
- **Steps:** `uv run pytest -m engine --engine-path C:\path\to\stockfish.exe` (an existing file), exactly as the Developer Guide row says ("add `--engine-path PATH`").
- **Expected:** the engine tests run against that exe.
- **Actual:** `pytest: error: unrecognized arguments: --engine-path` and `rootdir: <the exe's folder>`. pytest takes the existing path as a `file_or_dir` argument, picks the rootdir from it and never loads `tests/conftest.py`, where the option is registered. `--engine-path=PATH` works. A path that doesn't exist also "works" (it skips).
  - The v0.1 row `--fulldb-path PATH` has the same failure (checked with the dev `puzzles.db`); earlier QA missed it.
- **Evidence:** command output in the table above.

### v0.4-B2 (minor): the refutation is sometimes only 2 plies
- **Steps:** play a wrong move in a puzzle, then Show answer (default think time 1 s, real sf_19).
- **Expected:** §7.2 step 2 asks for "the best reply line, 3–5 plies", and the plan says "fewer if the game ends".
- **Actual:** the line is `pv[:5]` of whatever Stockfish returns. Stockfish sometimes returns a 2-ply pv (a TT cut), and that's shown as is. Seen: puzzle RDPB7, wrong move e8f7, line `c2b3 b7b6`, "−1.0 for you", with the game going on. It happened in 1 run of 4 over 12 puzzles.
- **Evidence:**
  - `tests/integration/test_qa_v04_engine.py::test_qa_refutation_is_at_least_3_plies_when_the_game_goes_on` (xfail strict: a 2-ply pv from the engine gives a 2-ply refutation).
  - `tests/engine/test_qa_v04_real_engine.py::test_qa_refutations_are_3_to_5_plies_unless_the_game_ends` (xfail, non-strict: intermittent).
- **Suggested direction (not applied):** extend a short pv with follow-up searches, or ask for a minimum depth.

### v0.4-B3 (minor): a refutation error arriving after Next shows on the next puzzle
- **Steps:** wrong move → Show answer → click **Next puzzle** while "Stockfish is checking your move…" is showing. The refutation request then fails (`engine_crashed`, `engine_timeout`).
- **Expected:** nothing from the previous puzzle on the new one.
- **Actual:** `TrainerView.loadRefutation` guards the success path (`a.positions === solution`), but not the error path. The red error appears under the new puzzle's board while you solve it. The same applies to `engine_not_installed` (the install banner) and to `setRefutation(null)` clearing a newer "loading" state.
- **Evidence:** `tests/e2e/test_qa_v04_ui.py::test_qa_refutation_error_after_next_is_not_shown_on_the_next_puzzle` (xfail strict). With `--runxfail`: `assert 1 == 0`, with the text "Stockfish stopped unexpectedly and was restarted. Try again." on the new puzzle.

### v0.4-B5 (minor): closing during a search waits for it to finish
- **Steps:** set Think time to 5–10 s, open the engine panel on a new position, and close the window at once.
- **Expected:** NFR-6, the engine is stopped and the app exits promptly.
- **Actual:** `StockfishEngine.close()` takes the request lock, so it waits for the running search to end. Measured: the app exited 5.4 s after WM_CLOSE with a 5 s think (`close()` alone: 4.5 s). With the 10 s maximum, the process (and `weaksquare.lock`) stays up to ~10 s after the window is gone, and a relaunch in that time does nothing visible. The engine process does end, and nothing is left behind.
- **Evidence:** `tests/engine/test_qa_v04_real_engine.py::test_qa_close_during_a_real_search` (prints the time), real app `test_engine_flow_in_the_real_app` ("app exit took 5.4 s").

### v0.4-B6 (minor): the NFR-4 banner ignores a custom engine
- With a custom engine set, the first log line still describes the managed install only: `not installed (sf_19 pinned)`, or `Stockfish 19 (sf_19, managed)` when both exist. The cause is `app.main` → `build_engine_installer(...).describe()`, which never reads `engine.custom_path`. The engine's name is only logged later, when it first starts (`engine started: …`). The plan's banner line was `sf_19 (managed) | custom | not installed`.
- **Evidence:** code (`app.py` main, `EngineInstaller.describe`). It's not visible in the UI. A related gap: About shows "Not installed (Settings → Engine)" when a custom engine is set but its file is gone (`custom_invalid`).

### v0.4-B7 (minor, cosmetic): Settings → Engine keeps showing a rejected value
- Typing an out-of-range value (Think time 50, Threads 0, Hash 99999) shows the backend's message. Nothing is saved, which is correct. But the field keeps showing the rejected number (e.g. "50") while the engine uses 1 s.
- **Evidence:** QA probe against the mock (`shown: 50 … saved: think_s 1`).

### Not bugs (load flakes seen this round)
`fulldb/test_qa_v02_fulldb.py::test_ratio_count_full_range_within_known_limit` (1.50 s vs 0.7 s) and `smoke/test_qa_v02_real_app.py::test_enter_after_mouse_clicks_is_next_in_the_real_app` failed only while other suites ran in parallel. Both pass alone.

---

## Tests added (all under `tests/`)
- `tests/integration/test_qa_v04_engine.py` (normal suite):
  - `test_qa_bridge_refuses_engine_output_at_every_step_until_the_end`
  - `test_qa_game_over_positions_never_reach_the_engine`
  - `test_qa_bridge_rejects_bad_engine_settings[×15]`
  - `test_qa_engine_settings_bounds_are_accepted_and_persist`
  - `test_qa_bad_positions_are_refused_before_the_engine[×9]`
  - `test_qa_probe_refuses_a_program_that_waits_on_stdin_and_kills_it` (real `sort.exe`)
  - `test_qa_probe_refuses_a_file_that_is_not_a_program`
  - `test_qa_close_during_a_hung_search_returns_within_the_bound`
  - `test_qa_process_exits_after_an_engine_timeout` (xfail strict, B1)
  - `test_qa_refutation_is_at_least_3_plies_when_the_game_goes_on` (xfail strict, B2)

  The NFR-6 tests run in a child Python, so B1 can't hang pytest.
- `tests/engine/test_qa_v04_real_engine.py` (`-m engine`):
  - `test_qa_refutations_are_3_to_5_plies_unless_the_game_ends` (xfail non-strict, B2)
  - `test_qa_awkward_positions_never_crash_the_real_engine`
  - `test_qa_engine_is_idle_between_searches`
  - `test_qa_close_during_a_real_search` (B5 timing)
- `tests/e2e/test_qa_v04_ui.py` (`-m e2e`):
  - `test_qa_screenshots_of_every_v04_screen[light/dark]` (8 screens each)
  - `test_qa_rapid_stepping_asks_about_the_newest_position_only`
  - `test_qa_next_while_the_panel_is_thinking_leaks_nothing`
  - `test_qa_next_while_the_refutation_loads`
  - `test_qa_refutation_error_after_next_is_not_shown_on_the_next_puzzle` (xfail strict, B3)
  - `test_qa_analysis_board_underpromotion`
- `tests/smoke/test_qa_v04_real_app.py` (`-m smoke`):
  - `test_engine_flow_in_the_real_app`: copies the dev folder's managed install into a temp folder. It covers the bridge refusals, refutation, panel, stepping, analysis board, Next, About, closing during a search, no engine process left, and a clean log banner.
  - `test_install_from_the_banner`: downloads from github.com, so it runs only with `QA_V04_DOWNLOAD=1`.

Each strict xfail is the regression test for its bug: the fix removes the marker.

---

## Scope / architecture / security
- **Scope:** nothing from v0.5+.
  - There's no background engine or analysis queue: the protocol docstring only mentions v0.8.
  - No Danger spotting, no wizard.
  - macOS and Linux keys are only mapped so they can be refused.
  - No LLM or chess.com code.
- **Dependencies:** none added. The `uv.lock`, `package-lock.json` and `package.json` diffs are the version bump only (0.3.0 → 0.4.0). `uv lock --check` is clean.
- **Layers:**
  - `core/engine.py` is pure: python-chess and dataclasses, no I/O.
  - No `datetime.now` / `time.time` / global `random` in `core/` or `services/`. `install.json`'s time comes from the Clock, and `rename_with_retry` (which sleeps) is injected from adapters.
  - `StockfishEngine`, `probe_engine` and the installer deps are constructed only in `app.py`. The scripts use `app.build_engine_installer`.
  - keyring is only in `secret_store.py` (pre-commit hook passes).
  - The download goes through `adapters/http.py`.
  - `Api._engine` is an underscore attribute, and the allowlist test was updated with the 9 methods.
  - Settings use `Database.session()` per call. No migration was added, and 0001–0003 are untouched.
- **Threads:** engine calls run on bridge threads, serialized by the adapter lock. `SessionService` releases the session lock before searching. There's one engine only (the interactive one).
- **Browser storage:** none in `web/src` (grep plus `contract/test_no_browser_storage.py`).
- **Security:**
  - The manifest pins tag, URL, size and SHA-256, and the digest matches GitHub's.
  - The hash is checked **before** the zip is opened.
  - The whole archive is refused on any unsafe name. Only `exe_member` is extracted, with a 512 MB cap.
  - Engine output is treated as untrusted. The backend keeps only the legal prefix of each pv. The UI's `pvToSan` stops at the first illegal move, `legalArrow` checks legality before drawing, and all text is plain React text (no `innerHTML` / `dangerouslySetInnerHTML` in `web/src`). The engine's `id name` is rendered as text.
  - No token, key or real-looking secret is in the repo or `tests/e2e/artifacts`. The mock paths use `C:\Users\you\…`.
  - The CDP port is still set only by the smoke harness, and `app.py` refuses it outside `--dev` (SR-16).
- **Data folders:** tests and QA used temp folders. The real folder is absent, and the dev folder is unchanged.

## Docs
- `check_docs.py --strict`: 0 errors, 0 warnings [v0.4]. No `TODO(v0.4)` left.
- **Developer Guide:** every row was run as written, except those listed in the table (DB fetch, recorder, token, live). All work except `--engine-path PATH` / `--fulldb-path PATH` (**B4**). Also note `uv run pytest` hangs at exit (**B1**). The setup row (`--skip-engine`, `--dev`), the fetch row (`--dev`, `--force`, "does nothing if the install matches") and the upgrade recipe all match the code.
- **User Guide, *Stockfish* chapter:** followed against the mock and the real app.
  - The banner text and the **Install Stockfish** button match, and no restart is needed after the install.
  - "Why *your move* fails", then **The solution**, and the "first wrong move" rule all match.
  - The panel's **Puzzle start** / **This position** and the eval wording match. So do **Analyze on the board**, Back / Forward / Reset / Close and "nothing scored".
  - The settings table matches: labels **Think time (s)**, **Threads**, **Hash (MB)**, **Use my own engine…**, **Use the managed Stockfish**, **Reinstall**, with defaults 1 / CPUs−1 / 256 and ranges 0.2–10 and 16–2048.
  - The privacy line ("one file from github.com … nothing about you is sent") matches the installer's single download.
  - Minor nit: "If Stockfish ever stops unexpectedly, the app restarts it and says so" holds for crashes. After a timeout it's B1.
- **CHANGELOG `[Unreleased]`** covers every user-visible item: refutation, panel ("never shown while you're solving"), analysis board, Install, Settings → Engine and About, and the setup/fetch script.
- **ARCHITECTURE:** §2 lists `core/engine.py`, `services/engine*.py` and `adapters/stockfish.py`. §7 has the two v0.4 entries (engine model and installer). README's status line is due at sign-off, per the plan.
- **Screenshots:** `docs_screenshots` regenerates byte-identical images. `engine-install.png`, `refutation.png`, `engine-panel.png`, `analysis-board.png` and `settings-engine.png` show the v0.4 screens.

## Visual check
- 16 mock screenshots are in `tests/e2e/artifacts/qa-v04/`. They cover Light and Dark: refutation step 2, engine panel, analysis board with arrow, install banner, install progress, Settings engine (managed and custom) and About.
- 7 real-app screenshots are in `qa-v04-real/`: no engine after a wrong move, refutation plus panel, analysis board, About, banner, progress, installed panel.
- No clipping or broken layout. The pv text wraps cleanly, and the Dark banner (orange) is readable. The Engine section sits at the bottom of a scrolling Settings modal, as before.

## For Adam's manual test
- Compare the manifest SHA-256 with the digest on the sf_19 release page. QA saw `3c8bf1f9…b48a7` from the API, and it matched.
- Watch Task Manager's CPU while stepping through a long answer with the default settings. The engine idled in QA's measurement.
- Check a few refutations **as a chess player**: QA only checks legality, length and wording.
- Try a custom engine through the real **Use my own engine…** file dialog: a real Stockfish build, then a non-engine `.exe`. The native dialog can't be driven over CDP. QA tested the same probe through the bridge with `sort.exe`.
- After the B1 fix: confirm closing the app always ends `python.exe` (Task Manager), including right after an engine error.

---

# Round 2, 2026-11-02 (re-verification)

Branch `v0.4` at `b59e503` ("QA v0.4 round 1 … fix all seven"). Same rules as round 1: no product code changed by QA, no `-m live`, no credentials, no Lichess calls. `%LOCALAPPDATA%\WeakSquare` still doesn't exist; the dev folder is unchanged.

## Verdict: **FAIL** (one new major bug)

All seven round-1 bugs are fixed and verified. Round 2 found **v0.4-B8**: the B1/B5 fixes leave one gap. If the window closes while the engine is still **starting** (about 0.35 s for sf_19, on the first search of a run or the first after an engine or settings change), the engine process survives `close()` and Python never exits. That's the same outcome as B1: `python.exe` stays, holding `weaksquare.lock`. The likelihood is low, but the impact is the one B1 was rated major for, and the fix is small.

## Re-verification of round-1 bugs

| Bug | Fix | Result | Evidence |
|---|---|---|---|
| B1 (major) process can't exit after a timeout | `_release_thread` resolves python-chess's stuck `returncode` future 1 s after `_close` | **FIXED** | `uv run pytest` now exits by itself (summary at 168 s, process gone at 169 s; round 1 hung). `test_qa_process_exits_after_an_engine_timeout` passes. **Real app, real timeout:** new QA smoke `test_qa_v04_r2_timeout_real_app.py::test_app_exits_after_an_engine_timeout`. A custom UCI engine (C#, compiled at test time with Windows' `csc.exe`) passes the self-test but hangs on any puzzle position. The app showed "didn't answer in time" after ~11 s and logged "engine timed out" / "engine restarted after a timeout". After WM_CLOSE it **exited in 4.2 s**, the app's `python.exe` was gone, the lock could be re-acquired, and no engine process was left |
| B4 (major) `--engine-path PATH` | Developer Guide writes `--engine-path=PATH` / `--fulldb-path=PATH`; guard test | **FIXED** | As written now: `uv run pytest -m engine "--engine-path=<temp copy of sf_19>"` gives 10 passed. `--fulldb-path=<dev puzzles.db>` collects 60 tests. `unit/test_fetch_stockfish_script.py` gives 3 passed. I agree a root conftest can't fix the space form |
| B2 (minor) 2-ply refutation | `_extend_refutation` asks again from the end of a short pv (≤ 2 more calls) | **FIXED** | `test_qa_refutation_is_at_least_3_plies_when_the_game_goes_on` passes (deterministic 2-ply engine). Real sf_19 `test_qa_refutations_are_3_to_5_plies_unless_the_game_ends`: 4/4 runs pass (round 1: 1 of 4 failed) |
| B3 (minor) stale refutation after Next | `puzzleSeq` counter in TrainerView | **FIXED** | `test_qa_refutation_error_after_next_is_not_shown_on_the_next_puzzle` passes (in the 129 e2e) |
| B5 (minor) close waits for the search | `close()` kills a busy engine; the search fails with `engine_stopped`; `EngineService.close` doesn't take the lock | **FIXED** | `test_qa_close_during_a_real_search`: `close()` during a 5 s real search took **0.00 s** (round 1: 4.5 s), and the pid is gone. Real app: exit in 4.0 s while a 5 s search ran. That's the same as an idle close (4.2 s above, mostly WebView2 teardown). **I agree** with the builder's edit of `test_qa_close_during_a_hung_search_returns_within_the_bound` (`engine_stopped`, < 1 s): a deliberate stop shouldn't restart or log an error. Round 2 also made that test wait until the process is up before closing. Under load it had failed with `engine_start_failed`, because closing during start-up is B8 |
| B6 (minor) banner ignores a custom engine | `Engine in use: …` logged after start-up; About shows "Your custom engine can't be found" | **FIXED** | Real-app log line 4: `Engine in use: Stockfish 19 (managed, sf_19) at C:\…\engines\sf_19\stockfish.exe`. QA now asserts this in `test_engine_flow_in_the_real_app`. Builder tests `test_engine_log_line_names_the_engine_in_use` (custom included) and `test_about_shows_a_missing_custom_engine` pass |
| B7 (minor) rejected value stays in the box | inputs remount after a refused save | **FIXED** | builder e2e `test_a_refused_setting_snaps_back` passes |

## New bug

### v0.4-B8 (major, low likelihood): closing while the engine is starting leaves it running; the process never exits
- **Steps:** finish a puzzle (the panel fires its first engine request, which starts Stockfish lazily), then close the window within ~0.35 s. The same window opens after a settings change that restarts the engine, a custom engine switch, or a reinstall.
- **Expected:** NFR-6. Nothing keeps running after `close()`, and the process exits.
- **Actual:** `StockfishEngine.close()` sets `_closed`, and finds `_engine is None` because `_start()` hasn't returned yet. So it returns at once. The bridge thread then finishes `_start()`, assigns `self._engine` (`_ensure` checks `_closed` only *before* starting) and runs the search. That leaves a live engine whose python-chess thread isn't a daemon. Python waits for it at exit and the process never ends, with the lock held, exactly like B1. The B1 workaround doesn't apply, because `_close` is never called on that engine.
- **Evidence:**
  - Scratch script with real sf_19, closing 0.0 / 0.02 / 0.05 / 0.1 / 0.2 s after the first `analyse`. Every time: `result [('e2e4',)] engine left True`, and the process was killed by `timeout 20` (rc 124). Measured start-up time: 0.34–0.36 s (Hash 16 and 256).
  - `tests/integration/test_qa_v04_engine.py::test_qa_process_exits_when_closed_while_the_engine_starts` (xfail strict, child Python, fake UCI engine). With `--runxfail`: `CLOSE_S 0.28 ERRORS [] LEFT False`.
- **Suggested direction (not applied):** after `_start()` in `_ensure`, if `_closed` is set, `_close()` the new engine and raise `engine_stopped`. Or make `close()` and the start agree under a small separate lock.
- **Related, harmless:** a request queued behind the killed search at shutdown fails with `RuntimeError: database is closed`, which the bridge logs as "bridge analyze_position crashed" after the window is gone. Nothing leaks, because the DB is closed before it can start an engine. It's only noise in the log.

## The `test_enter_after_mouse_clicks_is_next_in_the_real_app` failure: a test race, not a product bug
- **Where it fails:** the coordinator's run and QA round 1 both failed at `assert page.get_by_test_id("stat-failed").inner_text() == "1"` (`'0' == '1'`). That line runs right after waiting for "Puzzle 2 of".
- **Cause, in `TrainerView.load`:** `api.nextPuzzle()` returns, then `refreshStats()` *starts* another bridge call, and `setView(next)` renders at once. The header's "Puzzle 2" comes from the new view, but its "of N" comes from the **previous** `stats`, which already had `queue_size`. So the header matches while the session bar still shows the old Failed count for one bridge round trip. The skip *is* recorded (inside `next_puzzle`), and the bar updates a few ms later. The test read it once instead of waiting.
- **Product impact:** none beyond a one-round-trip lag of the counters, which predates v0.4. The opponent's first-move animation isn't involved: Enter is handled before the next puzzle loads.
- **Fix (test only, QA's own v0.2 file):** both reads now wait (`wait_for_function` on `stat-failed`, 10 s). It then passed 5/5 alone and in the full smoke run.

## Round 2 evidence: commands run

| Command | Result |
|---|---|
| `uv run pytest` | **717 passed, 1 xfailed** (B8), 240 deselected. Summary at 168 s, and the process **exited on its own** at 169 s. (An earlier round-2 run before QA's test edit: 716 passed, 1 failed, the start-up race above, also exited by itself) |
| `uv run pytest -m e2e` | **129 passed** (337 s) |
| `uv run pytest -m engine` | **10 passed**; `--engine-path=PATH` 10 passed |
| `npm.cmd --prefix web run build`, `uv run pytest -m smoke` | **21 passed, 1 skipped** (the opt-in download test) in 208 s, including the new real-app timeout test |
| `uv run pytest -m fulldb` | **59 passed, 1 xfailed** (known v0.2-B2), 496 s, nothing running in parallel |
| `uv run ruff check .` / `ruff format --check .` | clean / 204 files formatted |
| `uv run mypy src` | no issues in 67 source files |
| `npm.cmd --prefix web run typecheck` / `lint` | clean / clean |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings [v0.4] |
| `uv run pytest -m docs_screenshots` | 15 passed, `docs/img` byte-identical |
| `uv lock --check` | up to date. The fix commit changes no dependency, lockfile or migration |

**Scope, architecture and security:**
- The fix touches `adapters/stockfish.py`, `app.py` (log line), `services/engine.py`, `services/session.py`, four front-end files, the Developer Guide and ARCHITECTURE §7 (new entry for B1/B2/B5/B6, including the python-chess workaround and when to remove it).
- No new dependency and no browser storage.
- `_extend_refutation` reuses `EngineService.analyse`, so every position is still validated, and pv prefixes are still kept legal.

## Tests added or changed in round 2 (all under `tests/`)
- New: `tests/smoke/test_qa_v04_r2_timeout_real_app.py::test_app_exits_after_an_engine_timeout`. It's the real-app regression test for B1 and skips if `csc.exe` is missing.
- New: `tests/integration/test_qa_v04_engine.py::test_qa_process_exits_when_closed_while_the_engine_starts` (xfail strict, B8).
- Changed: `test_qa_close_during_a_hung_search_returns_within_the_bound` now waits for the engine to be up before closing. The `_run_child` helper got `mode` / `timeout_s` / `wait_for_start` parameters.
- Changed: `tests/smoke/test_qa_v04_real_app.py` now asserts the B6 `Engine in use:` line.
- Changed: `tests/smoke/test_qa_v02_real_app.py::test_enter_after_mouse_clicks_is_next_in_the_real_app` now waits for the session bar instead of reading it once.

## For Adam's manual test (round-1 list still applies)
After the B8 fix, finish a puzzle and close the window **immediately**, a few times. `python.exe` should disappear from Task Manager, and the app should start again normally.

---

# Round 3, 2026-11-02 (re-verification)

Branch `v0.4` at `c9255f8`. The only product change is `src/weaksquare/adapters/stockfish.py`. Same rules as before: no product code changed by QA, no `-m live`, no credentials, no Lichess calls. `%LOCALAPPDATA%\WeakSquare` still doesn't exist.

## Verdict: **PASS WITH ISSUES** (no open bugs; one unnumbered log-noise note)

B8 is fixed. Nothing it could affect regressed: start-up, timeout/restart, close during a search, crash recovery and the real-app exit. Every suite is green. All eight numbered bugs (B1–B8) are closed. The remaining "issue" is the shutdown log noise below, which I don't number.

## B8 re-verification

| Check | Result |
|---|---|
| `test_qa_process_exits_when_closed_while_the_engine_starts` (now a plain test) | **passes 10/10**, together with `test_qa_process_exits_after_an_engine_timeout`, `test_qa_close_during_a_hung_search_returns_within_the_bound` and the adapter's close test (`-k "exits or close_during"`, 4 passed × 10) |
| Real sf_19: close 0, 0.05, 0.15, 0.25, 0.33, 0.36, 0.40, 0.42, 0.45, 0.5, 0.6, 0.8 s after the first `analyse`, each in a fresh process (QA's scratch `startrace.py`, the same script that reproduced B8 in round 2) | every run gives `engine_stopped`, `engine left False`, **rc 0** (process exited, 1.2–1.7 s total), no traceback. At 1.0 s the search had finished (`e2e4`), with clean exit. No `stockfish.exe` left afterwards |
| The restart path: fake hung engine (`TIMEOUT_S` 1 s, think 0.3 s), close at 1.0–2.0 s, around the timeout and the one restart | every run has **rc 0** and `engine left False`. Before the timeout: `engine_stopped`. After it: `engine_timeout`, and the restart either isn't started (`_restart_after` returns when closed) or `_adopt` stops it. No leftover `uci_engine.py` processes. stderr still shows python-chess's own `InvalidStateError` traceback on the timeout path; that's the known upstream bug the B1 workaround covers, and it's harmless |
| `CancelledError` handling | `test_stockfish_adapter.py::test_a_cancelled_search_is_handled` passes. After close it's the quiet `engine_stopped`; otherwise it's `engine_crashed` with one restart, never an unhandled exception |
| Code review of `_adopt` / `close()` ordering | `close()` sets `_closed` before swapping out `_engine`. `_adopt` checks `_closed` before storing and again after. Every interleaving ends with exactly one side stopping the process. A double `_close` is harmless: python-chess guards `close()` with `_shutdown`, and `_release_thread` only resolves a pending future |
| Real app | `smoke/test_qa_v04_r2_timeout_real_app.py` (B1, real timeout → exit, lock released) and `test_engine_flow_in_the_real_app` (close mid-search, no engine left, clean log with `Engine in use:`) both pass in the smoke run |

## Round 3 evidence: commands run

| Command | Result |
|---|---|
| `uv run pytest` | **719 passed**, 240 deselected. Summary at 136 s, **exited on its own** at 138 s |
| `uv run pytest -m engine` | **10 passed** |
| `npm.cmd --prefix web run build`, `uv run pytest -m smoke` | **21 passed, 1 skipped** (opt-in download test) in 183 s. `test_enter_after_mouse_clicks_is_next_in_the_real_app` passed |
| `uv run pytest -m e2e` | **129 passed** (front end unchanged since round 2) |
| `uv run pytest -m fulldb` | **59 passed, 1 xfailed** (known v0.2-B2) |
| `uv run ruff check .` / `ruff format --check .` / `uv run mypy src` | clean / 204 formatted / no issues in 67 files |
| `npm.cmd --prefix web run typecheck` / `lint` | clean / clean |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings [v0.4] |
| `uv lock --check` | up to date. No dependency, lockfile, migration, docs or front-end change in this commit, apart from the ARCHITECTURE §7 entry, which now covers B8 |

## The shutdown "database is closed" log noise (unnumbered note)
- **When:** a bridge request queued behind the search that `close()` kills fails with `RuntimeError: database is closed`. The bridge logs it as `bridge analyze_position crashed` with a traceback at ERROR level, after the window is gone.
- **Impact:** nothing leaks, nothing is user-visible, and it needs a close mid-search with a second request queued.
- **Why it isn't a numbered bug:** it breaks no requirement. It's still worth a small tidy-up later, because a spurious ERROR traceback in `weaksquare.log` could mislead someone reading a bug report. For example, `EngineService.analyse` could answer `engine_stopped` once the service is closed, instead of reaching the closed DB.

## Tests in round 3
QA added no new tests. The builder's B8 and `CancelledError` regression tests, and QA's round-2 tests, are committed in `c9255f8`.

## For Adam's manual test (the round-1 list, plus round 2's)
- Finish a puzzle and close the window **immediately**, a few times. `python.exe` should disappear from Task Manager, and the app should start again normally.
