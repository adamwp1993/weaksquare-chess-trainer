# QA report: v0.12 (Training plan + journal), round 1

Branch `v0.12` at `796c726`. Run on 2026-11-05 by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `-m live` was **not** run: nobody asked for it, so `tests/live/test_coach_plan_live.py` was read only. No real credentials were read or used.

## Verdict: **FAIL** (4 major, 11 minor; no blocker)

Most of v0.12 works, through the real bridge and in the real window:
- Every task type ticks from real events.
- A puzzle task leaves every setting and preset byte-identical.
- The daily log matches Stats.
- Nothing private reached the LLM in any prompt I checked.
- Saved answers followed the rules.
- AI plan validation survived 250 garbage answers.
- All automated suites are green apart from one flake and the xfails below.

The gate (minor issues only) isn't met, because of these four:
- **B1 (major):** the carry-over limit of one day's worth holds only on the first read. Each later read of the plan carries more, so all of a day's unfinished tasks arrive, and they pile up over missed days.
- **B2 (major):** a whole-game weakness whose group fell below 5 games is marked **Gone** and called **better**, and the AI is told so. This breaks the FR-10.73 guard and "never inflates progress".
- **B3 (major):** the journal's link opens the position **before** the move the note is on. On a first-move note it opens the start position. This breaks the Done-when item "links back to the position".
- **B4 (major):** the Journal tab has **no game filter** (FR-10.70), and its composer can't tag a game or a plan day (FR-10.67). If you'd rather drop this from the requirements, it becomes a doc change.

---

## Evidence: commands run

Git Bash, one suite at a time. `npm.cmd` as written.

| Command (as in the Developer Guide) | Result |
|---|---|
| `uv run pytest` before my tests | **2219 passed, 1 skipped** (371 s), rc 0 |
| `uv run pytest` with my tests | 2726 passed, 1 skipped, 13 xfailed, **2 failed** (411 s). Both failures were faults in my new tests (a wrong attribute; a wrong cap assumption), now fixed. Rerun of my three files alone: **509 passed, 13 xfailed**. I did not repeat the whole command after that fix |
| `uv run pytest -m e2e` | 368 passed, 3 xfailed, **1 failed** (845 s). The failure was a wrong selector in my new test, now fixed. Rerun of `test_qa_v012_ui.py` alone: **13 passed, 3 xfailed** |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0; 36 passed, 1 skipped, **1 failed** (533 s). The failure is the flake described below |
| `uv run pytest -m engine` | **19 passed** (70 s) |
| `uv run pytest -m fulldb` | dev `puzzles.db` imported: **73 passed, 3 xfailed** (555 s) |
| `uv run pytest -m docs_screenshots` | **46 passed** (131 s). Two earlier screenshots changed (`import-puzzles.png`, `stats-reasons.png`). I restored the committed files without comparing pixels (no image library in the venv), so I can't say whether the change matters |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 420 files formatted |
| `uv run mypy src` | Success: 132 source files |
| `npm.cmd --prefix web run typecheck` / `lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | Hardcoded secrets Passed; keyring only in secret_store.py Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.12]`, both rc 0 |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, "VITE v8.3.5 mock ready" |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete" |
| Run the app (`--dev`) | Covered by the smoke harness with a temp data folder, not against the dev folder, so its `user.db` isn't migrated |
| `--dev-server`, `fetch_puzzle_db.py --dev`, `record_db_update.py` | **Not run:** unchanged in v0.12; the last two need the network |
| `set_test_token.py` (both rows), `-m live` (all rows) | **Not run:** Adam's (credentials) |

No human-facing command uses a `.ps1` script, bare `npm`/`npx` or venv activation.

**Flake, reported with both results:** `tests/smoke/test_qa_v04_rc2_real_app.py::test_try_again_in_the_real_app`
- **In the full smoke run: failed.** The test's log check found `ERROR pywebview: Error occurred in script`, from `evaluate_js`.
- **Alone: 1 passed** (16 s).
- It's an older test, and the error comes from pywebview's script call rather than v0.12 code. I don't count it as a v0.12 bug.

---

## Traceability

### Done when

