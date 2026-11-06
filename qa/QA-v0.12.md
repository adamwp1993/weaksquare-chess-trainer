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

---

# Round 2 (re-verification), 2026-11-05

Branch `v0.12` at `5fcbe6b`, run by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `-m live` was **not** run: nobody asked for it. No real credentials were read or used.

## Verdict: **FAIL** (1 major, 14 minor, no blocker)

All of B1 to B15 pass their re-test, and two have a gap filed as a new bug (B2 as B16, B13 as B29). The gate (minor issues only) isn't met because of one new major bug:
- **B16 (major):** a whole-game weakness that leaves the top list while its group still has 5 or more games is scored as rate 0 and called **better**, and the AI is told so. B2's fix closed the path for small groups but not this one. From real measures: the same low-clock mistake rate in both reports gives `then 4.0, now 0.0, better`, because mistakes elsewhere rose.

Four of the new minor bugs come from the round 1 fixes themselves: B17 and B18 (from B7), B20 (from B12) and B21 (from B6).

## Re-test of B1 to B15

| Bug | Result | Evidence and what I checked |
|---|---|---|
| B1 carry-over limit | **Fixed** | Round 1's test, plus 3 reads a day over 4 missed days: 20 minutes carried each day, no pile-up (`test_qa2_the_limit_holds_every_day_of_a_run_of_missed_days`). Done or skipped copies still use up the limit and don't carry again. Swapping a copy lets nothing extra in. |
| B2 group guard | **Fixed for what was reported; gap filed as B16** | All 5 whole-game kinds (opening, endgame, conversion, low clock, late castling) at group sizes (8,2), (2,8), (4,4), (8,0), (5,4), (4,5), in and out of the list: `not_enough`. (5,5) gets a verdict. Old reports with no measures on either side, and malformed `measures`: `not_enough`, no crash. `validate_trend` drops an "improved" claim. A real report has the groups the guard reads. |
| B3 journal link | **Fixed** | Real app, notes on ply 0 and ply 4: the link opens that very move highlighted. The main flow's facts file says `note_ply: 0, journal_link_shows: move-0`. |
| B4 game filter and tags | **Fixed** (see B24, B27, B28) | Real app: Tag a game and Tag a plan day stored `game_id` and `plan_day_id`; the Game filter narrows the list, hides the log and clears. Round 1's own test only looks for the label, so `test_qa2_the_game_filter_really_filters_and_hides_the_log` now covers the behaviour. |
| B5 doubled minutes | **Fixed** | Round 1's test (see B23 for the same total after a Swap). |
| B6 hand ticks in the log | **Fixed** (see B21) | Real app: tick +1, untick back, read from the real `get_journal`. Through the bridge: a late tick files on its own day, an app-seen task unticked and re-ticked counts once, a copy counts once, a swapped-away tick is gone. |
| B7 search and `older` | **Fixed** (see B17, B18, B19) | Empty journal: `older` false. Paging reaches a 100-day-old note and stops. `older` stops at From. From after To is empty. Combined filters are right. |
| B8 entry links | **Fixed** | Past-the-end and negative ply refused. Last move accepted. Missing day or task gets a plain refusal. A future date is refused. |
| B9 ended plan | **Fixed** | A session still running across the replacement carries on without error; its later attempts don't count. What happened before the end (attempt, review, reflection) still counts 2 days later. Hand changes, Start and Swap on the old plan are refused. A note saved later doesn't tick it. |
| B10 tag with a URL | **Fixed** | 11 bad keys refused on add and on edit. 25 real keys accepted, including `St. George Defense`, `King's Indian Attack`, `Réti Opening`. Every key from a real report and a real plan is accepted. |
| B11 Swap | **Fixed** (see B22) | Full DB: every slot reaches 3 or more different tasks with no A, B, A. |
| B12 review since the plan | **Fixed, with a regression** (B20) | Round 1's test passes. Resuming a task's own pass keeps its visits. |
| B13 no puzzle DB | **Fixed for Preview and Start** (see B29) | Bridge and real window: preview, create, Today, Swap, skip, tick, AI run all work; a puzzle task's Start gives a plain "Import the puzzle database first". **Correction to round 1:** the real window with no DB shows only *Get the puzzle database*, with no nav and no Coach, so this is reachable only through the bridge. |
| B14 long word | **Fixed** (see B25) | Real app, 5,000 characters in one word: no sideways scroll. Also fine in the edit box, Game Review's notes and at 900 px. |
| B15 docs | **Fixed** (see B30) | The Developer Guide row is there, §4.3 lists the columns, the counter reads `5,000 / 5,000`, and the live test now looks for the fixture's names. |

