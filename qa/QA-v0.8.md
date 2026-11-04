# QA report: v0.8 (Game library + Game Review, engine)

Branch `v0.8` at `b3eaa36`. Run on 2026-11-04 by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `docs/img/stats-reasons.png` changed when I regenerated the screenshots. The two versions look the same (the difference is in the chart's pixels), so I restored the committed file.

## Verdict: **FAIL** (1 major, 8 minor, no blocker)

All seven *Done when* items pass with evidence, and so do the four planning decisions Adam made. The automated suites are green. The checkpoint gate fails on one **major** bug:
- **B4 (major):** once you pick My puzzles, Name the idea and Danger spotting can't start. The source control shows "Lichess DB" and is locked, but the session still uses My puzzles. The error then tells you to "Choose Lichess DB", which you can't do from that control.

Fixing B4 and re-verifying should give PASS WITH ISSUES. The minor bugs:
- **B1:** changed grading thresholds never reach games that are already analyzed.
- **B2:** puzzle-file entries past the 20,000 cap are dropped without a word.
- **B3:** without Stockfish, a Retry move the app couldn't check is stored and counted as a miss.
- **B5:** the chess.com username you type for a URL import is used once, then forgotten, so the app still asks your color.
- **B6:** after one of My puzzles, the result panel shows Lichess-only details. **Open this puzzle on Lichess** goes to `lichess.org/training/<your puzzle's id>`, *Themes:* is empty, and Rated says the puzzle counts toward your rating.
- **B7:** long engine lines from the real Stockfish are cut off in Review's *Engine lines here*.
- **B8:** without Stockfish, a game puzzle is checked strictly, but the app shows no note saying so.
- **B9:** the User Guide's wording on decided positions overstates the rule.

---

## Evidence: commands run

Commands run in Git Bash unless noted. The PowerShell rows ran under `powershell.exe` with execution policy **AllSigned**.

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder tests: **1473 passed, 1 skipped**, 388 deselected (244 s). With the QA tests: see the last row |
| `uv run pytest -m e2e` | **229 passed** (600 s). QA `test_qa_v08_ui.py`: 4 passed, 2 xfailed (B4, B6) |
| `npm.cmd --prefix web run build` (PowerShell), then `uv run pytest -m smoke` | build rc 0. **29 passed, 1 failed, 1 skipped** (398 s). Builder `test_real_app_v08.py`: passed. QA `test_qa_v08_real_app.py`: passed. The failure was the older `test_qa_v04_real_app.py::test_engine_flow_in_the_real_app`, which found an `ERROR` from pywebview's `evaluate_js` in the log. That test closes the window while a 5 s search is running. Re-run alone 4 times: failed 1, passed 3. It's a shutdown-timing flake in a v0.4 test that touches no v0.8 code path (see Observations) |
| `uv run pytest -m engine` | **14 passed** (44 s). QA `tests/engine/test_qa_v08_real.py`: 1 passed (8 s) |
| `uv run pytest -m fulldb` (dev `puzzles.db`) | **71 passed, 3 xfailed** (the earlier QA xfails) in 538 s |
| `uv run pytest -m docs_screenshots` | **32 passed**. Only `stats-reasons.png` differed; it looks the same and was restored |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / already formatted (QA files included) |
| `uv run mypy src` | Success: no issues found in 102 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` (PowerShell) | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` (PowerShell) | gitleaks Passed; keyring-only Passed; rc 0 |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.8]`, both, rc 0 |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete" |
| `uv run python -m weaksquare --dev` (after the build) | Window up. Dev `user.db` migrated 6 → 7 (`Applied migration 0007_games.sql`), with a backup in `user-6-20261104-063238.db`. The app was closed by its own PID with WM_CLOSE: rc 0, "Shutting down", 0 ERROR lines. **Side effect:** your dev folder is signed in, so *sync on open* ran and fetched **1 Lichess game** into the dev `user.db` (`account_sync` lichess row). That's correct app behavior (FR-11.27) |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` | Vite 200. App rc 0 twice. The first run logged one CRITICAL: a bridge reply came back after Vite reloaded the page (`optimized dependencies changed. reloading` for `recharts`, the first time it was used). The second run was clean. This affects dev tooling only |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, Vite "mock" ready |
| `set_test_token.py`, `uv run pytest -m live` (incl. `tests/live/test_games_live.py`), `fetch_puzzle_db.py --dev`, `record_db_update.py` | **Not run.** The first two are for Adam only (credentials). The other two would replace the dev DB or call Lichess, and they're unchanged since v0.4. I reviewed the code of `tests/live/test_games_live.py` instead |
| Final re-run, QA tests included: `uv run pytest` + `uv run pytest -m e2e tests/e2e/test_qa_v08_ui.py` | **1501 passed, 1 skipped, 4 xfailed** / **4 passed, 2 xfailed** (addendum) |