| Item | Method | Result | Evidence |
|---|---|---|---|
| The plan fits the minutes and days and weights time by score | unit + QA | PASS | `test_plan.py`; QA `test_qa_every_plan_fits_the_minutes_and_has_two_to_four_known_tasks` (150 seeds), `test_qa_training_dates_stay_on_picked_days…`, `test_qa_plan_settings_at_both_bounds_make_a_plan`. See "Observations" on weakness-poor reports |
| Every task type opens its screen | integration + e2e + QA + smoke | PASS | `test_each_start_action_crosses_the_bridge`; QA `test_qa_every_task_of_a_real_plan_from_a_real_report_can_start`, `test_qa_a_task_of_puzzles_from_your_games_starts_and_ticks`, real-app `test_qa_v012_the_main_flow_in_the_real_app` |
| A puzzle task never changes your filters or presets | QA through the bridge + smoke | PASS | QA `test_qa_every_session_from_a_task_leaves_every_setting_and_preset_byte_identical` (four modes and a lesson drill, the whole `settings` and `presets` tables). In the real app, the two tables are unchanged after really playing a task, a review and a reflection |
| Each task type ticks from the real events | QA through the bridge + smoke | PASS | `submit_move`, `retry_move`, `mark_review_ply`, `add_journal_entry`, `open_plan_lesson`: `test_qa_a_puzzle_task_ticks_from_really_solved_puzzles…`, `test_qa_retry_ticks_from_real_retry_moves_and_a_review_from_real_visits`, `test_qa_a_reflection_and_a_lesson_tick_from_the_real_calls`. See B12 for one edge |
| Manual tick, untick, skip, swap | integration + e2e + QA | PASS (B11 on repeated swaps) | `test_tick_untick_skip…`, `test_skip_and_swap`, QA `test_qa_a_hand_choice_always_wins_over_a_later_real_event` |
| A tick in the Today card shows in the Plan tab and back | e2e + smoke | PASS | `test_a_tick_in_the_today_card_shows_in_the_plan_tab_and_back`; real app: hand tick, then the totals line |
| Carry-over follows the setting | QA with clock and dev offset + smoke | **FAIL (B1)** | Passes: on, off, rest day, once per task, away for days, done and skipped never carry, progress kept, dev offset. Fails: the one-day limit, `test_qa_reading_the_plan_again_never_carries_more_than_a_days_worth` |
| AI plan validation; a broken plan falls back; progress is aggregates only | unit + QA | PASS | `test_qa_any_ai_answer_gives_a_complete_plan_in_the_asked_shape` (250 seeds), `test_qa_an_ai_plan_with_invalid_tasks_is_filled_and_can_be_used`, `test_qa_a_broken_plan_falls_back_to_the_free_plan_whole` (7 shapes), `test_qa_plan_progress_in_the_prompt_is_aggregates_only` |
| The daily log is computed from stored data and matches Stats | QA + smoke | PASS (B6) | `test_qa_the_daily_log_matches_stats_for_a_mixed_day_with_real_attempts` (with a misclick and Danger spotting), `test_qa_the_log_files_an_attempt_on_your_local_day_not_the_utc_one`; real-app `get_journal` against `get_stats`. The Stats part matches; B6 is the plan-task count |
| A reflection appears in the game and the journal and links back to the position | QA + e2e + smoke | **FAIL (B3)** | It appears in both (`test_qa_a_reflection_shows_in_game_and_journal…`, real-app marker). Link: `test_qa_a_notes_link_opens_the_very_move_the_note_is_on` |
| Journal text only with the option; preview exactly what's sent; no platform ids or URLs | QA + smoke | PASS (B10, reachable only by a direct bridge call) | `test_qa_journal_text_never_goes_without_the_option_even_from_a_task`, `test_qa_the_preview_is_exactly_what_is_sent_in_scope_order_cut_and_labels`, `test_qa_no_name_date_url_id_clock_or_comment_reaches_the_llm_with_plan_trend_and_journal`; real-app preview |
| Since last report: rates, New and Gone, guards, settings, players, aggregates | unit + QA + smoke | **FAIL (B2)** | Passes: `test_qa_since_last_report_from_real_runs_matches_the_two_stored_reports`, `test_qa_the_guard_at_its_edges`, `test_qa_the_trend_part_has_aggregates_only_and_nothing_from_another_player`, `test_qa_a_trend_claim_can_never_be_better_than_the_numbers`, `test_qa_a_five_report_series…`. Fails: `test_qa_a_whole_game_weakness_whose_group_fell_below_5_games_is_not_called_better` |
| Every option has a tooltip | e2e + QA | PASS | `test_v012_tooltips.py`; QA adds Stats, all five modes before and during a session, the plan preview and confirm. A source scan found nothing else unexplained |