**The builder's edits to QA's tests don't weaken them.** Each moved date is there because future dates are now refused; the assertions are unchanged. The moved dates are the `clock.advance` additions and `entry_date` in `test_qa_a_weakness_tag_can_not_carry_a_url_to_the_llm`. That test now passes through its refusal branch, so `test_qa2_a_tag_can_not_be_a_web_address_on_add_or_on_edit` covers it directly. `ply=12` became `ply=2` in `test_plan_ai.py` because a ply past the end is now refused; it still proves the label is 1-based. The counter text is stricter than before. `test_0012_adds_when_you_ticked_a_task_by_hand` only reads a fresh database, so the migration tests below cover the upgrade paths.

## Regressions hunted, and clean

- **`user/0012`:** a v0.11 database (at 0010) and one at 0011 with a plan keep their rows and hand choices, and migrating again changes nothing. The real app opens the 0011 one. Hand ticks made at 0011 have no time, so they aren't in the log; they don't crash, and v0.12 isn't released, so only a dev database has any.
- **FR-8.16, what the tags send:** with a game tag inside and outside the report and a plan-day tag, the prompt's lines hold only `note`, `kind`, `game` (`G5`, inside the report only), `ply` and `weakness`. No plan day or task, game id, player name, URL or date. The labels with names stay in the UI.
- **Tooltip walk:** it covers the three new controls (`journal.tagGame`, `journal.tagDay`, `journal.filterGame`), and each opens with its own text on hover.
- **Game filter after deleting its last entry:** the box keeps its value and can still be cleared.
- **Speed:** the 4-week, 7-day preview takes 0.36 s on the full DB with the puzzle check.
- **Layout:** composer and filters, real app and mock, at normal width and at 900 px, are fine apart from B28's empty `()`.

## New bugs

### v0.12-B16 (major): a weakness out of the top list with its group still at 5 or more games is called better
**Steps:** two reports of 5 new games each, both with 5 games on a low clock. The first has `time:low_clock` as a weakness. In the second, low-clock mistakes are the same (8.0 per 100 moves in both) but mistakes elsewhere rose, so the weakness's gate (low-clock rate above the rest) closes.
**Expected:** not called better (FR-10.73). The report's own `low_clock` measure says the rate is unchanged.
**Actual:** `flag=gone, then=4.0, now=0.0, verdict=better`, and the same goes to the AI as `change`, so an "improved" statement passes `validate_trend`. `_weakness_rows` uses `0.0` for any key missing from `rates()`, but `whole_game` is both gated and capped at 10 (`game_weaknesses`). So missing doesn't mean zero. The same happens to `habit:castledLate` when its gate closes, and to any whole-game weakness pushed past the cap of 10.
**Evidence:** `test_qa2_low_clock_mistakes_unchanged_but_gone_from_the_list_are_not_better`, `test_qa2_a_group_with_5_games_gone_from_the_list_because_others_are_worse_is_not_better` (xfail).

### v0.12-B17 (minor, regression from B7): Show Daily log with a search or filter lists entries
**Steps:** Journal, **Show** only **Daily log**, then type a word in Search, or pick a Weakness or Game.
**Expected:** nothing, since the log has no words or tags. **Actual:** notes and reflections you didn't pick. `entry_kinds` is empty, and `search` treats an empty list as "all kinds". The window path had a guard for this; the new path doesn't.
**Evidence:** `test_qa2_show_daily_log_with_a_search_or_filter_lists_no_entries` (3 cases, xfail).

### v0.12-B18 (minor, regression from B7): search and Notes or Reflections stop at the newest 500
**Steps:** have 501 matching entries, search, or Show only Notes.
**Expected:** all of them, or a way to see more. The User Guide says Search finds words "however old". **Actual:** 500, with `older` false. `search` has `limit=500`, and this path no longer pages.
**Evidence:** `test_qa2_search_reaches_every_entry_past_500` (xfail).

### v0.12-B19 (minor): two edges of the timeline window
- **A To date after today shows nothing.** Set **To** 200 days ahead: *Nothing here*, because the window starts from that date. It should stop at today. `test_qa2_a_to_date_after_today_still_shows_today` (xfail).
- **`older` compares UTC dates with local days.** West of UTC, an evening's activity has the next day's UTC date. If it's your oldest activity and the window starts on that UTC date, `older` is false and that local day can't be reached. This is rare. `test_qa2_older_is_true_for_a_local_day_the_utc_date_hides` (xfail).

