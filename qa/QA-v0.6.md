# QA report: v0.6 (Training modes II + mistake reasons)

**Round 1, 2026-11-03.** Branch `v0.6` at `663c951`. Independent QA. I changed no product code, migrations, config or docs. New tests are under `tests/` only (`test_qa_v06_*`), plus two test-only race fixes in older QA smoke tests (see *Tests added*). I did not run `pytest -m live` and read no keyring entry. The real-app QA flow used a temp `WEAKSQUARE_DATA_DIR` with a copy of the dev folder's managed Stockfish. Two Developer Guide commands that I ran as written use the dev data folder; see *For Adam*.

## Verdict: **FAIL** (two majors: B1, B5)

Every *Done when* item passes with evidence:
- the safe-candidate verification (fake engine, plus real Stockfish)
- the reason-suggestion rules
- a misclick left out of local stats but still sent to Lichess as a loss

The full automated suite is green. Two majors block the gate:
- **B1:** in Danger spotting, the time a puzzle takes to appear gives the answer away. In the real app, guessing from the load time alone was right on 14 of 14 puzzles, in each of 5 runs.
- **B5:** after a wrong punishing move in Danger spotting, "Why your move fails" shows the eval from the wrong side, so a losing move reads as "+3.0 for you".

Six minor issues (B2–B4, B6–B8).

Builder's question about `test_qa_v05_round3_ladder_worst_case.py::[fork, promote 3->4]`: **confirmed, not a v0.6 regression.** I ran a same-machine A/B with the v0.5 SQL against the v0.6 SQL (`SOLVED_IDS`, `MISSED_IDS`, `NOT_MISCLICK` swapped in, interleaved, 10 runs each). Medians were 0.450 s (v0.5) and 0.454 s (v0.6). In my full `-m fulldb` run the case passed at 494 ms.

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder tests: **992 passed**, 307 deselected (193 s). With the QA tests: **1016 passed, 3 xfailed** (B1, B3, B5), 325 deselected (196 s) |
| `uv run pytest -m e2e` | **172 passed** (459 s). QA file `test_qa_v06_ui.py`: 13 passed, 1 xfailed (B2) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **23 passed, 2 failed, 1 skipped** (285 s). Both failures are races in older QA tests, not the app: `test_qa_v03_real_app.py::test_signed_out_solve…` read "Checking…" too early, and `test_qa_v05_real_app.py::test_v05_modes…` waited for the replies line on a one-move puzzle (hidden since v0.5-B4); it failed 2 of 5 runs. Fixed in the tests, then 3 of 3 passed. QA file `test_qa_v06_real_app.py`: passed. The Danger part (14 puzzles + the timing measure) ran in 5 runs; the first 4 stopped later on my own test's bugs (a print encoding error, a puzzle lookup), fixed before the final run |
| `uv run pytest -m fulldb` (dev `puzzles.db` imported) | **70 passed, 3 xfailed** (549 s), with `fork, promote 3->4` at 494 ms. QA `test_qa_v06_fulldb.py`: 3 passed. The first run failed on a typo in my test (`StatsRepo.rows`); fixed and re-run |
| `uv run pytest -m engine` | **11 passed** (37 s) |
| `uv run pytest -m docs_screenshots` | **24 passed**; `docs/img` unchanged (no git diff) |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 247 files already formatted (with the QA files) |
| `uv run mypy src` | Success: no issues found in 74 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.6]` (both) |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete" |
| `uv run python -m weaksquare --dev` (after the build) | window up, WM_CLOSE → rc 0, no ERROR lines in the log; dev `user.db` migrated 4 → 5 with backup `user-4-20261103-152106.db` |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` | Vite 200, window up, rc 0 |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, Vite "mock" ready |
| `fetch_puzzle_db.py --dev`, `record_db_update.py`, `set_test_token.py`, `-m live` | not run (unchanged since v0.4; they would replace the dev DB, call Lichess or need credentials) |