No human-facing command uses a `.ps1` script, bare `npm` / `npx`, or venv activation.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **Done when: PGN edge cases** (multi-game file, bad PGN, variants rejected) | unit | PASS | `test_a_multi_game_file_gives_every_game_in_order`, `test_a_bad_game_in_a_file_is_reported_and_the_others_still_load`, `test_variants_are_rejected`, `test_bad_pgns_give_a_clear_reason`. QA: `test_qa_every_variant_header_is_refused_with_a_reason` (Chess960, Crazyhouse, Atomic, KotH), `test_qa_a_game_of_exactly_400_plies_is_accepted_and_401_is_refused`, `test_qa_null_moves_headers_only_and_crlf_bom_pastes`, `test_qa_an_illegal_from_position_start_is_refused`, `test_qa_a_from_position_game_with_black_to_move_starts_with_blacks_move`; e2e `test_import_errors_are_clear`, `test_a_multi_game_file_lets_you_pick` |
| **Done when: chess.com optional fields** | unit | PASS | `test_every_optional_field_may_be_missing`, `test_malformed_optional_fields_become_none_not_errors`, `test_the_time_class_is_derived_when_missing_including_daily`, `test_variants_are_skipped`. QA: `test_qa_chesscom_names_and_time_class_fall_back_to_the_pgn`, `test_qa_chesscom_rules_chess960_and_other_variants_are_skipped` |
| **Done when: serial rule in the chess.com client** | integration | PASS | `test_requests_are_strictly_one_at_a_time_across_threads` (real `ChesscomGames` with its lock), `test_chesscom_url_import_searches_the_archives_one_request_at_a_time` (the fake fails on overlap). One `ChesscomGames` instance is wired in `app.py`, so the lock covers sync, Verify and URL import together |
| **Done when: analysis reused on re-import** | integration | PASS | `test_reimport_reuses_the_stored_game_and_its_analysis`, `test_a_synced_game_reimported_by_url_or_paste_is_the_same_game`, `test_the_same_settings_are_never_analyzed_twice` |
| **Done when: refutation prompt during a game analysis** | integration | PASS | `test_a_puzzle_refutation_is_prompt_while_a_game_is_analyzed` (the background engine is held on a gate). The separate `_bg_lock` and process are in `services/engine.py` |
| **Done when: anonymized fixtures (SR-12a)** | contract + manual | PASS | `test_anonymized`, `test_v08_checkers_catch_real_chesscom_urls_names_and_pgn_tags`, `test_recorded_game_fixtures_parse`. I read every file in `fixtures/http/chesscom` and `lichess_games`: only `player_*` / `opponent_*`, `GAMEID…`, `1000000…` and zero UUIDs. `mockGames.ts` uses only placeholder names |
| **Done when: puzzle-file import** (each format, bad entries, re-import, mate-in-1) | unit + integration + e2e | PASS (B2) | `test_each_format_imports_with_a_report`, `test_reimporting_the_same_file_adds_nothing_but_another_label_is_another_set`, `test_imported_puzzles_are_strict_but_any_mate_counts`, `test_the_mate_in_one_position_with_two_mates_imports_with_the_files_answer`, `test_cancel_leaves_nothing_behind`. QA: `test_qa_a_black_to_move_pgn_puzzle_is_solved_by_black`, `test_qa_csv_quotes_and_move_numbers_in_the_solution`, `test_qa_an_epd_with_an_illegal_bm_is_reported_not_imported`. Entries past the cap aren't reported: B2 |
| Decision 1: every game analyzed locally, Lichess badge and accuracy | integration + e2e | PASS | `test_first_sync_pulls_both_platforms_metadata_and_pgns_only`, `test_lichess_game_json_with_everything`; e2e `test_my_games_lists_both_platforms_and_filters` ("lichess analysis" badge); screenshot `qa-v08-my-games.png` |
| Decision 2: Missed / Allowed / Other, no themes | unit + schema | PASS | `test_missed_allowed_other`; `themes` stays NULL (`0007_games.sql`, `save_as_puzzle`). No tagger in `src/` (grep) |
| Decision 3: game puzzles use the 30 cp tolerance on the engine; imports are strict | integration + engine | PASS (B8) | `test_a_saved_game_puzzle_accepts_a_move_within_the_tolerance` (interactive engine only), `test_the_engine_continues_the_line_from_your_move`, `test_a_move_outside_the_tolerance_is_wrong`; QA `test_qa_a_tolerance_puzzle_accepts_any_mate_and_ends_there`, real engine `test_qa_real_engine_stalemate_blunder_retry_and_saved_puzzle`, real-app smoke (an off-line move graded) |
| Decision 4: the source is named "My puzzles" | e2e | PASS (B4, B6) | `test_my_puzzles_source_serves_your_own_puzzle`; screenshots `qa-v08-mixer-my-puzzles.png`, `qa-v08-mixer-both.png` |
| Builder defaults: 0.3 s, MultiPV 3, background threads = threads − 1 | integration | PASS | `test_a_game_is_graded_ply_by_ply_on_the_background_engine` (`{(0.3, 3)}`, 6 threads for 7) |
| Builder defaults: thresholds 50/100/200, ±500 decided, clamp ±1000 | unit | PASS (B1, B9) | `test_thresholds_at_each_boundary`, `test_decided_positions_are_not_penalized`, `test_leaving_the_decided_zone_is_penalized`; QA `test_qa_stalemating_a_won_position_is_a_blunder_and_the_final_eval_is_level` |
| Builder defaults: first sync of 90 days / 200 games, sync on open, URL search of 6 months | integration + e2e | PASS | `test_first_sync_respects_the_game_count_limit`, `test_first_sync_window_skips_older_chesscom_games`, `test_chesscom_url_import_searches…`; QA `test_qa_chesscom_months_on_the_first_sync_start_at_the_window_month`; QA e2e `test_qa_user_guide_settings_games_labels_and_defaults` (90, 200, 0.3, 5, 30, 50, 100, 200; sync on) |
| Builder defaults: limits (10 MB / 500 games, 20 MB / 20,000 entries, 400 plies) | unit + integration | PASS (B2) | `test_bad_files_and_labels`; QA 400/401 plies, `test_qa_a_400_ply_game_imports_and_analyzes_completely` |
| Builder defaults: modes for My puzzles; source locked in Name the idea and Danger spotting | integration + e2e | **FAIL (B4)** | `test_name_the_idea_and_danger_spotting_stay_lichess_only` (backend); QA e2e `test_qa_a_lichess_only_mode_after_choosing_my_puzzles_can_start` (xfail) |
| Builder defaults: `my:` attempts always stored `local` | integration + smoke | PASS | `test_a_my_puzzle_starts_from_its_own_position_and_never_syncs`; QA `test_qa_my_puzzles_never_reach_the_lichess_sync_queue`; QA smoke DB check (`my`, `local`, NULL rating) |
| Builder defaults: Commit the line grades game puzzles against the stored line | integration | PASS | `test_commit_the_line_grades_my_puzzles_against_the_stored_line` |
| FR-11.1, 11.2 Import game button; paste / file / Lichess URL / chess.com URL | integration + e2e + smoke | PASS (B5) | `test_game_and_puzzle_files_through_the_open_dialog`, `test_chesscom_link_sync_and_url_import`, `test_lichess_single_game_export_is_json_and_works_without_a_token`; e2e import tests; smoke (builder and QA) |
| FR-11.3 Lichess URL with `/white`, `/black`, `#ply`, the 12-char player URL | unit | PASS | `test_lichess_urls`; QA `test_qa_lichess_urls_with_a_player_suffix_and_ply_anchor` |
| FR-11.4 chess.com URL: archives, serial, ask once, paste the PGN if not found | integration + e2e | PASS (B5) | `test_a_chesscom_game_that_isnt_found_asks_for_the_pgn`, `test_a_chesscom_url_asks_for_your_username_once` (mock). The typed name isn't kept: B5 |
| FR-11.5 color detection, ask, review both sides | integration + e2e | PASS (B5) | `test_an_unknown_color_asks_and_can_be_set`, `test_import_a_pasted_game_asks_your_color`; QA `test_qa_review_both_sides_lists_moments_and_retries_for_each_color` |
| FR-11.6 python-chess validation, standard chess only | unit | PASS | see the PGN edge-case row |
| FR-11.7 stored with its source; dedupe reuses the analysis | integration + migration | PASS | `test_a_platform_game_is_stored_once_but_pastes_without_an_id_are_not_constrained` and the re-import tests |
| FR-11.8 every position, background, progress, cancel | integration + e2e + smoke | PASS | `test_cancel_stops_the_queue_and_keeps_nothing_partial`, `test_analyze_selected_runs_in_the_background`; QA stalemate and 400-ply analyses |
| FR-11.9 per-move record, classification, mate swing, decided positions | unit + engine | PASS (B1) | `test_mate_swings_are_blunders`, `test_grade_game_scores_every_move…`, `test_the_scholars_mate_blunder_is_found_and_refuted`; QA real-engine stalemate (mate in 3 thrown into stalemate = blunder) |
| FR-11.10 Missed / Allowed classification, themes from v0.10 | unit | PASS | `test_missed_allowed_other` |
| FR-11.11 per-side summary (counts, avg loss, accuracy, phase, low clock) | unit + e2e | PASS | `test_side_summary_counts_phases_and_low_clock_errors`, `test_phase_from_lichess_division_and_from_the_rule`; screenshot `qa-v08-review.png` |
| FR-11.12 symbols, clickable moves, eval graph | e2e + smoke | PASS | `test_review_shows_graph_moments_lines_and_refutation`; `qa-v08-real-review.png` |
| FR-11.13 key moments (top 5, *Played X, better was Y*, reason chips) | unit + e2e | PASS | `test_key_moments_are_the_largest_losses_in_game_order`, `test_reasons_and_save_as_puzzle_on_a_key_moment` |
| FR-11.14 best-move arrow, top lines, refutation step-through | e2e + smoke | PASS (B7) | `test_review_shows_graph_moments_lines_and_refutation`, builder smoke; long lines are clipped: B7 |
| FR-11.15 Retry: answer only after the try, tolerance, local stats | integration + e2e + engine + smoke | PASS (B3) | `test_retry_finds_moves_within_the_tolerance_from_the_stored_lines`, `test_retry_checks_other_moves_with_the_interactive_engine`, `test_retry_mode_checks_your_move_then_shows_the_answer`; QA real-engine retry and QA smoke (`retry-result` absent before the move) |
| FR-11.16 Save as puzzle, once, solved with the tolerance, never synced | integration + smoke | PASS | `test_save_as_puzzle_stores_your_position_and_the_best_line_once`; QA `test_qa_save_as_puzzle_for_black_is_served_with_black_to_move`; both smokes |
| FR-11.22 Game Review never syncs or changes a rating | integration + smoke | PASS | QA smoke: no attempt with `sync_status != 'local'`; `retry_attempts` only |
| FR-11.23 Lichess linked when signed in, exported with your token | integration | PASS | `test_lichess_user_games_sends_the_documented_flags_and_the_token`, `test_an_expired_lichess_token_is_reported` |
| FR-11.24 chess.com Verify (profile / 404), username in settings | integration + e2e | PASS | `test_verify_shows_the_profile_or_says_no_such_user`, `test_link_chesscom_with_verify` |
| FR-11.25 library columns and status badges | e2e | PASS | `test_my_games_lists_both_platforms_and_filters`; QA e2e column check |
| FR-11.26 library filters | integration + e2e | PASS | `test_library_filters`, `test_library_list_filters_and_settings` |
| FR-11.27 sync: on open, Refresh, incremental, ETags, first-sync window, metadata only | integration | PASS | `test_sync_is_incremental_and_a_second_run_adds_nothing`, `test_a_new_game_in_the_current_month_arrives_on_the_next_sync`, `test_an_unchanged_month_is_a_304_using_the_etag`, `test_changing_the_chesscom_username_forgets_the_old_sync_position`; QA `test_qa_relinking_another_chesscom_user_starts_a_fresh_first_sync` |
| FR-11.28 chess.com data handling | unit | PASS | see the optional-fields row |
| FR-11.29 Review / Open on Lichess or chess.com (the AI action is v0.9) | integration + e2e | PASS | `test_chesscom_link_sync_and_url_import` (`open_game_online`), the e2e row actions |
| FR-11.30 Analyze selected only (Send to Coach is v0.10) | e2e | PASS | `test_analyze_selected_runs_in_the_background` |
| FR-11.31 one job at a time, cancel, never twice at the same settings | integration | PASS (B1) | `test_games_queue_in_order_one_job_at_a_time`, `test_the_same_settings_are_never_analyzed_twice` |
| FR-11.32 documented APIs only | integration | PASS | `test_only_the_published_data_api_is_called` (refuses `callback` URLs) |
| FR-11.33 / FR-10.50 privacy | docs + code review | PASS | User Guide "Your data and privacy" (Your games, Importing your own puzzles); puzzle files are read in `services/puzzle_import.py` and never go to `http` |
| chess.com 410 / 429 at sync level | QA integration | PASS | `test_410_is_permanent`, `test_429_waits_and_tries_again_then_gives_up`; QA `test_qa_a_gone_month_is_skipped_now_and_never_asked_for_again`, `test_qa_chesscom_rate_limited_to_the_end_still_syncs_lichess` |
| FR-3.15 My puzzles source, its filters, Both in proportion | integration + e2e | PASS (B4, B6) | `test_my_puzzles_filters_by_origin_and_set`, `test_both_mixes_lichess_and_my_puzzles`, `test_history_filters_apply_to_my_puzzles`, `test_v08_puzzle_source_and_my_puzzles_filters` (an old preset loads as Lichess DB) |
| FR-10.43 tolerance rule with continuation | integration | PASS (B8) | see decision 3 |
| FR-10.46–10.49 puzzle files | unit + integration + e2e | PASS (B2) | see the Done-when row; QA e2e `test_qa_user_guide_import_puzzles_steps` |
| FR-5.7 reasons on game mistakes and Retry misses | integration + e2e | PASS (B3) | `test_reasons_on_your_game_mistakes_and_retry_misses` |
| FR-5.8 *Game Review only* | integration + e2e | PASS | `test_game_review_only_asks_in_game_review_not_after_puzzles`; QA e2e (the option appears) |
| FR-5.9 game suggestions (rushed on a low clock, missedResource) | integration | PASS | `test_the_review_shows_symbols…` (`missedResource`), the `core/reasons.py` rules |
| FR-9.7 reason breakdown by source; Retry found N of M | integration + e2e | PASS (B3) | `test_paste_analyze_review_retry_save_and_reason` (`get_reason_stats(…, "games")`), `test_stats_show_retry_and_reasons_from_games` |
| SRS with `my:` puzzles; key survives a DB change | integration | PASS | `test_my_puzzles_come_back_in_spaced_repetition`, `test_my_puzzle_keys_survive_a_puzzle_db_change` |
| Schema `user/0007_games.sql` | migration test | PASS | `test_v6_database_gains_empty_game_tables_and_keeps_its_data`, `test_custom_puzzles_are_unique_per_game_ply_and_per_imported_set_entry`; real dev DB migrated 6 → 7 with a backup |