### v0.12-B20 (minor, regression from B12): review passes lose or block real visits
- **A pass left open before the plan blocks the tick.** Look at one move of a game. A week later, start a plan with a review of that game, and visit every key moment and the final move from **My games** rather than Start. **Expected:** done (FR-10.64). **Actual:** left: `visit` adds to the old open pass, and `completed_games` needs a pass begun since the plan. Start works, and so does a hand tick. `test_qa2_a_whole_review_since_the_plan_began_ticks_with_an_old_pass_left_open` (xfail).
- **Start on a carried review task drops what you visited.** Visit the key moments from the task, miss the day, press Start on the copy, and visit the final move. **Expected:** done. **Actual:** left: the copy has another task id, so a new pass starts. `test_qa2_a_carried_review_task_keeps_the_moves_you_already_visited` (xfail).

### v0.12-B21 (minor, from B6): a hand tick moves to a later day in the log
**Steps:** tick a task by hand on day 1. On day 2 the app sees it done (here, a note saved from the task).
**Expected:** it stays on day 1, as `plan_tasks_done`'s docstring says ("on the day it first was"). **Actual:** day 1 drops by one and day 2 gains one: `COALESCE(done_at, manual_at)` prefers the later time.
**Evidence:** `test_qa2_a_hand_tick_stays_on_its_day_when_the_app_sees_it_done_later` (xfail).

### v0.12-B22 (minor): Swap's dead ends
- **Full DB:** after the options run out, each Swap gives the same reflection again ("What's the one thing to remember from today?"), so it appears to do nothing. Two slots can hold that same reflection on one day, though `swap_for` says "never one already on the day". The fallback isn't checked.
- **Fixture DB:** a general task swapped 12 times stays `9 puzzles: any theme`, because `fit_task` turns each option back into the same general task after the title check. The options are too thin here; on the full DB I saw this only as the reflection case above.
- **Evidence:** `test_qa2_swap_chain_on_the_full_db_moves_on_and_never_doubles`, `test_qa2_a_long_swap_chain_moves_on_and_never_doubles_a_task_on_the_day` (xfail).

### v0.12-B23 (minor): minutes spent vanish when you swap a task
**Steps:** spend 10 minutes on a puzzle task, then Swap it.
**Expected:** still about 10 min. **Actual:** 0. Totals read only tasks with `removed = 0`, though `attempt_facts` says swapped tasks count too. The plan progress sent to the AI is affected as well.
**Evidence:** `test_qa2_minutes_spent_stay_after_a_swap` (xfail).

### v0.12-B24 (minor): a plan-day tag is shown nowhere
**Steps:** Tag a plan day, Save.
**Expected:** you can see the tag (FR-10.67). **Actual:** it's stored, but no entry, filter or Plan tab shows it, so it looks as if nothing happened.
**Evidence:** `test_qa2_a_plan_day_tag_can_be_seen_on_the_entry` (xfail).