### Requirements

| ID | Method | Result | Evidence |
|---|---|---|---|
| FR-8.14 | QA through the bridge | PASS | `test_qa_the_new_limits_at_each_detail_and_reasoning_reach_the_request`: 7,500, 10,000, 15,000, 40,000 |
| FR-8.16 | QA end to end | PASS (B10) | A PGN with names, Elo, Site URL, dates, clock and comment on 12 games, a plan whose titles carry the opponent's name, and a journal with URLs: none reaches `user` or `system` |
| FR-10.61 | unit + QA | PASS | Bounds refused (`test_qa_plan_settings_are_refused_outside_their_bounds`, 11 cases), start day. The fixed-weakness share is v1.0 |
| FR-10.62 | unit + QA | PASS | As above |
| FR-10.63 | QA + smoke | PASS | As above |
| FR-10.64 | QA + smoke | **FAIL (B1)**; also B11, B12 | As above |
| FR-10.65 | e2e + smoke | PASS (B5, B9) | Tabs, today opened, confirm, history |
| FR-10.66 | QA | PASS | `test_qa_a_saved_answer_is_shown_free_and_keeps_the_shape_it_was_made_with`, `test_qa_a_v011_answer_is_not_reused_for_you_but_is_for_another_player`, `test_qa_another_players_report_never_sends_your_journal_or_your_plan`. **A real provider's acceptance of the schema is manual only** |
| FR-10.67 | QA + e2e | **FAIL (B4)**; also B8 | Limits and edit work (`test_qa_an_entry_of_exactly_the_limit…`); a game or day tag can't be chosen in the composer |
| FR-10.68 | QA + smoke | PASS (B6) | `test_qa_the_daily_log_counts_each_fact_on_its_day`; real analysis gives `games_analyzed` 1 |
| FR-10.69 | QA + e2e + smoke | **FAIL (B3)** | Marker and list work; the journal's link is off by one |
| FR-10.70 | QA + e2e | **FAIL (B4)**; also B7 | No game filter in the UI (the bridge has one). Search treats wildcards literally |
| FR-10.71 | QA + smoke | PASS | Scope, the newest 30, the 1,000-character cut, URLs removed before the cut, outside game has no label, saved-answer hash (`test_qa_saved_answers_follow_the_journal_text_in_scope_not_anything_else`); no journal copy in `coach_ai_runs` or `llm_usage` |
| FR-10.72 | e2e + QA | PASS | As above |
| FR-10.73 | unit + QA + smoke | **FAIL (B2)** | As above |
| Plan decisions (`plans/v0.12.md`) | QA | PASS | Report read stays fast at 100,000 attempts: report 0.70 s, Today card 0.001 s, journal 0.97 s (`test_qa_opening_a_report_and_the_today_card_stay_fast_with_a_big_history`, with the fixture puzzle DB). Item 13 is rightly unticked |

---

## Bugs

### v0.12-B1 (major): the carry-over limit is broken by reading the plan again
**Steps:** a plan with every weekday and 20 minutes a day, where day 1 has three 10-minute tasks. Do none. Next day, open the plan, then read it again.
**Expected:** at most 20 minutes carried (FR-10.64: "at most one day's worth").
**Actual:** 2 tasks on the first read, the third on the next. `to_carry` leaves out what's already been copied and starts counting the limit from zero each time, so each read carries another day's worth. The Today card and Plan tab read it after every change, so the limit does nothing in practice. In a default plan the overflow starts on the second missed day in a row: that day already holds its own tasks plus the copies, and the pile keeps growing day by day.
**Evidence:** `test_qa_reading_the_plan_again_never_carries_more_than_a_days_worth` (xfail); `core/plan.py` `to_carry`, called from `services/plan.py` `_sync`. The builder's test reads once.