---

## Bugs

### v0.8-B4 (major): a Lichess-only mode after choosing My puzzles can't start
- **Steps:** Choose your puzzles → **Puzzles from: My puzzles**. Then **Mode: Danger spotting** (or Name the idea first) → **Start**.
- **Expected:** the source control, now locked to "Lichess DB" with its tooltip, means what it shows, and the session runs on Lichess puzzles. Or the app switches the source back for you.
- **Actual:** the control shows "Lichess DB" (disabled), but `spec.source` is still `my`. The My puzzles filter group stays visible, the Lichess filters stay greyed out, and the count reads "1 puzzle matches". Start fails with *"My puzzles works in Standard, Commit the line and Spaced repetition. Choose Lichess DB for this mode."*, and you can't choose Lichess DB from the locked control. The way out is to switch to Standard, pick Lichess DB, then switch back.
- **Cause:** `SourceSelect` displays `value={locked ? "lichess" : spec.source}` but never changes the spec. `App.start` sends the spec unchanged.
- **Evidence:** `tests/e2e/test_qa_v08_ui.py::test_qa_a_lichess_only_mode_after_choosing_my_puzzles_can_start` (xfail strict); screenshots `tests/e2e/artifacts/qa-v08-locked-source.png` and `qa-v08-locked-source-start.png`.