### v0.12-B25 (minor): the Include my journal preview doesn't wrap a long word
**Steps:** an entry with a long unbroken word (a long link is cut, but other text isn't). Open the preview.
**Expected:** it wraps, as B14's fix did elsewhere. **Actual:** the text runs out of its box. The check puts 1,000 characters into the real element, because the mock's preview is fixed text.
**Evidence:** `test_qa2_a_long_word_stays_inside_the_journal_preview` (xfail); `tests/e2e/artifacts/qa-v012-r2-preview-long-word.png`.

### v0.12-B26 (minor): a session running when a task carries finishes the task twice
**Steps:** start a puzzle task late in the day, let the plan read after midnight (the copy is made), then finish the session.
**Expected:** one task done. **Actual:** the original and its copy both turn done, so **done** and **Plan tasks done** count 2. The copy inherits the original's attempts, and the original still collects them.
**Evidence:** `test_qa2_a_session_running_past_midnight_does_not_finish_a_task_twice` (xfail).

### v0.12-B27 (minor): closing a reflection's question throws away what you wrote
**Steps:** Start a reflection task, write something, then close the blue question box.
**Expected:** your words stay. **Actual:** the text box empties: clearing the draft changes the component's `key`, which remounts the tab.
**Evidence:** `test_qa2_closing_a_reflections_question_keeps_what_you_wrote` (xfail).

### v0.12-B28 (minor): game labels
- **The Game filter names two games against one opponent the same** (`White – Black`, no date), so you can't tell them apart. `test_qa2_the_game_filter_tells_apart_two_games_against_one_opponent` (xfail).
- **A game with no date shows empty brackets** in Tag a game: `player_a – opponent_b ()`. `tests/e2e/artifacts/qa-v012-r2-real-composer.png`.

### v0.12-B29 (minor, bridge only): a lesson's drill crashes with no puzzle database
**Steps:** with no `puzzles.db`, call `start_plan_lesson_drill`.
**Expected:** the plain message Start gives. **Actual:** *Something went wrong* (`no such table: pz.theme_bits`): `start_lesson_drill` has no `_puzzles_ready` check. The real window can't reach this, since it shows only *Get the puzzle database*.
**Evidence:** `test_qa2_a_lessons_drill_with_no_puzzle_database` (xfail).

### v0.12-B30 (minor, docs)
CHANGELOG's Changed line for **Since last report** still says "at least 5 games in each report", while the User Guide and FR-10.73 say "in that group".

## Automated suites (one at a time)

| Command | Result |
|---|---|
| `uv run pytest` | **2897 passed, 1 skipped, 16 xfailed** (448 s), rc 0 |
| `uv run pytest -m e2e` | **380 passed, 3 xfailed** (834 s), rc 0 |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0; 39 passed, 1 skipped, **1 failed** (538 s). See below |
| `uv run pytest -m engine` | **19 passed** (74 s) |
| `uv run pytest -m fulldb` | dev `puzzles.db` imported: **74 passed, 4 xfailed** (568 s): B22, plus the older v0.2-B2 and v0.5-B10 speed limits |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 425 files formatted |
| `uv run mypy src` | Success: 132 source files |
| `npm.cmd --prefix web run typecheck` / `lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | Hardcoded secrets Passed; keyring only in secret_store.py Passed |
| `python scripts/check_docs.py --strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.12]`, rc 0 |

**The one smoke failure, with both results:** `test_qa2_the_new_tags_filter_link_and_hand_tick_in_the_real_app`
- **In the full smoke run: failed** on `journal-tag-day`'s `input_value()`, read right after the question appeared.
- **Alone, before any change: 1 passed.**
- **Cause, as far as I can tell:** a fault in my test, which didn't wait for the day list to load. The evidence is that it only failed under load, and the same test's stored row check passes. I didn't reproduce the failure on purpose.
- **After fixing the wait:** the whole new smoke file passed 3 times alone (3 passed each). I did **not** repeat the full smoke run after that.
- Round 1's flake (`test_try_again_in_the_real_app`) passed this time.

Round 1's 16 regression tests for B1 to B14, run again by name after the suites: 13 and 3 passed.

## Tests added

All of these were run. Open bugs are `xfail(strict=True)` with their ID.
- `tests/integration/test_qa_v012_round2.py`: carry-over over several days, Swap chain, hand ticks, review passes, an ended plan with a running session, timeline paging and mixed filters, tags and what they send, the group guard for each kind, migrations, no puzzle DB.
- `tests/e2e/test_qa_v012_round2_ui.py`: the composer's tags, the Game filter, tooltips on the new controls, a narrow window, long words.
- `tests/smoke/test_qa_v012_round2_real_app.py`: tags, filter, journal link, long word, hand tick and a reflection task in the real window; a database at 0011; the real bridge with no puzzle DB.
- `tests/fulldb/test_qa_v012_round2_fulldb.py`: the Swap chain and preview speed on the full DB.

## Scope, architecture, security

Fix commit only: one new migration, none edited. No dependency change. No `datetime.now()`, `time.time()` or global `random` in the files it changed under `core/` and `services/`. The new `JournalGame` DTO is exported and `types.ts` has it. The new test fixtures use placeholder names only, and pre-commit's secret scan passed.

I re-ran only the commands listed above, as this round's request asked, not the whole Developer Guide table. I did not re-walk the User Guide; I read its changed lines against the behaviour above (B18, B30).

## For Adam's manual test

Everything from round 1's list still stands (the live test, AI plan quality, the real two-day flow, real lesson links, tooltip wording). Also:
- **Whether B16 should be fixed** by working out the real rate, or by saying *not enough* / *out of the top list* with no verdict. That's your call on the wording.
- **Whether the composer's game tag needs a ply.** FR-10.67 says "a game (and ply)"; the composer tags the game only, and the tooltip points to Game Review for one move. I didn't file this as a bug.
- **Tag a plan day (B24):** what you'd want it to show.
- **Whether the 50 latest games are enough** for Tag a game.

---

# Round 3 (re-verification), 2026-11-05

Branch `v0.12` at `6524009`, run by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `-m live` was **not** run: nobody asked for it. No real credentials were read or used.

## Verdict: **PASS WITH ISSUES** (no blocker, no major, 9 minor)

All of B16 to B30 pass their re-test, including B16, the only major left from round 2. B1 to B15 have not regressed. I found 9 new minor bugs, B31 to B39. Two come directly from round 2's fixes: B31 (from B22) and B34 (from B26). B33 and B35 are older gaps in the same code that round 2's fixes made easier to see. None loses data, sends anything it shouldn't, or calls a weakness better than it is, and each has a workaround by hand, so I rate none as major.

The gate's QA condition (minor issues only) is met. Whether to fix any of these before the rc is Adam's call. If only one gets fixed, I'd pick **B33**, because it contradicts a sentence in both FR-10.64 and the User Guide.

## Re-test of B16 to B30

| Bug | Result | Evidence and what I checked |
|---|---|---|
| B16 weakness out of the list called better | **Fixed** | Real window, real reports with their stored numbers set: `6 / — / no longer in the top list`, marked **Gone**, no "better" (`tests/e2e/artifacts/qa-v012-r3-whole-game-gone.png`). Through the real `get_coach_report`: `now`, `delta` and the last series value are null, the verdict is `not_enough`, and sorting doesn't crash. The AI's part says `not_enough`, with `this report: null`. `validate_trend` drops "improved", "worse" and "same". A five-report series with the weakness coming and going keeps its gaps; when it comes back it's **New** with no verdict. A tactical weakness that's gone stays `0.0, better`, as designed (but see B36). |
| B17 Daily log with a filter | **Fixed** | Round 2's 3 cases through the bridge. |
| B18 search capped at 500 | **Fixed** | Past 500 by round 2's test. 5,000 entries: all returned, `older` false, under 3 s. 2,000 notes tagged to a move: 0.75 s. |
| B19 window edges | **Fixed** | Round 2's two tests. Also a window wholly in the future, From after To, and To far ahead with a search. |
| B20 review passes | **Fixed** | Round 2's three tests. New: finished passes and the log's *reviewed* count survive a new plan; a replaced plan keeps its finished review, and its half review stays undone after visits made later; a new plan made in the same second as a visit still works. |
| B21 hand tick's day | **Fixed** | Stays on day 1 when the app sees it on day 2. Untick and re-tick gave the expected counts. |
| B22 Swap's dead ends | **Fixed, with a regression** (B31) | Full DB: every slot moves on with no doubles, and all three pool modes start with puzzles. Real window, from the ⋯ menu, 5 swaps: all different, minutes kept. A fixture-DB chain of 30 keeps the day's minutes, count and other tasks, and every result starts. |
| B23 minutes after a swap | **Fixed** | A chain of swaps with time on each adds up. The AI's `minutes_spent` equals the screen's, with copies and swaps mixed. |
| B24 plan-day tag | **Fixed** | Real window: the badge shows and stays the same after the plan is replaced. Through the bridge: it also stays after an edit. It doesn't say the plan has ended (see "Observations"). |
| B25 preview long word | **Fixed** | Round 2's e2e test. |
| B26 task finished twice | **Fixed for puzzles, Retry, review; gap filed as B34** | Copy chains over 3 days keep progress and finish once. `done`, the log and the screen agree. |
| B27 closing the question | **Fixed** | Real window and mock: words and tags stay. Saving clears the composer. Start again brings the question back. See "Observations" for the tick. |
| B28 game labels | **Fixed** | Two games on one day against one opponent still differ (new test). Real composer: no empty `()`. |
| B29 drill with no puzzle DB | **Fixed** | Round 2's test through the bridge. |
| B30 CHANGELOG wording | **Fixed** | The line now says "in that group". |

**B1 to B15:** all their tests pass in the suites below, and their xfail marks are gone. Spot check by name: `-k` on 15 of round 1's test names gave 14 passed. The real-app main flow, `test_qa_v012_the_main_flow_in_the_real_app`, passed.

**Hunted and clean:**
- **`PlansRepo.add`:** see B20 above. Nothing else reads an open pass; the log reads `completed_at` only.
- **Copies:** a hand tick and untick on the copy; swapping a copy never brings the original back on later days.
- **Unknown rate:** all paths listed under B16.
- **Search:** see B18.
- **Swap speed on the full DB:** 0.23 s at worst over 25 swaps, even with a puzzle count per choice.

## New bugs

### v0.12-B31 (minor, regression from B22): Swap gives the same puzzles again when your speed has changed
**Steps:** have 50 or more attempts. A day holds `6 puzzles: any theme` from when you were slower. Swap the other task on that day until it reaches general puzzles.
**Expected:** never a task already on the day (`swap_for`'s rule, and round 2's B22).
**Actual:** the day holds `6 puzzles: any theme` and `30 puzzles: any theme`. `_swap_in` compares type and title only, and the count is in the title. The old code also compared `_same`, which ignores the count. The same applies when swapping a puzzle task itself, which then looks like a resize. Anyone with 50 attempts has a speed that drifts as they solve.
**Evidence:** `test_qa3_swap_is_not_fooled_by_a_new_puzzle_count_after_your_speed_changes` (xfail).

### v0.12-B32 (minor): a hand tick on a task "Moved to the next day" leaves its copy open
**Steps:** miss a day so a task carries. Open the earlier day in the Plan tab, where the row says **Moved to the next day**. Its Start and ⋯ are hidden, but its checkbox is live. Tick it.
**Expected:** one task, settled once ("once a task has a copy, the copy is the task").
**Actual:** the original is done and the copy is still left (real window: `original: done, copy: left, done: 1`). Tick the copy too, and `done` and the log's **Plan tasks done** both count 2 for one task.
**Evidence:** `test_qa3_a_hand_tick_on_a_task_moved_to_the_next_day_settles_the_one_task` (xfail); `tests/e2e/artifacts/qa-v012-r3-hand-tick-on-moved.png`.

### v0.12-B33 (minor): a task you unticked comes back ticked when it's copied
**Steps:** finish a puzzle, Retry or review task, then untick it. Next training day, read the plan.
**Expected:** still unticked (FR-10.64 and the User Guide: "a box you unticked stays unticked until you tick it again").
**Actual:** the copy has no hand choice and inherits the facts, so it's `done` at once, and `done` counts it. Unticking the copy does hold.
**Evidence:** `test_qa3_a_task_you_unticked_stays_unticked_when_it_carries` (3 cases, xfail).

### v0.12-B34 (minor, from B26): a reflection or lesson finished from the original after its copy is made doesn't count for the copy
**Steps:** Start a reflection or a lesson task before midnight. Something reads the plan after midnight, which makes the copy. Then save the entry, or open the lesson's link, still from that Start.
**Expected:** the task is done once.
**Actual:** a reflection ticks neither: the original is blocked by `Facts.carried`, and the copy has another id, so it stays left though you wrote the entry. A lesson marks the original done and leaves the copy left. It's narrow: the app has to stay open over midnight.
**Evidence:** `test_qa3_a_reflection_or_lesson_started_before_midnight_ticks_after_it` (2 cases, xfail).

### v0.12-B35 (minor): Swap offers a game already in the plan, or already reviewed
**Steps:** a plan from a report with a few games, then press Swap repeatedly. Or review a game first, then Swap.
**Expected:** a task you can still do. `core/plan.py` says games are used once per plan.
**Actual:** Swap offers a review of a game another day already has, so one pass ticks both. A game already reviewed since the plan began gives a task that's **done the moment it appears**, which adds 1 to `done`. `swap_choices` and `_swap_in` don't check the rest of the plan.
**Evidence:** `test_qa3_swap_does_not_offer_a_game_another_day_of_the_plan_already_has`, `test_qa3_swap_never_gives_a_task_that_is_already_done` (xfail).

### v0.12-B36 (minor): a tactical weakness that's gone shows two different numbers
**Steps:** three reports, with a tactical weakness in the first two and not in the third.
**Expected:** one number for the latest report.
**Actual:** **Now** says `0` and the verdict is *better*, but **Last 3 reports** ends in `—`. The AI gets `this report: null` with `change: better`.
**Evidence:** `test_qa3_a_tactical_weakness_gone_has_the_same_number_in_its_series_and_the_prompt` (xfail); `_weakness_rows` sets `now` to 0.0 and the series to None.

### v0.12-B37 (minor): Send to Coach from My games can land on a tab that hides its message
**Steps:** open Coach → Plan or Journal. Go to My games, tick a game, press **Send to Coach**.
**Expected:** the Coach shows what was sent, and **Run the Coach**.
**Actual:** it stays on the tab you left, so *N games sent from My games* and the run button are on a tab you aren't looking at. Nothing appears to have happened. `App.tsx` doesn't set the Coach tab on this path. Found by my own test in the real window, then confirmed on the mock.
**Evidence:** `test_qa3_send_to_coach_from_my_games_shows_what_was_sent_whatever_tab_you_left` (xfail).

### v0.12-B38 (minor): a slow, older journal answer replaces the newer one on screen
**Steps:** clear the Search box and type a word straight away, so the whole journal (slower, it has the daily log) is still being worked out when the search answers.
**Expected:** the screen shows the word you searched for.
**Actual:** the older answer lands last and stays: the box says `find`, the list shows everything. `JournalTab.load` doesn't ignore out-of-date answers.
**How sure I am:** the test proves this with a delay I inject in front of the real bridge, so it shows the code has no guard, not how often it happens. My guide walk failed twice in 7 runs at the same place (search typed, the daily log stayed), which fits, but I didn't prove that's the cause. Two loops without an injected delay (25 and 24 rounds) didn't reproduce it.
**Evidence:** `test_qa3_a_slow_older_answer_does_not_replace_the_search_you_asked_for` (xfail, smoke).

### v0.12-B39 (minor, docs and leftovers)
- **User Guide, *The checkboxes*:** Swap is "the next task for the same weakness, otherwise for the next weakness". Since B22 it also goes on to general puzzles in other modes and to journal questions, and starts over when it's been through them.
- **ARCHITECTURE §7, the `review_passes` entry:** doesn't record that a new plan deletes unfinished passes.
- **`core/plan.py`:** `swap_for` and `_first_free` are now used only by unit tests, so those tests pass on code the app no longer runs.

## Developer Guide commands (the whole table, this time)

| Command | Result |
|---|---|
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete". Not with no flags: that would create shortcuts and write the real data folder |
| `uv run python scripts/fetch_puzzle_db.py` with a temp `WEAKSQUARE_DATA_DIR`, not `--dev` | rc 0, real download and import: 6,193,530 puzzles in 546 s. Not `--dev`, because that would replace the DB the full-DB tests read |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed, nothing to do |
| `npm.cmd --prefix web run build`, `uv run python -m weaksquare --dev` | **As written, on the dev data folder**: the window loads `WeakSquare Chess Trainer`, closes with rc 0. This opens the dev `user.db`, so it's now migrated to this version |
| `npm.cmd --prefix web run dev`, then `uv run python -m weaksquare --dev-server` | the window loads `http://localhost:5173/`, closes with rc 0 |
| `npm.cmd --prefix web run dev -- --mode mock` | HTTP 200 on 5173 |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged, though its time changes, so the next smoke run stops with the "run build" message, as the guide says |
| `uv run python scripts/make_icon.py --check` | up to date |
| `uv run python tests/fixtures/tools/record_db_update.py` | Writes scrubbed copies. Diff: `page.html`'s date and one link's class. Fixture checks passed on it (47 passed). I restored the committed file |
| The test, lint, type, docs and screenshot rows | see the suites below |
| `set_test_token.py` (both rows), `-m live` (all rows) | **Not run:** Adam's (credentials) |
| Build the Windows installer | `TODO(v1.0)`, nothing to run |