No human-facing command uses a `.ps1`, bare `npm` / `npx` or venv activation.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **DW** Safe-candidate verification test | unit + integration + real engine | PASS | `test_danger_mode.py` (50 cp edge, blunder never safe, mate against excluded, best = best of all lines, none qualify, ~50/50 + owed slot, random pick); `test_modes_v06.py::test_about_half_the_candidates_are_safe…` (MultiPV 5); `tests/engine/test_danger_safe_real.py` (Stockfish 19 re-analysis within 50 cp + noise); QA `test_an_engine_failure_shows_the_blunder_and_owes_a_safe_one` |
| **DW** Reason-suggestion rule tests | unit + integration | PASS | `test_reasons.py` (each rule, order, exact threshold, help-decided never rushed); `test_modes_v06.py` rushed / miscalculated / missedResource / Danger rule; QA `test_unknown_pattern_is_suggested…`, `test_name_the_idea_rushed_counts_from_start_solving`, `test_rushed_at_exactly_the_threshold_is_not_rushed_in_danger` (3.0 s → none, 2.9 s → rushed), `test_show_answer_before_the_call_is_a_loss_with_no_suggestion` |
| **DW** Misclick excluded locally, still sent as a loss | integration (fake Lichess) + real app | PASS | `test_misclick_is_excluded_locally_but_still_sent_to_lichess_as_a_loss` (`win: False` sent; Stats 0 attempts, 1 misclick); QA `test_the_sync_code_never_reads_mistake_reasons`; real app: Failed 1 → 0, "1 misclick", Stats note (`qa-v06-real/misclick-session-bar.png`) |
| FR-4.3 tag before moving; ≥1 tag, ≤3 per slot; slot ignored; motif groups | unit + integration + e2e + real app | PASS | `test_name_idea_mode.py` (11); QA bad types → `invalid_argument` (6 params), tag twice / wrong mode → conflict; e2e QA `test_board_takes_no_moves_before_start_solving`, `…more_than_three_tags…`; real app "Ideas found 0 of 1 · 1 extra / ✗ Fork / Missed: Quiet move", `idea_tags` stored |
| FR-4.3 no tag score without motifs | unit | PASS | `test_puzzle_without_motifs_has_no_tag_score` |
| FR-4.4 raw FEN, side to blunder, candidate arrow, Safe/Unsafe, S/U | integration + e2e + real app | PASS | `test_the_blunder_never_reaches_the_front_end…`; e2e `test_danger_spotting_safe_then_blunder…`; QA `test_double_pressing_s_calls_once`, `test_s_and_u_do_nothing_outside_danger_spotting`; real app 14 calls + refutations |
| FR-4.4 refutation = first move only, board flips, any mate | unit + e2e + real app | PASS | `test_blunder_called_unsafe_then_the_refutation_wins`, `test_any_mating_refutation_is_accepted`; real app header "you play black" after a white blunder (`qa-v06-real/danger-refute-0.png`) |
| FR-4.4 blunder never sent before the end | integration (new) | PASS | QA `test_nothing_before_the_call_reveals_the_truth` (session stats, hint, refutation, analyze ×2, prompt, move, retry). **But see B1:** load time reveals it |
| FR-4.4 help: no Hint before the call; Show answer = loss | unit + integration + e2e | PASS | `test_no_hint_before_the_call…`; QA integration + e2e `test_show_answer_before_the_call…` |
| FR-4.4 needs Stockfish; Start disabled | integration + e2e | PASS | `test_danger_spotting_needs_the_engine` (both) |
| FR-4.4 local only, Rated greyed, never queued | integration + e2e + real app | PASS | QA `test_rated_is_forced_off_and_nothing_is_ever_queued` (`local`, rated NULL, angle NULL); real app `DISTINCT mode, sync_status = [('danger_spotting','local')]`; Rated switch disabled |
| FR-4.6 / FR-3.9 Danger ignored by SRS and history filters | integration (new) | PASS | `test_danger_results_skip_srs…`; QA `test_a_danger_win_doesnt_hide_the_puzzle_from_exclude_solved_here`, `test_a_danger_miss_after_a_standard_miss_keeps_it_in_only_my_misses` (and SRS still scheduled) |
| FR-3.11 depth ladder only in Standard / Commit | integration + e2e | PASS | `test_name_the_idea_works_without_a_depth_ladder`, QA `test_danger_is_refused_with_the_depth_ladder`, e2e `test_the_depth_ladder_is_not_offered…` |
| FR-5.6 six reasons, keys 1–6 in order | unit + e2e | PASS | `test_reason_set_is_in_fr_5_6_order…`, e2e chips test |
| FR-5.7 asked after every failed puzzle in every mode, incl. Danger | integration + e2e + real app | PASS | `test_reason_prompt_after_a_loss…`, `test_danger_blunder_called_safe…`; real app chips after a Danger miss |
| FR-5.8 never blocking, Skip, change, note, Always/Off, not in practice | integration + e2e | PASS (B2) | `test_skip_hides_the_chips…`, `test_reasons_off…round_trips…`; QA `test_practice_run_keeps_the_original_attempts_prompt`, `test_reasons_off_never_asks_in_danger_either`, e2e `test_typing_digits_in_the_note…`, `test_a_201_character_note…`, `test_rapid_number_keys…` (last key wins), `test_practice_run_asks_nothing_new`. A key press drops the note: B2 |
| FR-5.9 suggestions only saved on click; rule order | integration | PASS (B4) | `suggested_reason` stored only with a chosen reason; QA `test_reason_for_an_earlier_puzzle…` (stored `None` once moved on, note kept as plain text) |
| FR-5.10 misclick excluded from session bar, Stats, ladder; SRS keeps it; warning 25% of ≥8 | integration | PASS | `test_misclick_is_left_out_of_the_session_bar_and_ladder`, `…keeps_the_puzzle_in_spaced_repetition`, `test_misclicks_are_not_in_the_ladder_window`; QA `test_misclick_is_excluded_from_stats_by_mode_details_and_reason_stats`, `test_misclick_warning_appears_at_a_quarter_of_eight` (1/7 off, 2/8 on) |
| FR-9.3 Commit / Name / Danger accuracy | unit + e2e + real app | PASS | `test_commit_and_name_the_idea_details`, `test_danger_spotting_counts_only_by_mode…`; real app "Safe moves called Safe 9 of 9 · Blunders spotted and punished 7 of 7" |
| FR-9.7 breakdown (theme, mode), weekly trend, misclicks apart | unit + integration + e2e | PASS | `test_reason_breakdown_filters_and_shares`, `test_reason_trend_by_local_week`, `test_reason_stats_over_the_bridge`, e2e Stats test; screenshots |
| §4 `mistake_reasons` table, migration 0005, v4 → v5 upgrade | integration + real dev folder | PASS | `test_user_db_v5.py`; dev `user.db` migrated with backup |
| Settings `reasons.ask` / `reasons.rushed_s` | integration + e2e | PASS | `test_rushed_threshold_setting`, `test_no_prompt_…when_off` |
| Bridge allowlist (5 new methods) | contract | PASS | `test_bridge_allowlist.py` |
| Idea lists equal between front and back end | contract | PASS | `test_idea_lists.py` |
| Full-DB timings with reasons | fulldb (new) | PASS | QA `test_qa_v06_fulldb.py`: Stats rows + report + reasons on 5,000 attempts 0.046 s; tallies 0.009 s; counts ≤ 0.352 s; Name the idea start + first puzzle ≤ 0.353 s |