### v0.12-B2 (major): a weakness whose group fell below 5 games is called better
**Steps:** an older report with `opening:Sicilian` as a weakness (8 games in that opening), and a newer one with 20 new games, only 2 of them Sicilians. Open the newer report.
**Expected:** *not enough new games yet* (FR-10.73: "at least 5 games in that group").
**Actual:** `flag=gone, then=6.0, now=0.0, verdict=better`. The guard looks at the report's total games, and "gone" scores as a rate of 0. A weakness that only dropped below the group guard isn't improved. The same value goes to the AI as `change`, so an "improved" statement passes `validate_trend`. It applies to every whole-game group (opening, endgame, conversion, low clock, late castling).
**Evidence:** `test_qa_a_whole_game_weakness_whose_group_fell_below_5_games_is_not_called_better` (xfail); `core/report_compare.py` `_weakness_rows`.

### v0.12-B3 (major): the journal's link opens the position before the noted move
**Steps:** in Game Review, go to a move and **Add a note** with **On this move**. Open Coach → Journal and click the entry's game link.
**Expected:** Game Review on that move, as the links under **Your notes** do.
**Actual:** one move earlier. `JournalTab` passes the 0-based `ply` as `initialPly`, which means "moves played". `GameNotes` correctly uses `ply + 1`. In the real app, a note on `1. a3` (ply 0) opened the start position with no move highlighted (`note_ply: 0, journal_link_shows: null` in `tests/e2e/artifacts/qa-v012-real-facts.json`). Opening it this way also marks the wrong move as visited.
**Evidence:** `test_qa_a_notes_link_opens_the_very_move_the_note_is_on` (xfail). The builder's test only checks that Review opens.

### v0.12-B4 (major): no game filter in the Journal tab; no game or plan-day tag in the composer
**Steps:** open Coach → Journal and look at the filters and the composer.
**Expected:** FR-10.70 "filters (weakness, game, type, date range)"; FR-10.67 "optional tags: a weakness, a game (and ply), a plan day".
**Actual:** Show, Weakness, From, To and Search only. The bridge and the mock accept `game_id`, but nothing in the UI sets it. A note can get a game only from Game Review, and a plan day only from a reflection task. The User Guide describes what's built, so it doesn't reveal the gap.
**Evidence:** `test_qa_the_journal_can_be_filtered_by_game` (xfail); `JournalTab.tsx`.

### v0.12-B5 (minor): minutes spent double when a puzzle task is carried
**Steps:** spend 10 minutes on a puzzle task without finishing it. Next training day, read the plan.
**Expected:** about 10 min. **Actual:** 20: the copy inherits the original's time, and both are added up. It's also in the plan progress sent to the AI.
**Evidence:** `test_qa_minutes_spent_do_not_double_when_a_puzzle_task_is_carried` (xfail).

### v0.12-B6 (minor): a task ticked by hand isn't in the daily log
**Steps:** tick a task by hand and read that day's log.
**Expected:** counted under **Plan tasks done**. **Actual:** not counted (`done_at` is set only by what the app saw). In the real run the plan said 5 done and the log said 4. A task the app saw and you then unticked still counts.
**Evidence:** `test_qa_the_daily_log_counts_a_task_ticked_by_hand` (xfail).

### v0.12-B7 (minor): search and filters cover only the newest 30 days at first; "Show older days" never goes away
**Steps:** write a note, come back 60 days later, and search for a word in it.
**Expected:** it's found. **Actual:** *Nothing here for these days and filters.* You have to press **Show older days**, possibly several times. Without a **From** date, that button shows forever, even on an empty journal (`older` is always true).
**Evidence:** `test_qa_search_finds_an_old_entry` (xfail); `services/journal.py` `timeline`.

### v0.12-B8 (minor): `add_journal_entry` doesn't check what an entry links to (bridge only; the UI doesn't send these values)
- A ply past the end of the game is stored (`test_qa_a_note_on_a_move_past_the_end_of_the_game_is_refused`).
- A task or day that doesn't exist crashes with "Something went wrong" instead of a refusal (`IntegrityError`; `test_qa_bad_links_on_a_journal_entry_get_a_plain_refusal`).
- A future `entry_date` is stored but never shown (`test_qa_an_entry_dated_tomorrow_is_not_lost`).

All xfail.

### v0.12-B9 (minor): an ended plan's completion still changes
**Steps:** replace a plan that has a review task on a game, then review that game.
**Expected:** the old plan stays as it was when replaced (FR-10.65). **Actual:** its task turns done, because `_facts` has no upper time limit for `retry_attempts` or `review_passes`.
**Evidence:** `test_qa_an_old_plans_completion_stops_when_it_is_replaced` (xfail).