No human-facing command uses a `.ps1` script, bare `npm` or `npx`, or venv activation.

## User Guide walk

`test_qa3_the_user_guide_sections_step_by_step_in_the_real_app` follows the guide's own words in the real window.
- ***Your training plan*:** the run-the-Coach-first message, the labels and defaults of the builder, Preview (nothing saved), Start this plan, starting today, 2 to 4 tasks adding up to your minutes, at least one reflection a week (the test checks at least one, not exactly one), replace only with confirm, Earlier plans, ticks on the Today card shown in the Plan tab, an untick that stays, and the Skip and Swap menu words.
- ***Your training journal*:** Save, Edit, Delete, Search, Show and the daily log.
- ***Finding out what an option does*:** hover in the real window. Tab is on the mock, because a window driven over CDP has no OS focus.
- ***Since last report*:** read against the real screenshot, including the new *no longer in the top list* wording.
- ***Include my journal* and *AI coaching*:** not walked step by step here. The preview is in the main-flow smoke test, and the saved-answer rules are in round 1's tests. A real AI answer is manual only.
- **Not walked again:** the Today card on a rest day, which round 1's tests cover.

Labels, order and defaults match, except what B39 lists. No step misleads, so nothing here is major.

## Automated suites (one at a time)

| Command | Result |
|---|---|
| `uv run pytest` | Before my tests: **2913 passed, 1 skipped** (461 s). With the final tests: **2932 passed, 1 skipped, 10 xfailed** (473 s), rc 0 |
| `uv run pytest -m e2e` | **386 passed, 1 xfailed** (862 s), rc 0. I added two tests to `test_qa_v012_round3_ui.py` after this run started and fixed one; that file alone: **5 passed, 1 xfailed**. I did not repeat the whole command |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | First run: 42 passed, 1 skipped, **1 failed** (631 s). See below. Rerun with the final tests: build rc 0, **43 passed, 1 skipped, 1 xfailed** (654 s), rc 0 |
| `uv run pytest -m engine` | **19 passed** (71 s) |
| `uv run pytest -m fulldb` | dev `puzzles.db` imported: **76 passed, 3 xfailed** (568 s): the older v0.2-B2 and v0.5-B10 speed limits, none from v0.12 |
| `uv run pytest -m docs_screenshots` | **46 passed** (130 s). One image changed, below |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 429 files formatted |
| `uv run mypy src` | Success: 132 source files |
| `npm.cmd --prefix web run typecheck` / `lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | rc 0: hardcoded secrets Passed; keyring only in secret_store.py Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.12]` |

