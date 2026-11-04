# QA report: v0.10 (the Coach)

Branch `v0.10` at `018a20a`. Run on 2026-11-04 by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `-m live` was **not** run (Adam's).

## Verdict: **PASS WITH ISSUES** (2 major, 6 minor; no blocker)

Every *Done when* item passes with evidence, including with the real Stockfish 19 in the real app: a Coach run on an imported game analyzes it at 0.3 s, makes a Missed puzzle from the missed mate with the right side and solution, applies the Suggested mix, and a level change runs no engine. Show best moves is off by default, hides every better move on the Review screen and survives a relaunch. The automated suites are green. The issues:
- **B1 (major):** another player's game mistakes count in *your* Stats → Why you missed (Games / All). The plan says they never count in your stats.
- **B3 (major):** if you leave the Coach page while a run is going (the User Guide says you can), the Mixer never picks up the applied Suggested mix. The label doesn't show, you train on the old filters, and the next filter change you make silently replaces the suggestion.
- **B2 (minor):** a blunder that allows mate from a position where you were ahead by 1.5+ is classed **Missed**, not **Allowed**, so no Allowed puzzle is made and the Coach reports it as a missed tactic.
- **B4 (minor):** with Show best moves off, Explain this move's step list still names the better move.
- **B5 (minor):** the Coach has no Lichess / chess.com / both choice for your own accounts (FR-10.3 "override them per run"; plan step 12).
- **B6 (minor):** small text issues: "1 games" in Saved reports, and the User Guide's "a mate in one is [kept]".
- **B7 (minor):** before the puzzle database is imported (a fresh install), every launch logs `bridge get_theme_catalog crashed` with a traceback, from a call the main page makes since v0.10.
- **B8 (minor, test only):** the builder's v0.9 smoke test fails every time now that there are three AI features.

---

## Evidence: commands run

Git Bash unless noted. PowerShell rows ran as `powershell.exe -NoProfile -ExecutionPolicy AllSigned -Command …`.

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder tests: **1699 passed, 1 skipped**, 449 deselected (285 s), rc 0. With the QA tests: see the last row |
| `uv run pytest -m engine` | **17 passed** (60 s). QA `tests/engine/test_qa_v010_real.py`: 1 passed, 1 xfailed (B2) |
| `uv run pytest -m e2e` | **275 passed** (677 s), rc 0. QA `test_qa_v010_ui.py`: **7 passed, 2 xfailed** (B3, B4) |
| `npm.cmd --prefix web run build` (PowerShell), then `uv run pytest -m smoke` | build rc 0; **33 passed, 1 skipped, 2 failed** (494 s). `test_real_app_v09.py::test_game_review_model_in_the_real_app` fails every time (B8, test only). `test_qa_v05_real_app.py::test_v05_modes_in_the_real_app` timed out once on the Commit-the-line move count and passed in 2 of 2 re-runs (flake, not v0.10). QA `test_qa_v010_real_app.py`: **2 passed** (also 2/2 on their own). Note: my first smoke run stopped at the harness's stale-build check, because `gen_types.py` rewrites `types.ts` (same content, new time); I rebuilt and re-ran |
| `uv run pytest -m fulldb` | dev `puzzles.db` is imported: **72 passed, 3 xfailed, 1 failed** (531 s). The failure is the known pre-existing `test_qa_v05_round3_ladder_worst_case.py::…[fork, promote 3->4]` (0.504 s against 0.5 s; also on `main`). QA `test_qa_v010_fulldb.py`: 2 passed |
| `uv run pytest -m docs_screenshots` | **37 passed** (117 s). `git status docs/` showed only `docs/img/stats-reasons.png` changed; I compared it with the committed file and they look identical (a pixel-level re-render, not a content change), and restored it |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 367 files already formatted |
| `uv run mypy src` | Success: no issues found in 119 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` (PowerShell AllSigned) | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` (PowerShell) | gitleaks Passed; keyring-only Passed; rc 0 |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.10]`, both rc 0 |
| `uv run python scripts/gen_types.py` | `types.ts` content unchanged (git status clean) |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, "VITE … mock ready" |
| `npm.cmd --prefix web run build` once, then `uv run python -m weaksquare --dev` | Run with `WEAKSQUARE_DATA_DIR` set to a fresh temp folder (Stockfish copied in), **not** the dev folder: the dev folder's `user.db` is still at v7, and this run would migrate it to 0008 and start the backfill there, which a v0.9 checkout then refuses (newer schema). Window up, closed with WM_CLOSE after 15 s: rc 0, "Shutting down", 0008 tables present. **1 ERROR** in the log: `bridge get_theme_catalog crashed` (B7) |
| `npm.cmd --prefix web run dev`, then `uv run python -m weaksquare --dev-server` | Vite 200; app rc 0, "Shutting down" (same temp folder setup). 2 ERROR lines, both B7 (React dev mode runs the effect twice) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (PowerShell, temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete"; `git status` clean afterwards |
| `set_test_token.py` (both rows), `uv run pytest -m live` (all three rows), `fetch_puzzle_db.py --dev`, `record_db_update.py` | **Not run.** The first are Adam's (credentials). The other two replace the dev DB or call Lichess and are unchanged since v0.4 |
| Final run with the QA tests: `uv run pytest` (after `ruff check .` and `ruff format --check .`, both clean) | **1713 passed, 1 skipped, 2 xfailed** (B1, B7), rc 0 (297 s) |

No human-facing command uses a `.ps1` script, bare `npm`/`npx`, or venv activation. The new Developer Guide text (vendored tagger update procedure) names only `uv run pytest …`.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **Done when: each habit tag has positive and negative tests** | unit | PASS | `tests/unit/test_habits.py`: hungPiece 2+/2−, missedFreeCapture 2+/2−, ignoredThreat 2+/3−, movedDefender 2+/2−, plus illegal move, quiet move, mate, and `test_every_habit_maps_to_drills` |
| **Done when: tagger output matches the puzzle DB's theme names** | unit + fulldb (QA) | PASS | `test_every_tag_is_a_puzzle_db_theme`, `test_tagger_keys_outside_the_catalog_are_the_known_internal_ones`. QA fulldb: `test_qa_every_key_the_tagger_can_keep_is_a_puzzle_db_theme` (every kept `TagKind` is in the full DB's `theme_bits`) and `test_qa_the_tagger_agrees_with_the_db_on_real_mate_puzzles` (≥ 100 real mate puzzles re-tagged: every tag is a DB theme, ≥ 97% agreement on mateIn1–3, mate and the length themes) |
| **Done when: the suggestion never overwrites manual filters** | integration | PASS | `test_filters_you_changed_are_never_overwritten`, `test_a_new_suggestion_replaces_the_last_one_you_applied`; QA `test_qa_filters_changed_after_an_applied_suggestion_are_never_overwritten` (a tweak saved through `ui_settings` after an applied suggestion), `test_qa_a_mode_change_alone_isnt_a_filter_change` (filters reset to the default broad mix are replaced again). Front-end gap when you leave the page: B3 |
| **Done when: quality check accepts / rejects known positions** | unit + engine | PASS | `tests/unit/test_puzzle_gen.py` (clean mate in one, unique best extends, several equal moves rejected, one-move advantage dropped, decided, up in material, no jump, mate line follows the defence, illegal engine output); engine `test_a_back_rank_mate_is_a_clean_puzzle`, `test_a_quiet_opening_position_is_not_a_puzzle`. QA real game: a missed back-rank mate is accepted (`test_qa_a_missed_mate_in_a_real_game_becomes_your_puzzle`); a missed mate where Bxf7+ also wins (+7.4) was rejected `no_forced_mate` (Lichess's mate-in-one rule, see Observations) |
| **Done when: each severity level's set; narrowing archives, keeps attempts** | integration | PASS | `test_levels_archive_and_restore_without_the_engine`, `test_widening_to_inaccuracies_checks_only_new_candidates`; QA `test_qa_each_level_gives_its_set_and_a_round_trip_runs_no_engine` (3 games with a blunder / mistake / inaccuracy: exact sets at each level across 6 changes, same row ids, no engine, no queue), `test_qa_narrowing_keeps_the_attempts_and_the_archived_puzzle_is_not_served` (a real attempt survives, the archived puzzle isn't served, widening restores it), `test_qa_a_puzzle_you_archived_stays_archived_across_level_changes` |
| **Done when: re-runs create no duplicates** | integration | PASS | `test_re_runs_make_no_duplicates`, `test_your_own_save_at_that_move_wins`; QA `test_qa_a_re_analysis_at_another_think_time_makes_no_duplicate`, `test_qa_two_coach_runs_and_the_backfill_make_no_duplicates` (2 games → 4 puzzles; a 2nd run with source Both + the backfill: still 4) |
| **Done when: Missed / Allowed side to move and orientation** | integration + engine + smoke | PASS | `test_missed_and_allowed_become_puzzles_with_the_right_side`, `test_an_allowed_puzzle_is_served_as_your_opponent_with_its_game_link`; QA engine (real Stockfish, whole pipeline): Missed at ply 14 → fen before your move, `d1d8`, white, solve as you, `mateIn1` tag, served as White; QA smoke: the same through the real app. Board orientation = `view.player_color` (`TrainerView.tsx`), label *Find what your opponent could have played*. Real Allowed case: B2 |
| **Done when: tolerance alternative accepted, engine continues** | integration | PASS | v0.8 `test_a_saved_game_puzzle_accepts_a_move_within_the_tolerance`, `test_the_engine_continues_the_line_from_your_move`; QA `test_qa_a_coach_allowed_puzzle_takes_a_move_within_tolerance_and_the_engine_continues` (origin `coach`, solve as opponent: `a1a3` instead of `e1e2` is *correct* with a reply, the line continues legally from it, the puzzle is solved, interactive engine only) |
| **Done when: a level change runs no game analysis** | integration + smoke | PASS | `test_a_level_change_runs_no_game_analysis` (queue never called); QA level round-trip (Recorder `.calls == []`); QA smoke: two level changes in the real app leave `coach_candidates` and the game's analysis untouched |
| **Done when: Analyze from here uses the interactive engine, changes nothing** | integration + smoke + e2e | PASS | `test_analyze_from_here_uses_the_interactive_engine_and_changes_nothing` (FakeEngine `options[0] == 7`, rows and status unchanged, bad FEN refused); QA smoke with real Stockfish: lines returned, analysis rows unchanged, "not a fen" refused; e2e `test_analyze_from_here_plays_any_line_and_goes_back`; QA `test_qa_analyze_from_here_screens` (back at 4.Nxe5 after **Back to the game**) |
| **Done when: Show best moves off hides best move / engine lines / better lines (Playwright), survives a relaunch** | e2e + smoke | PASS (B4) | `test_show_best_moves_off_hides_every_better_move`; QA e2e `test_qa_show_best_off_explain_this_move_hides_the_board_arrows`, `test_qa_show_best_off_explain_my_game_hides_better_lines`; QA smoke `test_qa_v010_show_best_moves_survives_a_relaunch` (off by default, no better / lines / "better was", turned on, app closed, `settings.review.show_best = true` in user.db, relaunched: still on). Explain this move's steps: B4 |
| FR-10.3 another player kept apart (My Games, mix, puzzles, trends, stats) | integration + e2e | PASS except stats (B1) | `test_another_players_run_is_kept_apart`, `test_another_players_game_makes_no_puzzles`, migration tests; QA `test_qa_another_players_run_leaves_your_filters_mode_and_suggestion`, `test_qa_your_trend_skips_another_players_report` (your 2nd report's trend is against your 1st, not theirs), `test_qa_your_own_username_as_another_player_counts_as_you`; e2e `test_another_player_is_kept_apart`. Stats: QA `test_qa_another_players_game_mistakes_stay_out_of_your_mistake_reason_stats` (xfail B1) |
| FR-10.3 accounts: override per run (Lichess / chess.com / both) | e2e + code | FAIL (B5) | `CoachView.tsx` has no platform control; the backend's `CoachParams.platforms` is never set by the UI |
| FR-10.21 / FR-8.16 the Coach prompt has no names, usernames, dates, URLs or game ids | integration (QA, through the service) | PASS | `test_the_prompt_is_anonymized`, `test_another_players_report_gets_coaching_without_their_name`; QA `test_qa_a_metadata_heavy_game_leaves_no_trace_in_the_coach_prompt` (a PGN with Event, Site URL, Date, names, Elo, UTCTime, Annotator, comment and `%clk`, imported and run at Detailed with Both: none of 16 markers in the system + user text, no `game_id`/`"ply"`, `max_tokens` 5,000) |
| FR-10.22–10.25 validated AI presets, fallback, cap and budget, saved answer free, logged under `coach` | integration + e2e | PASS | `tests/integration/test_coach_ai.py` (5 tests); e2e `test_ai_coaching_needs_a_confirm`; QA screenshots coach-ai-confirm / coach-ai-result |
| FR-10.14 progress, ETA, cancel; one run at a time | integration + code | PASS (cancel: manual) | QA `test_qa_a_second_run_while_one_is_going_is_refused` (one report). Cancel mid-run: code path `_wait` → `runner.cancel(job)`; not timed in a test (For Adam) |
| FR-10.40 level and think-time settings validated | integration | PASS | `test_the_puzzle_level_through_the_games_settings`; QA `test_qa_level_and_think_time_bounds_are_checked` (0.2 and 5.0 kept; 0.1, 5.01, bool, string, bad margin refused) |
| FR-10.9 Coach analysis at Game Review's 0.3 s | smoke | PASS | QA smoke: `games.analysis_think_s = 0.3` after the Coach run |
| FR-10.39 puzzles after any analysis + backfill | integration | PASS | `test_any_analysis_calls_the_puzzle_hook`, `test_the_backfill_tags_old_puzzles_and_runs_once`; `app.py` starts the backfill at launch |
| FR-10.28–10.31 Suggested label, Why this mix, banner Apply / Compare / Dismiss | e2e | PASS (B3) | `test_a_coach_run_shows_the_report_and_applies_the_suggestion`, `test_the_banner_waits_when_you_changed_your_filters`, `test_apply_from_the_banner`; QA `test_qa_staying_on_the_coach_page_applies_the_mix_on_screen`; leaving the page: `test_qa_leaving_the_coach_page_during_a_run_still_applies_the_mix_on_screen` (xfail B3) |
| FR-11.30 Send to Coach | e2e + smoke | PASS | `test_send_to_coach_runs_on_exactly_those_games`; QA smoke drove the real Send to Coach → Run |
| FR-1.15 Coach model (Same as Explain) | integration + e2e | PASS | `test_the_answer_is_validated_saved_and_logged_under_the_coach`; v0.9 feature tests updated for `coach` |
| FR-10.15 Lichess puzzle dashboard via `http.py`, scrubbed fixture | integration | PASS | `tests/integration/test_lichess_dashboard.py` (4); fixture has numbers only |
| Bridge: 13 new methods, allowlist | contract | PASS | `tests/contract/test_bridge_allowlist.py` (default suite); all `@bridge_call` |
| Vendored tagger: licence, pin, imports, no logging | contract + review | PASS | `tests/contract/test_vendored_tagger.py` (4); `LICENSE` is AGPL-3.0; pin `8e24b6d5e2b9…` in the vendor README, REQUIREMENTS §16 and the test; imports only `chess`, `typing`, `dataclasses` and each other |

---

## Bugs

### v0.10-B1 (major): another player's game mistakes count in your Stats
- **Steps:** Coach → **Another player** → enter a username → Run. Then ☰ → Stats → **Why you missed** → From: **Games** (or **All**).
- **Expected:** FR-10.3 and the plan: another player's games "never count in your stats". The User Guide says the same ("they never change … your stats").
- **Actual:** every inaccuracy, mistake and blunder of theirs is added to your game rows, as *not tagged*. `game_reason_rows` in `adapters/db/repos/stats.py` selects game errors with `g.user_color = ga.mover`. For a game that is only another player's, `games.user_color` holds *their* color (ARCHITECTURE §7, 0008 entry), and the query doesn't look at `game_subjects`. After 50 of their games, your Stats can show hundreds of untagged "game mistakes" that aren't yours. If you open one of their games in Game Review, its reason chips and Retry treat their moves as yours too, so a reason you click there is counted in your shares as well (see Observations).
- **Evidence:** `tests/integration/test_qa_v010_coach.py::test_qa_another_players_game_mistakes_stay_out_of_your_mistake_reason_stats` (xfail strict): `untagged` goes from 0 to 2 after one planted game of `lichess:someone_x`.

### v0.10-B2 (minor): a blunder that allows mate from a good position is classed Missed
- **Steps:** a game where you're about +1.5 or better and blunder into a mate in one (QA engine game: you're Black, about +1.8, and play 7...Qh6??, allowing 8.Rd8#). Analyze it.
- **Expected:** FR-10.11: **Allowed** = "your move let the opponent win material or mate". This is an Allowed back-rank mate, and FR-10.42 makes it an Allowed puzzle solved as White.
- **Actual:** `missed_or_allowed` (the v0.8 "simple rule", unchanged in v0.10 although its comment says "refined in v0.10") returns **Missed** whenever the eval before was ≥ 150 for you. The Missed check then runs on your position before the blunder, finds no tactic, and makes no puzzle. The Coach counts it as a missed tactic with the themes of a line you never had, and the real lesson (the allowed mate) is lost. In v0.8 this was only a label; in v0.10 it decides puzzles and the Coach's rankings.
- **Evidence:** `tests/engine/test_qa_v010_real.py::test_qa_an_allowed_mate_in_a_real_game_is_solved_as_your_opponent` (xfail strict, real Stockfish): row 13 is `blunder` / `missed`, and no puzzle exists.

### v0.10-B3 (major): leaving the Coach page during a run loses the Suggested mix on screen
- **Steps:** Coach → **Run the Coach** (on your games). While it runs, go to **Puzzles** (the User Guide: "You can keep solving puzzles meanwhile"; 50 new games take about 20 minutes). Wait for the run to finish.
- **Expected:** the backend has applied the Suggested mix (your filters were untouched), so the main page shows *Suggested — from Coach run #N* and the Mixer shows the new mix.
- **Actual:** nothing changes on screen. Only `CoachView` reloads the filters (`onRunDone`), and only if it's mounted when the job ends; coming back to the Coach page doesn't do it either (`running_job` is gone by then). So: no label or **Why this mix**; **Start** trains on the old filters held in `App.tsx`; and the first filter you touch saves the old filters plus your change over the applied suggestion (`changeSpec`), after which the next run treats your filters as changed by hand and shows the banner. The mix appears only after a restart, if you didn't touch anything.
- **Evidence:** `tests/e2e/test_qa_v010_ui.py::test_qa_leaving_the_coach_page_during_a_run_still_applies_the_mix_on_screen` (xfail strict: no `suggestion-label` after the run). Staying on the page works (`test_qa_staying_on_the_coach_page_applies_the_mix_on_screen`). The same happened in the real app when I started a run through the bridge and then opened Puzzles.

### v0.10-B4 (minor): with Show best moves off, Explain this move still names the better move
- **Steps:** Show best moves off. My games → Review game 1 → 4.Nxe5?? → **Explain this move** → Confirm.
- **Expected:** FR-11.35: while it's off, Game Review "hides everything that gives the better move away", including "the AI's better lines and arrows"; the AI's text stays.
- **Actual:** the board arrows and **Show me** are hidden, correctly. But the explanation's step list (`ExplanationView`, `explanation-steps`) is the validated best line rendered as moves: "**You: Nxd4** Nxd4 guards the square…", with *(for example …)* variations. That's the better line itself, not free AI prose. (The summary may name the move too; that's AI text, which the requirement keeps.) Explain is a deliberate request, so this is minor, but the guide's list of what Off hides suggests otherwise.
- **Fix options:** hide the steps until Show best moves is on, or say in FR-11.35 and the User Guide that Explain this move shows the line.
- **Evidence:** `tests/e2e/test_qa_v010_ui.py::test_qa_show_best_off_hides_the_better_move_in_the_explanation_steps` (xfail strict); `qa-v010-review-explain-best-off.png`.

### v0.10-B5 (minor): no choice of your accounts (Lichess / chess.com / both) for a run
- **Steps:** link both a Lichess and a chess.com account, open the Coach, choose **You**.
- **Expected:** FR-10.3: "defaults to your linked accounts, and you can override them per run. Lichess username and/or chess.com username." Plan step 8 ("subject: me, with the platform set to Lichess, chess.com or both") and step 12 ("Subject: You (Lichess / chess.com / both)").
- **Actual:** the **You** option has no platform control; `CoachView.tsx` never sets `params.platforms`, so a run always takes every game of yours (imports included). The backend supports it (`CoachParams.platforms`, `LibraryFilter.platforms`). The User Guide doesn't mention the choice either, so the docs and the UI agree; the gap is against the requirement and the plan.
- **Evidence:** code (`grep platforms web/src/views/CoachView.tsx`: no hits); screenshots `qa-v010-coach-empty.png`, `qa-v010-real-coach-report.png`.

### v0.10-B6 (minor): two text issues
- **"1 games":** the Coach's **Saved reports** list shows "2026-11-04 · You · 1 games" for a one-game run (`CoachView.tsx` line ~592 builds `${s.games} games`). Seen in the real app (`qa-v010-real-coach-report.png`); the report header next to it correctly says "1 game".
- **User Guide, *Puzzles from your games*:** "A one-move win of material isn't kept; a mate in one is." A missed mate in one is kept only when no other move also wins clearly (Lichess's rule: every non-mating move ≤ 0.6 in win chances). In the QA game, 8.Qxf7# missed with 8.Bxf7+ (+7.4) also there made no puzzle. Suggested wording: "…a mate in one is, unless another move wins easily too."
- **Evidence:** screenshot above; for the guide, the engine run described under Observations (`coach_candidates.reason = 'no_forced_mate'`).

### v0.10-B7 (minor): a traceback in the log at every launch before the puzzle database exists
- **Steps:** a fresh data folder with no `puzzles.db` (first run, before the import). Start the app (`uv run python -m weaksquare --dev` with a new `WEAKSQUARE_DATA_DIR`).
- **Expected:** no ERROR in the log; the catalog is empty or refused with a readable code until the import.
- **Actual:** `App.tsx` now calls `getThemeCatalog()` when it mounts (new in v0.10, for the Compare dialog and the banner). With no puzzle DB, `puzzles.py: theme_counts` hits `no such table: pz.theme_bits`, and the bridge logs `ERROR … bridge get_theme_catalog crashed` with a full traceback (twice in `--dev-server`). The UI ignores the error, so nothing shows, but it's an "internal" crash in every first-run log, which makes real problems harder to spot in a support log.
- **Evidence:** the dev-run rows above; `tests/integration/test_qa_v010_fresh_install.py::test_qa_the_theme_catalog_before_the_puzzle_db_exists_is_not_a_crash` (xfail strict).

### v0.10-B8 (minor, test only): the builder's v0.9 smoke test fails with three AI features
- **Steps:** `npm.cmd --prefix web run build`, then `uv run pytest -m smoke tests/smoke/test_real_app_v09.py`.
- **Actual:** `explain, game_review = settings["data"]["features"]` → `ValueError: too many values to unpack (expected 2)`. v0.10 added the `coach` feature; commit `99e88a6` updated the other v0.9 tests but not this smoke test. Not a product bug, but `-m smoke` is red on this branch.
- **Evidence:** the smoke row above; `tests/smoke/test_real_app_v09.py:52`.

---

## Tests added

- `tests/integration/test_qa_v010_coach.py` (14 passed, 1 xfailed): `test_qa_each_level_gives_its_set_and_a_round_trip_runs_no_engine`, `test_qa_narrowing_keeps_the_attempts_and_the_archived_puzzle_is_not_served`, `test_qa_a_puzzle_you_archived_stays_archived_across_level_changes`, `test_qa_a_re_analysis_at_another_think_time_makes_no_duplicate`, `test_qa_two_coach_runs_and_the_backfill_make_no_duplicates`, `test_qa_a_coach_allowed_puzzle_takes_a_move_within_tolerance_and_the_engine_continues`, `test_qa_another_players_game_mistakes_stay_out_of_your_mistake_reason_stats` (xfail B1), `test_qa_your_trend_skips_another_players_report`, `test_qa_another_players_run_leaves_your_filters_mode_and_suggestion`, `test_qa_your_own_username_as_another_player_counts_as_you`, `test_qa_filters_changed_after_an_applied_suggestion_are_never_overwritten`, `test_qa_a_mode_change_alone_isnt_a_filter_change`, `test_qa_a_metadata_heavy_game_leaves_no_trace_in_the_coach_prompt`, `test_qa_a_second_run_while_one_is_going_is_refused`, `test_qa_level_and_think_time_bounds_are_checked`.
- `tests/engine/test_qa_v010_real.py`: `test_qa_a_missed_mate_in_a_real_game_becomes_your_puzzle`, `test_qa_an_allowed_mate_in_a_real_game_is_solved_as_your_opponent` (xfail B2).
- `tests/fulldb/test_qa_v010_fulldb.py`: `test_qa_every_key_the_tagger_can_keep_is_a_puzzle_db_theme`, `test_qa_the_tagger_agrees_with_the_db_on_real_mate_puzzles`.
- `tests/e2e/test_qa_v010_ui.py`: `test_qa_show_best_off_explain_this_move_hides_the_board_arrows`, `test_qa_show_best_off_hides_the_better_move_in_the_explanation_steps` (xfail B4), `test_qa_show_best_off_explain_my_game_hides_better_lines`, `test_qa_analyze_from_here_screens`, `test_qa_leaving_the_coach_page_during_a_run_still_applies_the_mix_on_screen` (xfail B3), `test_qa_staying_on_the_coach_page_applies_the_mix_on_screen`, `test_qa_coach_screens`, `test_qa_banner_and_compare_screens`, `test_qa_settings_and_my_puzzles_screens`.
- `tests/smoke/test_qa_v010_real_app.py`: `test_qa_v010_show_best_moves_survives_a_relaunch`, `test_qa_v010_a_coach_run_with_the_real_stockfish` (copies the dev folder's managed Stockfish into the temp folder, then Send to Coach → Run in the real UI; skips without it).
- `tests/integration/test_qa_v010_fresh_install.py`: `test_qa_the_theme_catalog_before_the_puzzle_db_exists_is_not_a_crash` (xfail B7).

Screenshots (gitignored), `tests/e2e/artifacts/qa-v010-*.png`: coach-empty, coach-another-player, coach-report, coach-ai-confirm, coach-ai-result, banner, compare, mixer-suggested, mixer-suggested-why, my-puzzles-filters, settings, review-explain-best-off, review-narrative-best-off, analyze-here-best-off, analyze-here-best-on, and from the real app real-review-best-off, real-coach-empty, real-coach-report, real-mixer-suggested. I looked at them. No clipped text or broken layout. Findings: "1 games" (B6) in the real Saved reports; the Compare shot was taken mid-fade (my timing, not the app).

---

## Scope, architecture and security findings

- **Later versions:** nothing built. No checkpoints, `weakness_metrics`, statuses, Progress page or notifications (v1.0); no digests, Advanced analysis, lesson links or notes (v0.11). Danger spotting stays Lichess-only for My puzzles (plan decision). The label reads *Coach run #N*.
- **`core/`:** the new modules (`coach`, `coach_llm`, `habits`, `puzzle_gen`, `suggested_mix`, `tagging`, `preset_suggestion`) import only the standard library, python-chess, other `core` modules and the vendored tagger. No `datetime.now()`, `time.time()` or global `random` in `core/` or `services/` (the three `import random` hits are pre-existing type imports for the injected `rng`).
- **Layers (minor, no bug filed):** `services/game_puzzles.py` imports the `Candidate` dataclass from `adapters/db/repos/coach.py`. It's a type, not a concrete adapter (wiring is still only in `app.py`), but it's the only service that imports from `adapters/`; the dataclass belongs in `core/`.
- **Threads / engine:** repos use the shared `Database` (a connection per thread). Puzzle checks and the Coach's analysis use `analyse_background`; Analyze from here uses the interactive engine (tested). The Coach waits on the analysis job from its own job thread; the real-app run shows no deadlock.
- **Bridge:** new dependencies are underscore attributes (`_coach`, `_game_puzzles`); every new method has `@bridge_call`; the allowlist test passes.
- **Front end:** no localStorage, sessionStorage, IndexedDB or cookies in `web/src`; no `dangerouslySetInnerHTML`; AI text renders as React text.
- **Migrations / dependencies:** only `user/0008_coach.sql` added; no applied migration edited. No new PyPI or npm package: `pyproject.toml`, `package.json`, `uv.lock` and `package-lock.json` change only the version (plus ruff/mypy excludes for `vendor/`).
- **Data:** tests use temp folders; the smoke harness uses a temp `WEAKSQUARE_DATA_DIR` (my smoke test copies Stockfish *from* the dev folder, read-only). The CDP port is still set only by `tests/smoke/conftest.py`, and `app.py` refuses it without `--dev` (SR-16).
- **Secrets / fixtures:** no `lip_`, `sk-ant-` or `sk-` value outside `FAKE` placeholders in the v0.10 diff. `dashboard.json` has numbers and theme names only. New usernames are `opponent_b`, `someone_x`, `player_a`. The only lichess.org URL with a path in new code is an upstream comment in the vendored `util.py` (a board-editor position, no user or game).
- **Builder tests (observation):** `_my_games(services, n)` in `test_coach_run.py` imports the same PGN *n* times, so it's one game (the v0.8 dedupe). Tests that call it with 2 or 3 (`test_coach_ai.py`, `test_v010_bridge.py`) run on one game. My QA tests use distinct move lists.

## Observations (no bug filed)

- **Lichess's mate-in-one rule drops some missed mates.** A missed mate in one is kept only if every non-mating move is ≤ 0.6 in win chances. In the QA game where 8.Qxf7# was missed but 8.Bxf7+ also wins (+7.4), no puzzle was made (`no_forced_mate`). That's the ported rule working as Adam decided, but you may notice obvious missed mates without a puzzle. See also B6.
- **The Suggested mix sets the training mode too.** "Untouched" is decided on the filters only, so a mode you picked by hand (with the default filters) is replaced by the suggestion's mode.
- **Reviewing another player's game** (from the Player filter) treats their moves as "yours": the reason chips and Retry appear for their mistakes, and what you record there goes into your reasons and Retry totals. Same root cause as B1.
- **Bridge-only edge:** `start_coach_run` for you with `game_ids` that include another player's game counts that game in the report's games (denominator). The UI can't send it (Send to Coach is hidden for other players).
- **Plan file:** `plans/v0.10.md` step 9 (Suggested mix) is still unticked although it's built and tested.

---

## Docs findings

- `check_docs.py` and `--strict`: 0 errors, 0 warnings [version v0.10].
- **Developer Guide:** every command run as written (table above), except the credential/live/network ones. The new *Vendored code* procedure matches `src/weaksquare/vendor/README.md` and `PIN` in the contract test.
- **User Guide, followed against the mock (QA e2e) and the real app (QA smoke):**
  - *Show best moves and Analyze from here* (Added in v0.10): labels, default off, what it hides and keeps, **◀ Back** / **Forward ▶** / **Reset** / **Back to the game**, "Game position:" eval: as written. B4 for the explanation steps.
  - *Puzzles from your games* (Added in v0.10): "from move 7 on" matches the 12-ply skip; levels, archive and restore, manual save wins, other players make none: as written. "A one-move win of material isn't kept; a mate in one is": B6.
  - *The Coach* (Added in v0.10): steps 1–4, Send to Coach, the report sections, Another player, the Suggested mix, AI coaching: as written, except step 3 has no per-account choice (B5) and step 4's "You can keep solving puzzles meanwhile" leads into B3. "Another player … never change … your stats": B1.
  - *My puzzles* (Changed): origin and severity filters, **Open the game** / **Archive this puzzle**: present.
  - *Your data and privacy*: Get AI coaching (what it sends matches `build_prompt`'s allow-list), the other player's public games (`/api/games/user/<name>`, chess.com archives one at a time), the dashboard (`/api/puzzle/dashboard/30`, only when signed in): all match the code.
- **CHANGELOG `[Unreleased]`:** one line each for Show best moves, Analyze from here, My puzzles filters, theme tags, the Coach, AI coaching (with what it sends), another player, the Suggested mix, puzzles from your games, habit tags. Covers every user-visible *Done when* item.
- **README** status line is true ("v0.10 … is being built"). **ARCHITECTURE** §2 lists the new modules and `vendor/`; §7 has the v0.10 entries (schema, vendored tagger, pipeline hook, Coach run, AI coaching).
- **Screenshots:** `uv run pytest -m docs_screenshots` regenerates `docs/img/` with no content change.

---

## For Adam's manual test

- **Real AI coaching:** not run (no key used, `-m live` not run). Run **Get AI coaching** once on a real report and judge the summary and presets; check Settings → AI shows the Coach's spend.
- **Another player on the network:** fetching a real Lichess / chess.com player's games wasn't run (QA never calls the real sites). Run the Coach on another username, then check it appears under **Player** in My games, that your Suggested mix is unchanged, and (B1) look at Stats → Why you missed → From: Games before and after.
- **B3 in practice:** start a 50-game run, go to Puzzles while it runs, and see whether the *Suggested* label appears when it finishes (it won't until a restart, or you're back on the Coach page when it ends).
- **Cancel mid-run:** press **Cancel** during the analysis step and check that the analysis queue stops and no report is saved.
- **Your dev data folder is still at user.db v7.** The first `uv run python -m weaksquare --dev` on this branch migrates it to 0008 and starts the one-time backfill (tags, then puzzles from every analyzed game, on Stockfish). A v0.9 checkout then refuses it (the newer-schema check); the migration keeps a backup first, so switching back means restoring that. I didn't touch the dev folder.
- **The quality of the weaknesses and puzzles** on 50–100 of your real games (the plan's checklist): only a person can judge whether the top 3 match your games. Note B2 and the mate-in-one observation when you look for Allowed puzzles.


## Builder's fixes after round 1 (2026-11-04)
B1–B8 fixed, each with a regression test; QA's xfail tests are now plain tests. See ARCHITECTURE.md §7, "v0.10: QA fixes (v0.10-B1 to B8)". B2 was narrowed: only walking into a forced mate overrides Missed (QA's Missed engine test still passes).

---

## Round 2 (2026-11-04): re-verification of B1–B8 (commit `4f2ee0b`)

### Final verdict: **PASS WITH ISSUES** (B1–B8 fixed; 2 new minor issues, B9 and B10)

The fix commit touches `stats.py`, `review.py`, `game_review.py`, `bridge/api.py`, `App.tsx`, `ExplainPanel.tsx`, `CoachView.tsx`, `mockCoach.ts`, the User Guide, REQUIREMENTS, ARCHITECTURE §7 and tests. My round-1 tests are unchanged except that the xfail markers were removed (I checked the diff: no assertion was changed). No new dependency or migration.

| Bug | Re-test | Result | Evidence |
|---|---|---|---|
| B1 other player's mistakes in your Stats | integration | **Fixed** | `test_qa_another_players_game_mistakes_stay_out_of_your_mistake_reason_stats` passes (`game_reason_rows` now joins `game_subjects` 'me'); builder `test_b1_another_players_game_records_nothing_as_yours` (no Retry, no reason chips, `set_game_reason` refused) |
| B2 allowed mate classed Missed | engine + unit | **Fixed** | `tests/engine/test_qa_v010_real.py::test_qa_an_allowed_mate_in_a_real_game_is_solved_as_your_opponent` passes with real Stockfish (Allowed at ply 13, puzzle from the position after 7...Qh6, `d1d8`, solved as White, won); the Missed test still passes; `test_v010_b2_walking_into_mate_from_a_winning_position_is_allowed` |
| B3 mix not reloaded after leaving the Coach page | e2e | **Fixed** (side effect: B9) | `test_qa_leaving_the_coach_page_during_a_run_still_applies_the_mix_on_screen` passes; new `test_qa_r2_the_mix_reloads_on_the_puzzles_page_with_its_mode` (label shown, Mixer mode Danger spotting) |
| B4 explanation steps with Show best off | e2e | **Fixed** | `test_qa_show_best_off_hides_the_better_move_in_the_explanation_steps` passes ("The line is hidden while Show best moves is off."). Puzzle Explain always passes Show me, so its steps still show (checked: `ExplanationView` has two callers) |
| B5 account choice | e2e | **Fixed** (docs: B10) | builder `test_b5_you_can_coach_one_of_your_accounts` (mock records `coachPlatforms:chesscom`); control visible in the regenerated `coach-report.png` |
| B6 "1 games", guide sentence | e2e + docs | **Fixed** | builder `test_b6_one_game_is_singular_in_saved_reports`; the User Guide now explains the mate-in-one exception |
| B7 theme-catalog crash before the import | integration | **Fixed** | `test_qa_the_theme_catalog_before_the_puzzle_db_exists_is_not_a_crash` passes (returns `[]`, no "crashed" log) |
| B8 builder v0.9 smoke test | smoke | **Fixed** | `test_real_app_v09.py::test_game_review_model_in_the_real_app` passed in the full smoke run |

### v0.10-B9 (minor): a Coach run that ends during a session changes the Mixer's mode but not the session's
- **Steps:** Coach → **Run the Coach** → go to Puzzles → **Start** (Standard). Let the run finish (its suggestion's mode is Danger spotting, with untouched filters).
- **Expected:** the Mixer and the running session agree on the mode. §6: changing the mode while a session runs starts a new session in that mode (`changeMode`); otherwise the shown mode stays the session's.
- **Actual:** the B3 fix calls `reloadFilters()`, which runs `setMode(s.mode)` directly. The Mode control shows **Danger spotting** (and the Rated switch is greyed out with "Danger spotting stays on this PC") while the session bar says **Standard** and the puzzles go on as Standard and rated. The filters on the left also switch to the new mix under the running session. **Start** or a mode click brings the two back in step. Minor, and only while a session is running, but it's confusing (is my current puzzle rated?).
- **Fix options:** while a session is running, reload only the label and banner and apply the new filters and mode when the session ends or at the next Start; or follow `changeMode`'s rule.
- **Evidence:** `tests/e2e/test_qa_v010_ui.py::test_qa_r2_a_run_ending_mid_session_keeps_the_mode_shown_and_the_session_in_step` (xfail strict: `('danger_spotting', 'Standard')`); `qa-v010-r2-mid-session.png`.

### v0.10-B10 (minor, docs): the account choice and the hidden explanation line aren't in the User Guide, and the Coach screenshot is stale
- **The Coach → Running the Coach, step 3** still lists only whose games, count, time controls, Rated only and color. The new **All my games / Lichess / chess.com** control (B5) isn't mentioned.
- **`docs/img/coach-report.png`** was not regenerated after B5: `uv run pytest -m docs_screenshots` changes it (the new control appears above **Games**). I restored the committed file.
- **Show best moves and Analyze from here → "Off hides"** doesn't list Explain this move's step-by-step line, which Off now hides (B4).
- **Evidence:** `git status docs/` after `uv run pytest -m docs_screenshots` (only `coach-report.png`); `docs/USER_GUIDE.md` sections named above.

### Observations (no bug filed)
- **B2 and games analyzed earlier:** the stored `kind` of moves analyzed before the fix (v0.8/v0.9 games, or this branch's rc builds) isn't recomputed by the tag backfill, which only re-tags. They change only on a threshold change (regrade) or a re-analysis. Adam's dev folder has never run v0.10, so this matters only for games analyzed during the rc testing.
- **Formatting churn:** the fix reformats `ExplainPanel.tsx` (and parts of `App.tsx`) to a narrower line width than the rest of `web/src`. Lint and typecheck pass; it's just a noisy diff.
- `test_qa_v06_real_app.py::test_v06_danger_reasons_and_name_the_idea_in_the_real_app` timed out once in the full smoke run and passed 2 of 2 re-runs (it doesn't touch v0.10 code). Round 1's v0.5 smoke flake didn't recur.

### Round-2 runs
| Command | Result |
|---|---|
| `uv run pytest` | **1717 passed, 1 skipped**, rc 0 (297 s) |
| `uv run pytest -m engine` | **19 passed** (incl. both QA engine tests) |
| `uv run pytest -m e2e` | **288 passed**, rc 0 (706 s). Then my 2 round-2 tests in `test_qa_v010_ui.py`: 10 passed, 1 xfailed (B9) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0; **34 passed, 1 skipped, 1 failed** (the v0.6 flake above, 2/2 on re-run). QA v0.10 smoke and the fixed v0.9 smoke passed |
| `uv run pytest -m docs_screenshots` | 37 passed; `coach-report.png` drifts (B10) |
| `uv run ruff check .`, `ruff format --check .`, `uv run mypy src` | clean; 374 files formatted; no issues in 119 files |
| `npm.cmd --prefix web run typecheck` / `lint` (PowerShell AllSigned) | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings [version v0.10] |
| `-m fulldb` | not re-run: the fixes don't touch the puzzle DB or the filters (round 1: 72 passed, 3 xfailed, 1 known timing failure) |
| `-m live` | not run (Adam's) |

**Tests added in round 2** (`tests/e2e/test_qa_v010_ui.py`): `test_qa_r2_the_mix_reloads_on_the_puzzles_page_with_its_mode`, `test_qa_r2_a_run_ending_mid_session_keeps_the_mode_shown_and_the_session_in_step` (xfail B9).

**For Adam's manual test** (in addition to round 1): start a puzzle session while a Coach run is going and look at the Mode control and the Rated switch when it finishes (B9). Try **Lichess** / **chess.com** on the Coach page with both accounts linked.

## Builder's fixes after round 2 (2026-11-04)
B9 and B10 fixed with regression tests (QA's B9 test is now plain). The round-2 observation about old Missed/Allowed labels is fixed too: the backfill regrades stored moves before re-tagging (`test_r2_the_backfill_applies_the_b2_rule_to_old_analysis`).