### v0.12-B10 (minor): a journal tag can carry a URL to the LLM (bridge only; the UI offers report keys)
**Steps:** `add_journal_entry({"text": "plain", "weakness_key": "https://evil.example/u"})`, then read the preview.
**Expected:** refused or cleaned (FR-8.16). **Actual:** it's stored, previewed and sent unchanged. `weakness_key` is checked only for type and length, and it isn't passed through `strip_urls`.
**Evidence:** `test_qa_a_weakness_tag_can_not_carry_a_url_to_the_llm` (xfail).

### v0.12-B11 (minor): Swap goes back and forth between two tasks
**Steps:** press **Swap** three times on one task of a report with several options.
**Expected:** the next task each time (FR-10.64). **Actual:** A, B, A, B. `swap_for` always restarts from the first option, so a third is never reached.
**Evidence:** `test_qa_swap_keeps_moving_to_the_next_task` (xfail).

### v0.12-B12 (minor): moves visited before the plan count towards its review task
**Steps:** visit a game's key moments but not its last move. A week later, start a plan with a review of that game and visit only the last move.
**Expected:** left, since a Retry from before the plan doesn't count either. **Actual:** done: `ReviewPassesRepo.start` takes over the old open pass.
**Evidence:** `test_qa_a_review_task_needs_visits_since_the_plan_began` (xfail).

### v0.12-B13 (minor): Preview the plan crashes with no puzzle database
**Steps:** with no `puzzles.db` but a report (a games-only Coach run needs no puzzles), press **Preview the plan**.
**Expected:** a plain message. **Actual:** *Something went wrong* (`no such table: pz.theme_bits`). The Today card's read is fine.
**Evidence:** `test_qa_the_plan_works_without_a_puzzle_database` (xfail).

### v0.12-B14 (minor): one long word makes the whole page scroll sideways
**Steps:** save a journal note of 5,000 characters with no spaces (a long link is the realistic case, at a smaller scale).
**Expected:** it wraps. **Actual:** the page scrolls sideways by 32,619 px at that length. `whiteSpace: pre-wrap` with no word break. The Game Review notes use the same styling, but I didn't test them.
**Evidence:** `test_qa_the_longest_entry_of_one_unbroken_word_stays_inside_its_box` (xfail); `tests/e2e/artifacts/qa-v012-journal-long-entry.png`.

### v0.12-B15 (minor, docs)
- `tests/live/test_coach_plan_live.py` isn't in the Developer Guide's Commands table. The **Live tests** row says what `uv run pytest -m live` spends, but not this extra paid Coach call (run cap $0.05, budget $0.10).
- REQUIREMENTS §4.3 `plan_tasks` omits the `title` and `removed` columns that migration 0011 has.
- The journal composer's counter reads `5000 / 5,000` (one number has a comma, the other doesn't).
- That live test's docstring says it checks "no player name from the PGN", but it only looks for the tag text `[White`, `[Black` and `[Site`, never for the names themselves.

---

## Tests added

All of these were run. Open bugs are `xfail(strict=True)` with their ID.
- `tests/integration/test_qa_v012_plan.py`: tasks from real reports, the Mixer untouched, real ticks, carry-over day by day and by dev offset, swap, history, bounds.
- `tests/integration/test_qa_v012_journal_ai.py`: FR-8.16 end to end, progress and trend parts, journal scope and preview, limits, saved answers, invalid plans, Since last report from real runs, the journal, the daily log against Stats, local-day boundary, cap and speed.
- `tests/unit/test_qa_v012.py`: plan and AI-plan invariants over seeded inputs, date rules, guard edges, trend claims, the 5-report series.
- `tests/e2e/test_qa_v012_ui.py`: the journal's link, game filter, HTML stays text, long words, limits, tooltips on further screens, screenshots, a narrow window.
- `tests/smoke/test_qa_v012_real_app.py`: `test_qa_v012_the_main_flow_in_the_real_app`, the whole flow in the real window including a day forward and a restart.

## Scope, architecture, security