**The one smoke failure, with both results:** `test_qa3_the_user_guide_sections_step_by_step_in_the_real_app`
- **In the full run: failed.** After typing a search, the daily log stayed on screen. Same step as B38.
- **Alone: 1 passed** (17 s).
- **What I changed:** the test now waits a second before searching, with a comment naming B38. So the final run's pass doesn't cover that race; its own test does.
- Round 1's flake (`test_try_again_in_the_real_app`) and round 2's tag test passed in both full runs.

**Screenshots:** `docs/img/stats-reasons.png` changed. I looked at the committed and the new image, and they differ only in a hover highlight on the **Why you missed** tab. It's the same file size (130,141 bytes) as before the last commit, so this image flips between two captures on each regeneration. It's harmless, and I restored the committed one. No other image changed.

## Tests added

All of these were run. Open bugs are `xfail(strict=True)` with their ID.
- `tests/integration/test_qa_v012_round3.py`: passes across a new plan, copy chains, hand ticks on copies, Swap and its pool, the unknown rate through the real report read and the prompt, the five-report series, thousands of entries, the badge, window edges, B21, B23, B26, B28.
- `tests/e2e/test_qa_v012_round3_ui.py`: the composer after a closed question, the badge, Send to Coach, Tab on an info mark, repeated search.
- `tests/smoke/test_qa_v012_round3_real_app.py`: the round 2 fixes together in the real window, the User Guide walk, search order, B38.
- `tests/fulldb/test_qa_v012_round3_fulldb.py`: Swap's speed and pool on the full DB.