### v0.8-B1 (minor): new grading thresholds never reach games already analyzed
- **Steps:** analyze a game. Settings → Games → change **Inaccuracy / Mistake / Blunder from (cp)**. Open the game's review.
- **Expected:** the review is graded with the new thresholds (the stored evals are enough to regrade it), or it shows **Analyze again**.
- **Actual:** the stored classifications, key moments and Retry list stay as they were. `current` stays true, because `is_current` compares only the think time and the engine, so **Analyze again** never appears. The Developer Guide says "to re-analyze a game, use **Analyze again** or change `review.think_s`", but Analyze again appears only after a think-time or engine change.
- **Evidence:** `tests/integration/test_qa_v08_edges.py::test_qa_changed_thresholds_regrade_or_offer_analyze_again` (xfail strict: still "good", `current` True).

### v0.8-B2 (minor): puzzle-file entries past the cap are dropped without a word
- **Steps:** import an EPD, CSV or PGN puzzle file with more than 20,000 entries.
- **Expected:** the report says the file had more entries than the app takes (FR-10.48: the report accounts for what wasn't imported).
- **Actual:** `parse_epd` / `parse_csv` / `parse_pgn_puzzles` stop at `max_entries` and the rest vanishes. The report's `entries` is 20,000 and nothing mentions the rest. The same happens to the 501st game of a game file.
- **Evidence:** `tests/unit/test_qa_v08_core.py::test_qa_entries_past_the_cap_are_reported` (xfail strict; with a cap of 3, five lines give 3 entries and no error).

### v0.8-B3 (minor): without Stockfish, an unchecked Retry move counts as a miss
- **Steps:** don't install Stockfish. Review an analyzed game → **Retry your mistakes** → play a move that isn't one of the stored top 3.
- **Expected:** the move is reported as *not checked* and left out of "Retry: found N of M" (and the miss reason chips aren't offered for it).
- **Actual:** `retry_attempts` gets a row with `found = 0`, Stats counts it as tried and not found, and the result is a miss. The UI also says "Install Stockfish to have other moves checked." A possibly good move becomes a recorded miss.
- **Evidence:** `tests/integration/test_qa_v08_edges.py::test_qa_an_unchecked_retry_is_not_counted_as_a_miss` (xfail strict: `tried == 1`).

### v0.8-B5 (minor): the chess.com username typed for a URL import is used once, then forgotten
- **Steps:** with no linked chess.com username (and not signed in to Lichess), go to Import game → Game URL → a chess.com URL → type your username when asked → Import.
- **Expected:** FR-11.4 "ask once" and FR-11.5. The name you typed is remembered, or offered for linking, and it's used to detect your color.
- **Actual:** the game is found, but the app still asks *Which side did you play?*, because `_save` detects your color from the linked usernames only. The next chess.com URL asks for the username again.
- **Evidence:** `tests/integration/test_qa_v08_edges.py::test_qa_the_username_given_for_a_chesscom_url_finds_your_color_and_is_kept` (xfail strict: `needs_color=True`).

### v0.8-B6 (minor): My puzzles show Lichess-only details
- **Steps:** Puzzles from: My puzzles → Start → finish the puzzle.
- **Expected:** no Lichess link and no rating promise for your own puzzles (FR-3.15: they never sync and have no rating).
- **Actual:**
  - **Open this puzzle on Lichess** links to `https://lichess.org/training/<custom id>`, for example `/training/1`. That's a different or nonexistent Lichess puzzle. `bridge/api.py::_outcome` builds `puzzle_url` for every puzzle.
  - The result panel shows an empty **Themes:** line.
  - Before Start, the **Rated** switch is on and says "Solves count toward your Lichess puzzle rating."
- **Evidence:** `tests/e2e/test_qa_v08_ui.py::test_qa_a_my_puzzle_has_no_lichess_link_and_no_rated_promise` (xfail strict: the href is `https://lichess.org/training/1`); real-app screenshot `tests/e2e/artifacts/qa-v08-real-my-puzzle-outcome.png`.

### v0.8-B7 (minor): long engine lines are cut off in Review
- **Steps:** analyze a game with the real Stockfish, open the review, and look at **Engine lines here**.
- **Expected:** the lines wrap, or are shortened with an ellipsis, as in the puzzle engine panel, which caps the PV.
- **Actual:** the background engine's whole PV is stored and shown with `wrap="nowrap"`, so lines of 15 to 20 moves run off the panel and stop mid-move ("…Nxc6 Nx"). The mock's lines are short, so the docs screenshots don't show this.
- **Evidence:** `tests/e2e/artifacts/qa-v08-real-review.png` (QA smoke).

### v0.8-B8 (minor): no note when a game puzzle falls back to strict checking
- **Steps:** without Stockfish, drill a puzzle saved from a game and play a good move that isn't the saved one.
- **Expected (plan v0.8 defaults):** "Without Stockfish, game puzzles fall back to strict checking on the stored line, **with a note**."
- **Actual:** the move is simply *wrong*. `PuzzleView` and `MoveResult` carry no flag for it, and `TrainerView` shows no note. The behavior itself is right (`test_without_stockfish_a_saved_puzzle_checks_its_stored_line`), and the User Guide documents it.
- **Evidence:** that test, plus code review of `services/session.py::_tolerate` and the `TrainerView.tsx` diff (no note added).

### v0.8-B9 (minor, docs): "already won or lost" overstates the decided-position rule
- **Where:** User Guide → Reading the review: "Positions that were already won or lost (beyond ±5) aren't penalized."
- **Actual rule:** a move isn't penalized only when the position is still beyond ±5 after it, or was already lost. Going from +8 to +1 is a blunder (`test_leaving_the_decided_zone_is_penalized`), so a reader who sees "??" on a move from a won position may think the app is wrong. Suggested wording: "…aren't penalized as long as they stay won (or were already lost)."

---

## Tests added (all pass, or xfail strict for an open bug)

- `tests/unit/test_qa_v08_core.py`:
  - **PGN:** `test_qa_a_game_of_exactly_400_plies_is_accepted_and_401_is_refused`, `test_qa_every_variant_header_is_refused_with_a_reason` (×4), `test_qa_a_from_position_game_with_black_to_move_starts_with_blacks_move`, `test_qa_an_illegal_from_position_start_is_refused`, `test_qa_null_moves_headers_only_and_crlf_bom_pastes`.
  - **URLs and Lichess games:** `test_qa_lichess_urls_with_a_player_suffix_and_ply_anchor`, `test_qa_lichess_from_position_games_are_accepted_but_chess960_is_skipped`.
  - **Grading:** `test_qa_stalemating_a_won_position_is_a_blunder_and_the_final_eval_is_level`, `test_qa_a_resigned_game_grades_every_move_including_the_last`.
  - **chess.com:** `test_qa_chesscom_rules_chess960_and_other_variants_are_skipped`, `test_qa_chesscom_names_and_time_class_fall_back_to_the_pgn`, `test_qa_chesscom_months_on_the_first_sync_start_at_the_window_month`.
  - **Tolerance:** `test_qa_tolerance_mates_and_bounds`.
  - **Puzzle files:** `test_qa_a_black_to_move_pgn_puzzle_is_solved_by_black`, `test_qa_csv_quotes_and_move_numbers_in_the_solution`, `test_qa_an_epd_with_an_illegal_bm_is_reported_not_imported`, `test_qa_entries_past_the_cap_are_reported` (xfail B2).
- `tests/integration/test_qa_v08_edges.py`:
  - **Analysis:** `test_qa_a_stalemated_game_is_analyzed_and_its_final_position_never_searched`, `test_qa_a_400_ply_game_imports_and_analyzes_completely`, `test_qa_changed_thresholds_regrade_or_offer_analyze_again` (xfail B1).
  - **Retry and Save:** `test_qa_an_unchecked_retry_is_not_counted_as_a_miss` (xfail B3), `test_qa_review_both_sides_lists_moments_and_retries_for_each_color`, `test_qa_save_as_puzzle_for_black_is_served_with_black_to_move`.
  - **My puzzles:** `test_qa_a_tolerance_puzzle_accepts_any_mate_and_ends_there`, `test_qa_my_puzzles_never_reach_the_lichess_sync_queue`.
  - **Sync:** `test_qa_a_gone_month_is_skipped_now_and_never_asked_for_again`, `test_qa_chesscom_rate_limited_to_the_end_still_syncs_lichess`, `test_qa_relinking_another_chesscom_user_starts_a_fresh_first_sync`.
  - **URL import:** `test_qa_the_username_given_for_a_chesscom_url_finds_your_color_and_is_kept` (xfail B5).
- `tests/e2e/test_qa_v08_ui.py`:
  - **User Guide walk-throughs:** `test_qa_user_guide_my_games_and_review_steps`, `test_qa_user_guide_settings_games_labels_and_defaults`, `test_qa_user_guide_import_puzzles_steps`.
  - **Source control:** `test_qa_my_puzzles_source_greys_lichess_filters_and_both_keeps_them`, `test_qa_a_lichess_only_mode_after_choosing_my_puzzles_can_start` (xfail B4).
  - **My puzzles results:** `test_qa_a_my_puzzle_has_no_lichess_link_and_no_rated_promise` (xfail B6).
- `tests/engine/test_qa_v08_real.py`: `test_qa_real_engine_stalemate_blunder_retry_and_saved_puzzle`.
- `tests/smoke/test_qa_v08_real_app.py`: `test_qa_v08_import_analyze_retry_save_and_drill_in_the_real_app`.

Screenshots (gitignored) are in `tests/e2e/artifacts/qa-v08-*.png`: my-games, review, retry, retry-result, settings-games, import-puzzles-dialog, import-report, mixer-my-puzzles, mixer-both, locked-source, locked-source-start and my-puzzle-outcome, plus real-app review, retry-result, my-puzzle-outcome and locked-source. I looked at all of them. Besides B4, B6 and B7 there's no layout breakage or clipped text.

---

## Scope, architecture and security findings

- **Later versions:** nothing from them was built. A grep finds no Explain this move or Explain my game, no AI-reviewed status, no Send to Coach, no tagger or habit tags, no `game_errors` and no severity setting or filter. `custom_puzzles.severity` and `solve_as` are §4.3 schema columns. The severity column is filled on save but nothing reads it, which is acceptable as schema.
- **`core/`:** no I/O. The only imports are python-chess, `hashlib`, `re`, `csv` and `io` on strings. `datetime` is used only to turn timestamps from the API into dates (`fromtimestamp`), never `now()`. No `time.time()`, `datetime.now()` or global `random` in `core/` or `services/`.
- **Wiring:** `services/` imports no adapters. Concrete adapters (`ChesscomGames`, `LichessGames`, `CombinedSource`, `CustomPuzzleSource`, the repos) are wired only in `app.py`. `keyring` appears only in `adapters/secret_store.py` (`app.py` mentions it in a docstring). Game HTTP goes through `adapters/http.py` (`get_json_cached`, `stream_ndjson`).
- **Engines:** Retry (`ReviewService.retry_move`) and the tolerance check (`SessionService._tolerate`) call `EngineService.analyse`, the interactive engine. The analysis queue calls `analyse_background`, a second process with its own lock. `test_a_saved_game_puzzle_accepts…` asserts that only the 7-thread interactive engine was used.
- **Threads, bridge, front end:** every repo opens its connection per call from `Database`. The bridge allowlist tests pass, and the new `Api` methods all use `@bridge_call`. `web/src` uses no browser storage (grep, plus the smoke `test_no_browser_storage_and_csp_active`). LLM text isn't involved in v0.8.
- **Migrations:** `0007_games.sql` is the only new migration. It was changed within v0.8 (the refutation column) before any release, and earlier migrations are untouched. **Dependencies:** none added. `pyproject.toml`, `package.json` and both lockfiles changed only the version to 0.8.0. `recharts` and `@mantine/charts` were already there.
- **Data:** tests use temp folders (the `services` and `rig` fixtures). Smoke and engine tests copy or read the *dev* folder's Stockfish read-only, never the default data folder.
- **Security:**
  - gitleaks passed. A grep for `lip_`, `sk-ant-` and `sk-` tokens finds only `FAKE` placeholders, plus compiled `__pycache__` files, which aren't tracked.
  - Fixtures and `mockGames.ts` are anonymized (`player_*` / `opponent_*` / `your_name`, `GAMEID…`, `1000000…`).
  - Tokens never reach DTOs or logs: `LichessGames` passes `token=` to `http.py`, which redacts it.
  - The CDP port is accepted only with `--dev` (`app.py` `DEBUG_PORT_ENV` check; `test_debug_port_refused_without_dev` passed).
- **Plan deviation, no bug:** the plan said `SAVED_FILTERS_VERSION` 3 → 4 with an upgrade step. It's still 3. That isn't needed, because every new field defaults to "no restriction", and `test_v08_puzzle_source_and_my_puzzles_filters` shows an old preset loads as Lichess DB.

### Observations (not filed as bugs)
- `parse_lichess_url` accepts Lichess site pages whose path is 8 characters long (`lichess.org/analysis`, `/training`, `/practice`, `/streamer`) as game IDs. The result is one request, a 404, and *"Lichess has no game with that URL."* Harmless.
- The puzzle import job reports only "Reading the file…" and "Saving…". Cancel takes effect only after parsing (it's atomic, so nothing is half-imported).
- The analysis queue lives in memory: after a restart, queued games show *Not analyzed* again. No requirement covers this.
- Grading notes from the real engine on Loyd's stalemate game: cp losses can reach about 2000, because both evals are clamped to ±1000. The key moments are then dominated by the mutual blunders, which is correct but makes the stalemate (1000) rank 6th.
- The v0.4 QA smoke flake (an `ERROR` from pywebview `evaluate_js` when the window closes during a running bridge call) recurs about 1 run in 3 on this machine. The builder may want to make that test tolerate this pywebview shutdown message.

---

## Docs findings

- `check_docs.py --strict`: `0 error(s), 0 warning(s) [version v0.8]`.
- **Developer Guide:** every command was run as written (table above), except the credential, live and download commands. They all work under AllSigned PowerShell. The v0.8 data notes match the code (tables, settings keys, `reasons.ask` `game_review`). The note "to re-analyze a game, use **Analyze again**" is only true after a think-time or engine change (B1).
- **User Guide, followed against the mock UI and the real app:**
  - *Your games and Game Review:* button and tab names, filters, columns, Settings → Games labels and defaults (90, 200, 0.3, 5, 30, 50, 100, 200), Retry flow and the *Game Review only* option all match. Wording issue: B9.
  - *Importing your own puzzles:* the menu item, label-first (Choose a file stays disabled until there's a label) and the report columns match.
  - *My puzzles:* the source names, filters, greyed Lichess-only controls, modes and no opponent move first all match. B4 contradicts "Name the idea and Danger spotting stay Lichess-only" in practice, and B6 contradicts "never sync to Lichess and have no rating" in the UI text.
  - The privacy section lists the game fetches (Lichess with your sign-in, chess.com public archives one at a time, URL import, Verify) and says puzzle files are never sent.
- **CHANGELOG `[Unreleased]`** covers every user-visible *Done when* item (game import edge cases, chess.com, analysis reuse, puzzle files with the report and mate-in-1), plus *Game Review only*. **README** status names v0.8 as in progress. **ARCHITECTURE** §2 and §7 have the v0.8 entries (schema, background engine, `my:` keys, the chess.com lock and ETags).

---

## For Adam's manual test (not verifiable automatically)

1. **Real accounts:** link your chess.com username (Verify shows your profile), sign in to Lichess, then **Refresh**. QA used fakes and hand-written fixtures only. Check that the first sync takes at most 90 days / 200 games per account and that a second Refresh adds nothing. My `--dev` run already synced 1 Lichess game from your dev sign-in.
2. **Live API shapes:** `uv run pytest -m live tests/live/test_games_live.py --chesscom-user=YOURNAME` (and `--record-games` if you want recorded fixtures). Review the anonymization in the diff.
3. **chess.com URL import** for one of your recent games. Note B5: you'll be asked your color unless you linked the username first.
4. **Review one Lichess and one chess.com game:** check that the *Lichess analysis* badge and platform accuracy appear, and that long engine lines are cut off (B7).
5. **Retry and Save 2 puzzles, then drill them** under My puzzles. Try a reasonable move that isn't the saved one: it should be accepted within 30 cp, and the engine should continue. Note B6 (the Lichess link) and B4 (switching to Danger spotting with My puzzles selected).
6. **Import a small PGN or EPD file of your own,** check the report, re-import it (0 added), and drill the set: strict checking, any mate counts.

---

## Addendum: final re-run with the QA tests

- `uv run pytest`: **1501 passed, 1 skipped, 4 xfailed** (B1, B2, B3, B5), 396 deselected, in 245 s, rc 0.
- `uv run pytest -m e2e tests/e2e/test_qa_v08_ui.py`: **4 passed, 2 xfailed** (B4, B6), rc 0.
- The QA smoke (`test_qa_v08_real_app.py`) and the QA engine test passed in the runs listed above.
- `uv run ruff check .` and `ruff format --check` are clean with the QA files.

---

# Round 2: re-verification of commit `4f08bd4` (2026-11-04)

## Verdict: **PASS WITH ISSUES** (3 new minor bugs, no blocker or major)

All nine round-1 bugs are fixed. Each one was checked by running a test, and B4, B6, B7, B8 and B9 also by looking at the UI or the docs. Every suite is green, with no flakes this round.

The re-test found three new **minor** bugs, all edge cases of the fixes:
- **B10:** thresholds changed while a game is being analyzed don't reach that game.
- **B11:** a mistyped chess.com username from a URL import is linked even when no game was found.
- **B12:** a CSV with exactly 20,000 entries and a trailing blank line is reported as having more than 20,000.

## Bugs re-tested

| Bug | Result | Evidence |
|---|---|---|
| B1 thresholds regrade | **Fixed** | `test_qa_changed_thresholds_regrade_or_offer_analyze_again` passes. New: `test_qa_r2_regrading_after_an_analysis_matches_the_new_thresholds` (every stored row equals `regrade(row, new)`). User Guide and Developer Guide updated to match. The concurrent case is still open: B10 |
| B2 cap reported | **Fixed** | `test_qa_entries_past_the_cap_are_reported`, `test_v08_b2_a_game_file_past_500_games_says_so`; new `test_qa_r2_a_csv_over_the_cap_says_so_once`. Edge case: B12 |
| B3 unchecked Retry | **Fixed** | `test_qa_an_unchecked_retry_is_not_counted_as_a_miss`. The UI shows a yellow "…couldn't be checked without Stockfish, so it isn't counted" and no reason chips (`ReviewView.tsx` diff) |
| B4 locked source | **Fixed** | `test_qa_a_lichess_only_mode_after_choosing_my_puzzles_can_start` passes. New `test_qa_r2_b4_the_source_follows_a_lichess_only_mode`: the My puzzles filters and the grey note disappear in Name the idea, and My puzzles can be picked again in Standard. Screenshot `qa-v08-r2-source-after-mode.png` |
| B5 typed chess.com name | **Fixed** | `test_qa_the_username_given_for_a_chesscom_url_finds_your_color_and_is_kept`. Side effect of the fix: B11 |
| B6 Lichess details on My puzzles | **Fixed** | `test_qa_a_my_puzzle_has_no_lichess_link_and_no_rated_promise`. Real-app screenshot `qa-v08-real-my-puzzle-outcome.png`: no link, no rating change, no empty Themes line, and Rated reads "Your own puzzles stay on this PC: they never count toward a rating." |
| B7 clipped lines | **Fixed** | `test_v08_b7_long_engine_lines_are_shortened`. Real-app screenshot `qa-v08-real-review.png` (real Stockfish): lines of 8 moves with "…", nothing cut off |
| B8 strict note | **Fixed** | `test_v08_b8_…`. New e2e `test_qa_r2_b8_a_saved_game_puzzle_without_stockfish_shows_the_strict_note` (Save a moment with `?engine=missing`, then drill it). Screenshot `qa-v08-r2-strict-note.png`: "Stockfish isn't installed, so only this puzzle's saved line counts." |
| B9 docs wording | **Fixed** | User Guide → Reading the review now says "isn't penalized when the game was already lost before it (−5 or worse), or is still won after it (+5 or better). Dropping from +8 to +1 still counts." That matches `_is_decided` (a move from a lost position can't lose cp in practice) |

## New bugs

### v0.8-B10 (minor): thresholds changed while a game is being analyzed don't reach that game
- **Steps:** analyze a game. While it's running, change Settings → Games → the thresholds.
- **Expected:** once the analysis finishes, that game is graded with the thresholds in force.
- **Actual:** `_analyze` reads the settings when it starts and writes the game at the end. The B1 regrade has already run on the stored rows by then, so this game keeps the old grades and stays *current*. It's stuck that way until the thresholds change again.
- **Evidence:** `tests/integration/test_qa_v08_round2.py::test_qa_r2_thresholds_changed_while_a_game_is_analyzed_reach_that_game` (xfail strict: index 0 is `'good'` but should be `'blunder'`).

### v0.8-B11 (minor): a mistyped chess.com username from a URL import stays linked
- **Steps:** with no linked chess.com username, go to Import game → a chess.com URL → type a wrong name → Import. The job fails.
- **Expected:** the name is linked only once it has found the game (or passed Verify).
- **Actual:** `start_url_import` links it before the search, and the link stays after the job fails. The next sync on open then fails with "Your linked chess.com username wasn't found". If the typo is someone else's real account, the sync pulls their public games into your library instead.
- **Evidence:** `test_qa_r2_a_username_whose_game_isnt_found_is_not_linked` (xfail strict: `chesscom_username == 'player_typo'`).

### v0.8-B12 (minor): a CSV at the cap with a trailing blank line says "more than 20,000"
- **Steps:** import a CSV with exactly 20,000 puzzles and a blank last line.
- **Expected:** no cap message.
- **Actual:** `parse_csv` counts blank rows before checking the cap, so the blank row trips it. The report then lists "the file has more than 20,000 entries: this one and the rest weren't read" and counts one skipped entry. EPD skips blank lines before counting, so it isn't affected.
- **Evidence:** `test_qa_r2_a_csv_at_the_cap_with_a_trailing_blank_line_is_not_over_the_cap` (xfail strict, with a cap of 2).

## Commands run (round 2)

| Command | Result |
|---|---|
| `uv run pytest` (before my round-2 tests) | **1507 passed, 1 skipped** (245 s) |
| `uv run pytest -m e2e` | **238 passed** (613 s) |
| `uv run pytest -m engine` | **15 passed** (52 s) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0. **30 passed, 1 skipped** (412 s). The v0.4 shutdown flake didn't recur. QA `test_qa_v08_real_app.py` passed |
| `uv run ruff check .`, `ruff format --check .`, `uv run mypy src` | clean / 326 files formatted / no issues in 102 files |
| `npm.cmd --prefix web run typecheck`, `npm.cmd --prefix web run lint` (PowerShell, AllSigned) | rc 0 / rc 0 |
| `python scripts/check_docs.py --strict` | 0 error(s), 0 warning(s) [version v0.8] |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged (`strict_without_engine` already in it) |
| Final: `uv run pytest` + `uv run pytest -m e2e tests/e2e/test_qa_v08_ui.py`, round-2 QA tests included | see the addendum below |

No `-m live`, no credentials. The fix commit touched no migration and added no dependency. It added one DTO field, `PuzzleView.strict_without_engine`, with `types.ts` regenerated.

## Tests added (round 2)
- `tests/integration/test_qa_v08_round2.py`:
  - `test_qa_r2_regrading_after_an_analysis_matches_the_new_thresholds`
  - `test_qa_r2_thresholds_changed_while_a_game_is_analyzed_reach_that_game` (xfail B10)
  - `test_qa_r2_a_username_whose_game_isnt_found_is_not_linked` (xfail B11)
  - `test_qa_r2_a_csv_at_the_cap_with_a_trailing_blank_line_is_not_over_the_cap` (xfail B12)
  - `test_qa_r2_a_csv_over_the_cap_says_so_once`
- `tests/e2e/test_qa_v08_ui.py`:
  - `test_qa_r2_b8_a_saved_game_puzzle_without_stockfish_shows_the_strict_note`
  - `test_qa_r2_b4_the_source_follows_a_lichess_only_mode`

## Round 2 addendum
- `uv run pytest`, round-2 QA tests included: **1509 passed, 1 skipped, 3 xfailed** (B10, B11, B12), 399 deselected, in 246 s, rc 0.
- `uv run pytest -m e2e tests/e2e/test_qa_v08_ui.py`: **9 passed**, rc 0.
- ruff check and ruff format are clean with the new files.

**For Adam's manual test:** the round-1 list still applies. B4 and B6 are fixed, so in step 5 try Danger spotting after choosing My puzzles: it should start on Lichess DB. In step 3, if you type your chess.com name in the Import dialog, type it carefully (B11).

---

# Round 3: re-verification of commit `bc09026` (2026-11-04)

## Final verdict: **PASS**

B10, B11 and B12 are fixed. No bug from any round is still open, and the re-test found no new ones. The fix commit changed only `core/puzzle_files.py`, `services/analysis.py`, `services/games.py` and ARCHITECTURE §7. It added no migration, dependency or DTO change.

| Bug | Result | Evidence |
|---|---|---|
| B10 thresholds changed mid-analysis | **Fixed** | `test_qa_r2_thresholds_changed_while_a_game_is_analyzed_reach_that_game` passes without its xfail marker. `_analyze` now regrades the finished game when the thresholds changed during the run |
| B11 mistyped chess.com name linked | **Fixed** | `test_qa_r2_a_username_whose_game_isnt_found_is_not_linked` passes: a failed search links nothing. New `test_qa_r3_a_found_game_links_the_typed_name_only_when_none_is_linked`: a found game still detects your color from the typed name, and an already-linked name is never replaced. B5's own test still passes |
| B12 CSV blank rows and the cap | **Fixed** | `test_qa_r2_a_csv_at_the_cap_with_a_trailing_blank_line_is_not_over_the_cap` passes. New `test_qa_r3_blank_rows_keep_their_row_numbers_and_dont_count`: blank rows don't count toward the cap, and reported entry numbers are still the file's row numbers |

**Residual, not filed:** B10 leaves a window of a few milliseconds. If the thresholds change after the job reads them back but before it stores the game, that game keeps the previous grades until the next threshold change. It's not practically reachable from the UI.

## Commands run (round 3)
| Command | Result |
|---|---|
| `uv run pytest` | **1512 passed, 1 skipped**, 399 deselected (250 s), rc 0 |
| `uv run pytest tests/integration/test_qa_v08_round2.py tests/integration/test_qa_v08_round3.py` | **7 passed** (the B10–B12 regression tests plus the round 3 tests) |
| `uv run pytest -m e2e` | **238 passed** (608 s), rc 0 |
| `uv run ruff check .` / `ruff format --check .` | clean |

No `-m live`, no credentials, and no product code changed.

## Tests added (round 3)
- `tests/integration/test_qa_v08_round3.py`:
  - `test_qa_r3_a_found_game_links_the_typed_name_only_when_none_is_linked`
  - `test_qa_r3_blank_rows_keep_their_row_numbers_and_dont_count`

**For Adam's manual test:** the round-1 list still applies, with no known open bugs.