---

## Bugs

**v0.6-B1 (major): Danger spotting gives the answer away by how long the puzzle takes to appear.**
- Steps: Danger spotting with Stockfish installed. Press Next and watch how long the new position takes.
- Expected: nothing observable before the call tells a safe candidate from the blunder (FR-4.4, "so the answer is never always Unsafe"; the plan's "the real blunder never reaches the front end").
- Actual:
  - `SessionService._danger_candidate` runs a full engine search (your think time, MultiPV 5) **only for safe slots**. Blunder slots return at once.
  - Real app, default 1 s think time: safe candidates appear after **1.34–2.97 s**, blunders after **0.06–0.28 s**.
  - Calling "Safe if it took more than 0.6 s" was right on **14 of 14** puzzles, in each of 5 runs.
  - With a longer think time (up to 10 s) the gap grows.
  - Also, the plan's "Preparing the position…" indicator isn't implemented (no such string in `web/src`). During the wait the old result stays on screen.
- Fix direction (builder's call): make the work and timing independent of the answer. For example, always analyse, or pad to a fixed delay, or prefetch the next candidate during the current puzzle.
- Evidence:
  - `tests/smoke/test_qa_v06_real_app.py` prints `QA-OBS danger loads` / `guessing from the load time alone: 14/14 right`.
  - `tests/integration/test_qa_v06_edges.py::test_b1_loading_a_danger_puzzle_does_the_same_work_whatever_the_answer` (xfail strict): engine searches per load are {1} for safe and {0} for blunder.

**v0.6-B5 (major): Danger spotting's "Why your move fails" is scored from the blunderer's side.**
- Steps: Danger spotting. Call the blunder Unsafe, play a wrong punishing move, then press Show answer.
- Expected: the refutation's eval is "for you", the side you're now playing (FR-7.2, §7.2).
- Actual:
  - `SessionService._player` takes the side to move in `start_fen`. In Danger spotting that's the raw FEN, the blunderer's side.
  - Fake engine: shown `+3.0 for you`, where the eval for you is `−3.0` and `+3.0` is the blunderer's. So a losing move reads as good for you.
  - The engine panel and Analyze after the end use the same side, so "Puzzle start: … for you" also refers to the blunderer after you played the punisher. That's defensible for a safe candidate, but not after a refutation.
- Evidence: `tests/integration/test_qa_v06_edges.py::test_b5_danger_wrong_refutation_is_explained_from_the_punishing_side` (xfail strict).

**v0.6-B2 (minor): keys 1–6 save the reason without your note.**
- Steps: after a miss, open **Add a note**, type, click a chip (saved with the note), click the board, press **5**.
- Expected: the note stays with the changed reason, as when you click a chip.
- Actual:
  - `reasonKey` in `TrainerView.tsx` calls `chooseReason(key, null)`. The new latest row has `note = NULL`, so the note is gone.
  - The builder's own e2e expects it: `["…didntLook:saw it too late", "reason:1=misclick"]`.
- Evidence: `tests/e2e/test_qa_v06_ui.py::test_b2_changing_the_reason_with_a_key_keeps_the_note` (xfail strict).

**v0.6-B3 (minor): the refutation can be searched twice.**
- What happens: after a lost puzzle with Stockfish installed, the front end asks for "Why your move fails" (`get_refutation`) and for the reason prompt (`reason_prompt` → `get_refutation`) at about the same time. Neither waits for an in-flight search. Both run the full search, serialized on the interactive engine, so the second answer arrives about one think time later.
- Evidence: `test_b3_reason_prompt_and_why_it_fails_share_one_refutation_search` (xfail strict): 2 searches of the same position.

**v0.6-B4 (minor): the "Rushed" think time includes the opponent's move animation.**
- What happens:
  - `StandardMode.start` stamps `position_ms` when `next_puzzle` returns. The trainer only plays the opponent's first move `OPPONENT_DELAY_MS = 500` ms later.
  - So the first move's think time is about 0.5 s longer than "from when the position appeared" (FR-5.9). A 2.6 s move isn't suggested as Rushed at the 3 s default.
  - Commit the line uses the whole entry time from the same stamp.
  - Name the idea is unaffected: its think time starts at Start solving.
- Evidence: `core/modes/standard.py` `start`, `web/src/views/TrainerView.tsx:22` and the `later(…, OPPONENT_DELAY_MS)` in `load`. This is from code reading; I can't pin it with the mock client.

**v0.6-B6 (minor, UX): the session bar's All time counts Danger spotting, while Stats doesn't.**
- What happens: after 16 Danger puzzles and one Name the idea solve, the session bar says "All time: 17 solved". Stats says "Puzzles played 1". Only the By mode tab explains why.
- This is consistent with the User Guide ("All time counts every attempt you've ever made"), but the two numbers disagree side by side.
- Evidence: `qa-v06-real/stats-reasons.png` (behind the modal) and `qa-v06-real/stats-mode-details.png`.

**v0.6-B7 (minor, cosmetic):**
- (a) The safe verdict reads "Stockfish rates it −0.4 for you (its best line: 0.0 (level))", with nested parentheses (`qa-v06-real/danger-verdict.png`).
- (b) The "By week" chart's y-axis ticks read 0, 3, 6, 12 (`qa-v06-stats-reasons.png`).

**v0.6-B8 (minor, docs):** the User Guide's Mistake reasons → Gotchas says "In a later version you'll also be able to be asked about your game mistakes only." CLAUDE.md says to document shipped features only.

Also noted:
- The backend allows Hint before tagging in Name the idea (a loss). After that, `set_tags` refuses ("already decided") and `on_move` refuses ("Name the idea first"), so only Show answer remains. The UI doesn't offer Hint before tagging, so you can't reach this state from the app.
- plans/v0.6.md still has "Docs in the same commits" unticked, though the docs are done.

---

## Tests added
- `tests/integration/test_qa_v06_edges.py` (22 functions, 27 cases):
  - **Danger spotting:** B1 equal-work (xfail); nothing reveals the truth before the call; Show answer before the call; moving on before the call; Rated forced off and never queued; refused with the depth ladder; an engine failure owes a safe one; a Danger win doesn't hide from Exclude solved; a Danger win doesn't clear Only my misses or SRS.
  - **Name the idea:** bad tag types (6); tagging twice / wrong mode; unknownPattern; rushed from Start solving.
  - **Reasons:** the exact 3 s edge in Danger; Off in Danger; a reason for an earlier puzzle; the practice-run prompt; misclick in by-mode / details / reason stats; the misclick warning at 2 of 8; the sync never reads `mistake_reasons`.
  - **Bugs:** B3 double search (xfail); B5 refutation side (xfail).
- `tests/e2e/test_qa_v06_ui.py` (14): B2 note dropped by key (xfail); digits typed in the note; 201-character note; practice asks nothing new; rapid 1–6; board locked before Start solving; at most 3 tags; S pressed twice → one call; Show answer before the call; S/U outside Danger; and screenshots of every v0.6 screen (light and dark) into `tests/e2e/artifacts/qa-v06-*.png`.
- `tests/smoke/test_qa_v06_real_app.py` (1): the real app with real Stockfish runs 14 Danger puzzles with refutations, then the B1 timing measure, a Danger miss → key 6 Misclick (session bar and DB), Name the idea tag → solve → result, and the Stats tabs. Screenshots go to `tests/e2e/artifacts/qa-v06-real/`.
- `tests/fulldb/test_qa_v06_fulldb.py` (3): Stats and tallies with 5,000 attempts carrying reasons; history-filter counts with Danger rows; Name the idea start + first puzzle.
- Test-only race fixes (no assertions weakened): `tests/smoke/test_qa_v03_real_app.py` now waits for "Not signed in", and `tests/smoke/test_qa_v05_real_app.py` accepts no replies line on one-move puzzles.

---

## Scope / architecture / security
- **Scope:**
  - No "Game Review only" option.
  - No game, Retry or habit-tag reason sources (`Source = "puzzle" | "danger"`).
  - No Explain or Coach code, and no dead UI found.
- **Layers:**
  - `core/` does no I/O.
  - No `datetime.now`, `time.time` or global `random` calls in `core/` or `services/`. `danger.py`'s `import random` is only for the `random.Random` type; it uses the injected `rng`.
  - `ReasonsService` and `MistakeReasonsRepo` are wired only in `app.py`.
  - `keyring` appears only in `adapters/secret_store.py`. There's no new HTTP.
- **Decisions 12–17:**
  - The Danger candidate uses the interactive `EngineService` (the same lock as the panel).
  - The new repos use `db.session()`.
  - `Api._reasons` is an underscore attribute, and the allowlist test passes.
  - No browser storage (grep empty; real app `localStorage + sessionStorage == 0`).
  - The tests use temp folders.
- **Migrations:** only the new `0005_reasons_modes.sql` (nullable columns, a new table and an index). No applied migration was edited.
- **Dependencies:** none added. The lockfile diffs are only the 0.6.0 version bump.
- **Security:**
  - No token or key patterns in the diff, the QA tests or the artifacts. The only hit is the hook's own test string in `.claude/hooks`.
  - No fixtures changed.
  - Notes are stored as plain text, never logged (the new log lines carry only a puzzle ref and an error code) and rendered by React (escaped).
  - The CDP port is set only by the smoke harness and refused without `--dev` (`app.py:99`).

## Docs
- `check_docs.py --strict`: 0 errors, 0 warnings. No `TODO(v0.6)` left.
- **User Guide sections followed against the mock and the real app.**
  - **Name the idea first:** steps 1–3, "Start solving", the result line and "Missed:" all match.
  - **Danger spotting:** steps 1–3, S/U, "turns round", "How it's scored", and the gotchas (no Hint, Show answer, Rated greyed, no depth ladder) all match. "A puzzle can take a moment to appear" is true, and is the B1 tell.
  - **Training settings:** the labels "Ask after a failed puzzle" Always/Off and "Suggest Rushed under (seconds)" match.
  - **Mistake reasons:** the table, the steps, "Saved", Skip, "Add a note" / "Save note" and the misclick text all match. See B8.
  - **Stats** (mode details, Why you missed, the misclick note) and **Keyboard shortcuts** (S / U, 1–6) match.
- CHANGELOG `[Unreleased]` covers every user-visible *Done when* item (both modes, reasons, misclicks, Stats).
- The privacy section says the v0.6 features send nothing, and that Danger spotting never syncs. That matches the DB (`local`) and the code (the sync never reads reasons).
- The README status says v0.6 "is next". That's acceptable until sign-off.

## Visual check
I looked at every screenshot.
- **Mock** (`tests/e2e/artifacts/qa-v06-*.png`): Name the idea tagging and the miss with chips; the Danger call (light and dark), the safe verdict, the refute, a wrong refutation, and the answer before the call; Settings → Training; Stats → mode details and Why you missed.
- **Real app** (`qa-v06-real/*.png`): the mixer in Danger, the call, the refute, the verdict, the reason chips, the misclick session bar, Name the idea tagging and result, and both Stats tabs.

No clipped text or broken layout apart from B7. The vertical Modes control is compact but readable.

## For Adam's manual test
- **Run as written, on your dev folder:** `uv run python -m weaksquare --dev` migrated the dev `user.db` from schema 4 to 5 (backup `backups\user-4-20261103-152106.db`). QA read no credential.
- **B1, by feel:** in 20 Danger puzzles, see whether you can tell safe from blunder by the pause before each appears. Try it with a longer think time too.
- **Roughly half safe:** the real app gave 9, 5, 8, 6 and 7 safe out of 14 across my 5 runs; the integration test gives 5–15 of 20.
- **Reason suggestions with real timing:** a fast wrong move should suggest Rushed. Note that the 0.5 s opponent animation counts (B4).
- **The weekly trend over real weeks:** QA used a fixed clock and the mock's data only.
- **A misclick on a signed-in account:** check that the loss still appears in your Lichess puzzle history. QA verified this with the fake Lichess only.