## Scope, architecture, security

Fix commit only: no new or edited migration, no change to `uv.lock` or `package-lock.json`. No `datetime.now()`, `time.time()` or global `random` in `core/plan.py`, `core/report_compare.py`, `services/plan.py` or `services/journal.py`. `types.ts` matches the DTOs. The new tests use placeholder names only, and pre-commit's secret scan passed. Nothing new from a later version.

## Observations (not filed as bugs)

- **Closing a reflection's question means saving won't tick the task.** Your words and tags stay, but the link to the task is gone, so the saved note leaves the task unticked with no message (real window: task stays `left`). That follows "saved from the task", but someone may close the box just to get it out of the way.
- **With its copy swapped away, the original says Missed** rather than **Moved to the next day**. That's accurate enough, and a test records it.
- **The plan-day badge doesn't say the plan has ended.** `Plan: Thu, Nov 5` reads the same for a replaced plan.

## For Adam's manual test

Everything from round 1's list still stands: the live test, AI plan quality, the real two-day flow, real lesson links and tooltip wording. Also:
- **Which of B31 to B39 to fix before the rc.** All are minor, so the gate doesn't require any. I'd start with B33, then B31 and B35, which make Swap and the totals look wrong.
- **Whether saving after closing the question should tick the task.**
- **Your remaining calls from round 2:** the composer's game tag has no ply, what a plan-day tag should show, and whether 50 games are enough for Tag a game.
- **Your dev database:** my `--dev` run opened it, so it's migrated to this version.