- **Scope:** nothing from a later version found: no statuses, checkpoints, Progress page or charts. The share for fixed weaknesses waits for v1.0, as the plan says.
- **Layers:** the new `core/` modules do no I/O. No `datetime.now()`, `time.time()` or global `random` in `core/` or `services/`. `keyring` is imported only in `secret_store.py` (pre-commit hook passed). No browser storage in `web/src`. The bridge allowlist test passed. Thread rule: the AI job's plan work goes through the same `Database` sessions; nothing new shares a connection that I found.
- **Migrations:** one new file, `0011_plan_journal.sql`; none edited.
- **Dependencies:** none added. `uv.lock` and `package-lock.json` differ only by the app's version.
- **Security:** pre-commit's secret scan passed. The only key-like patterns my scan hit in tests are `lip_FAKE…`; the other hit is `apply_transform` in vendored code, a false match. The new fixtures use placeholder names. A run stores a journal hash, not the text (tested). The CDP port is set only by the smoke harness.
- **Cost (computed from the seeded prices, assuming about 20,000 input tokens, against the default $0.50 cap; only Fable at High was executed):** blocked at Confirm, never silently:
  - Opus 5.5: High
  - Fable 5.1: High and Medium, and Low too at this prompt size
  - GPT-5.5: High and Medium
  - GPT-5.4: Detailed at High

  The CHANGELOG mentions only "a costly model at High", so this list is for the handoff that the plan asks for. Smaller prompts get through more often.

## Docs findings

- `check_docs --strict`: 0 errors, 0 warnings.
- **Developer Guide:** see the table above. B15 for the missing row.
- **User Guide:** *Since last report*, *AI coaching*, *Include my journal*, *Your training plan*, *Your training journal* and *Finding out what an option does* were followed through the real-app flow and the e2e tests. Labels, order and defaults match, except: *Since last report* says "at least 5 games", which is what the code does but not FR-10.73's "in that group" (B2); "the journal entry links back to that position" (B3).
- **CHANGELOG `[Unreleased]`** covers every user-visible Done-when item, including "with filters and search" (B4 is a narrower gap).
- **Privacy section** says what the plan, trend and journal send, and it matches the prompts I captured.
- **Screenshots:** I looked at the Today card, Plan tab, preview, Journal, Review notes, Since last report and the journal preview, at normal width, plus Today, Plan and Journal at 900 px. No breakage, apart from B14. Files are in `tests/e2e/artifacts/qa-v012-*.png`. One real-app capture shows a modal mid-animation, which is a capture artifact.

## Observations (not filed as bugs)

- **Weakness-poor reports give mostly general puzzles.** A report with one whole-game weakness gave 101 "any theme" tasks out of 112 at 4 weeks, 7 days, 120 minutes, because games and lessons are used once per plan. It meets the text of FR-10.61, but "the top weaknesses get the most time" isn't what you'd see. Worth a look in the manual test.
- **Puzzles from your games appear only if you have at least the task's count of them.** With fewer, the task becomes general puzzles. That's by design (plan item 4), but on a young library this task type won't show.
- **A report with no game dates** (a PGN without a Date header) has no first day, so only entries tagged to its games go. The preview shows this correctly.
- **Ticking Include my journal with nothing to send** is a separate saved answer, so the identical prompt is billed again.
- **The preview shows the move's SAN** (`G1 · 1. a3`), while the request sends the label and the ply number. It's harmless, but it isn't quite "exactly what is sent".
- **Next clicked before Show answer returns is ignored**, and the answer can stay on screen until you click again. I hit this only with the test's instant clicks, and no attempt data was lost.

## For Adam's manual test

- **The live test, which I only read:** `uv run pytest -m live tests/live/test_coach_plan_live.py`. It makes one real Coach call (cap $0.05) and is the only check that a real provider accepts the nested plan schema. It also checks the plan's shape and that the AI's plan wasn't simply replaced by the free one.
- **The quality of a real AI plan and of its trend statements**, compared with the free plan: no test can judge this.
- **ROADMAP's manual flow over real days:** 2 weeks × 5 days × 20 minutes with real games; "after the two days" uses wall-clock time here only through the dev offset. Check B1's pile-up by missing two days.
- **Real lesson links** from a lesson task: the smoke test avoids opening your browser. Only the fake desktop proved that they open and tick.
- **Tooltip wording**, read as a user, and whether the Today card takes too much space above the Mixer with 4 tasks.
- **Whether you want B4** as written, or would rather change the requirement.