# After round 3 (builder's note, not QA's)

The builder fixed B31 to B39 after this report. Their xfail marks are gone, so they run as regression tests. **No QA round has re-verified these fixes.** ROADMAP allows 3 rounds, and the gate's QA condition was already met.

- **A bug the fixes exposed:** with B35's smaller pool, `test_qa2_swap_chain_on_the_full_db_moves_on_and_never_doubles` showed that Swap, once it had been through everything, bounced between two tasks. Fixed, with `test_swap_keeps_cycling_once_it_has_been_everything_and_never_bounces_between_two`, which fails on the old behaviour.
- **QA tests changed:**
  - B31's test no longer counts a Commit-the-line task as the same task, because another mode is another task.
  - The round 3 smoke test now expects the box on a moved row to be disabled (B32), and no longer waits or clicks around B37 and B38.
  - Its search step now waits for the result instead of asserting at once.
- **Still failing:** `test_ladder_preview_slow_branches_are_within_target[fork, promote 3->4]`, a v0.5 500 ms limit. It takes 499 to 523 ms on `main` (v0.11) on this PC, so v0.12 didn't cause it. The limit was left as it is.
- **Seen once, not explained:** `test_qa_v011_whole_game_report_and_per_run_options` failed with `TargetClosedError` in one full smoke run. It then passed 4 of 4 alone and in the next full run (44 passed, 1 skipped). The failing line wasn't captured.
