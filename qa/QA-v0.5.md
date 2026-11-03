# QA report: v0.5 (Training modes I)

**Round 1, 2026-11-02.** Branch `v0.5` at `11c9e9e`. Independent QA. No product code, migrations, config or docs were changed; new tests are only under `tests/` (`test_qa_v05_*`). Not run: `pytest -m live`, any keyring read. The real app ran with temp `WEAKSQUARE_DATA_DIR` folders for every QA flow. Two Developer Guide commands run "as written" use the dev data folder; see *For Adam* (dev `user.db` migrated 3 → 4 with a backup, and the app's own Lichess history import ran once with the dev sign-in).

## Verdict: **PASS WITH ISSUES** (minor only)

Every *Done when* item passes with evidence, including a Commit-the-line submit, a mode switch, fast-forward + Spaced repetition and Hide filters surviving a relaunch **in the real app**. Six minor issues (B1–B6), no blocker or major.

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder: **809 passed**, 270 deselected (143 s). With QA tests: **851 passed**, 278 deselected (153 s); exits normally |
| `uv run pytest -m e2e` | **150 passed** (392 s). QA file `test_qa_v05_ui.py`: 6 passed |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **23 passed, 1 skipped** (the v0.4 download test, opt-in). QA file `test_qa_v05_real_app.py`: 2 passed |
| `uv run pytest -m fulldb` (dev `puzzles.db` imported) | **61 passed, 1 xfailed** (516 s); `test_perf_v05.py` 2 passed (8.7 s) |
| `uv run pytest -m engine` | **10 passed** (28 s) |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 219 files already formatted |
| `uv run mypy src` | Success: no issues found in 70 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed (also re-run after adding QA tests) |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.5]` (both) |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged (no git diff) |
| `uv run pytest -m docs_screenshots` | **21 passed**; `docs/img` byte-identical (no git diff) |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`; not bare, it writes real shortcuts) | rc 0, "Setup complete" |
| `npm.cmd --prefix web run build` + `uv run python -m weaksquare --dev` | window up, WM_CLOSE → exit 0, no ERROR lines |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` | window up, exit 0, no ERROR lines |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, Vite "mock" ready |
| `fetch_puzzle_db.py --dev`, `record_db_update.py`, `set_test_token.py`, `-m live` | not run (unchanged since v0.4; would replace the dev DB / call Lichess / need credentials) |

No human-facing command uses a `.ps1`, bare `npm`/`npx` or venv activation.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **DW** Mode state machine: Commit grading by index | unit | PASS | `test_commit_line_mode.py` (16), `test_qa_v05_modes.py::test_missing_reply_counts_as_not_predicted_and_missing_player_moves_lose`, `…the_line_ends_at_an_accepted_mate…` |
| FR-4.2 mate alternative only while every earlier ply matched | unit (new) | PASS | `test_qa_v05_modes.py::test_alternative_mate_on_a_later_ply_is_accepted…` (fixture FrexF, g8b8 for f4b8), `…after_a_wrong_prediction_is_not_accepted` |
| FR-4.2 missing player moves wrong, extras ignored | unit | PASS | `test_extra_moves_after_the_solution_are_ignored`, QA missing-reply test |
| FR-4.2 replies stored (`replies_correct/total`, migration 0004) | integration | PASS | `test_modes_v05.py::test_commit_the_line_grades…`, `test_user_db_v4.py`; real app: row `("commit_line", 1, r, r)` |
| **DW** Help before Submit is a loss, after is free | unit + integration | PASS | `test_hint_before_submit_is_a_loss…`, `test_help_after_submit_is_free`, QA `test_hint_before_submit_is_a_loss_recorded_once`, `test_show_answer_before_submit_ends…` |
| FR-4.2 Try again (not recorded) | integration + e2e | PASS | QA `test_commit_try_again_records_nothing`; `test_modes.py::test_commit_try_again…` |
| FR-4.2 illegal / overlong / junk lines, submit twice | integration (new) | PASS | QA `test_submit_line_with_the_wrong_type…` (4), `…junk_moves…` (5, incl. 300 plies), `test_overlong_line_with_show_move_count_is_refused`, `test_submit_twice_records_once`; e2e double-click Submit → 1 call |
| FR-4.2 Show move count caps entry | e2e (new) | PASS | `test_qa_v05_ui.py::test_show_move_count_stops_entry_at_the_solution_length` |
| **DW** SRS: box moves, graduation, misses from any mode, calendar day | unit | PASS | `test_srs.py` (11 + params), QA UTC−5 evening miss, graduated-never-due, other-mode wins |
| FR-4.6 removed by re-import skipped | integration (new) | PASS | QA `test_srs_skips_puzzles_a_reimport_removed`, `test_srs_with_every_due_puzzle_removed_cannot_start` |
| FR-4.6 intervals shrunk after high boxes | unit + integration (new) | PASS | QA `test_srs_shrunk_intervals_after_reaching_a_high_box` (box 4 → `[1,2]` replays to graduated) |
| FR-4.6 queue size applies, most overdue first, angle `mix` | integration | PASS | QA `test_srs_queue_size_still_applies…`, `test_srs_skip_in_review_sends_it_back_to_box_one`; builder `test_a_miss_comes_back…` |
| FR-4.6 fast-forward dev-only, then review | integration + real app | PASS | QA `test_fast_forward_then_review_with_the_dev_clock` (OffsetClock +1 → due, +4 → box 2 due), `…refused_outside_dev…`; real-app smoke (Debug +1 day → "1 puzzle due now") |
| **DW** Ladder: window, threshold, never drops | unit | PASS | `test_ladder.py` (13), QA exact-threshold and bigger-window tests |
| FR-4.5 shared across Standard/Commit, practice never counts, count = current level | integration (new) | PASS | QA `test_ladder_level_is_shared…`, `test_ladder_practice_runs_never_count`, `test_ladder_count_matches_counts_only_the_current_level` |
| FR-3.11 ladder can't combine with ratios | integration | PASS | builder + QA (`get_ladder_status`, `count_matches` → invalid_argument) |
| **DW** Angle with the ladder and Show move count | unit + integration | PASS | `test_angle.py::test_depth_ladder_*`, `::test_commit_show_move_count…`; QA ladder test records `short`; builder `test_commit_show_move_count…` |
| **DW** Playwright: one flow per mode | e2e | PASS | `test_modes.py` (Commit ×3, SRS ×3, ladder, Standard via existing suites) |
| **DW** Mode switch starts a new session (nothing recorded) | integration + e2e + real app | PASS | builder `test_switching_mode…`; QA `test_mode_switch_after_a_correct_first_move_records_nothing`, e2e `…mid_puzzle_records_nothing…`, real app (attempts stay at 1, sessions `commit_line, standard`), rapid switching ends on the chosen mode (10 sessions, badge matches) |
| **DW** No engine output before Submit | e2e + integration + real app | PASS | `test_modes.py` `no_engine_output`; QA `test_engine_is_refused_before_submit…`, `test_engine_stays_refused_after_a_hint_until_submit`; real app `engine-panel` count 0 before Submit |
| **DW** Collapse/expand keeps filters and **survives a relaunch** through the bridge | e2e + real app (new) | PASS | `test_hide_and_show_filters…` (mock: setting call only); QA real app: `ui.filters_collapsed=true` in `user.db`, relaunch shows the strip, Show filters restores the panel, mode still `spaced_repetition`, `localStorage+sessionStorage == 0` |
| FR-1.14 F shortcut, strip summary, wider board | e2e + visual | PASS | `test_hide_and_show…` (F), screenshots `qa-v05-collapsed-playing.png` (board 656 px vs 544 px) |
| §3.2 Modes control, last mode remembered | e2e + real app | PASS | `test_mode_is_remembered`; real-app relaunch |
| FR-9.1 Stats by mode | unit + e2e | PASS | `test_stats.py::test_by_mode…`, `test_stats_by_mode_and_training_settings`, `qa-v05-stats-by-mode.png` |
| Settings → Training / Debug (dev only) | integration + e2e | PASS | `test_new_settings_round_trip…`, `test_no_debug_section_outside_dev_runs`; QA `test_app_wires_the_offset_clock_only_for_dev` |
| Version 0.5.0 | contract | PASS | `test_versions_agree.py` |
| Full-DB timings | fulldb | PASS | `test_perf_v05.py` 2 passed |

---

## Bugs

All minor.

**v0.5-B1 (minor): a mode switch that can't start leaves the old session running under the new mode's label.**
Steps: mock `?srs=none` (or real app with nothing due), Start a Standard session, click **Spaced repetition**.
Expected: the switch either starts an SRS session or doesn't take effect (§6: "switching starts a new session in that mode").
Actual: the error "Nothing is due for review…" appears, the Modes control shows Spaced repetition (saved as `trainer.mode`), the filters are greyed out, and the board keeps playing the **Standard** session (badge "Standard"). Same for any switch whose `start_session` fails (e.g. 0 matches). `web/src/App.tsx` `changeMode` sets and saves the mode before `start(next)` succeeds.
Evidence: `tests/e2e/test_qa_v05_ui.py::test_switching_to_spaced_repetition_with_nothing_due_mid_session` (prints `session-mode='Standard' start_disabled=True`), `tests/e2e/artifacts/qa-v05-switch-to-srs-nothing-due.png`.

**v0.5-B2 (minor): the depth ladder dead-ends at a level with no puzzles.**
Steps: themes = Mate in 2, Order = Depth ladder, window 3 / threshold 60, solve 3.
Expected: the ladder skips or tops out at levels the theme set can't fill, or says why.
Actual: "Level up!" to Long, then the session just ends (`next_puzzle` → None). Since the level never drops, every later session for that theme set shows 0 matches "at long" and Start is disabled for good. Likewise a theme set with no 2-move puzzles (e.g. Mate in 1) can never start. `services/session.py` `_after_ladder_attempt`, `core/ladder.py` `status`.
Evidence: `tests/integration/test_qa_v05_edges.py::test_ladder_climbing_into_an_empty_level_ends_the_session` (pins current behaviour).

**v0.5-B3 (minor): hidden length can be deduced from the entry cap.**
With Show move count off, `PuzzleView.max_plies = min(60, 2n+10)` and the entry stops with "That's as long as a line can be." at exactly 2n+10 plies, so n follows. Those solves are still reported with angle `mix` (§8.3 says a known length isn't `mix`). Practically nobody enters 16+ plies, but the docstring's "doesn't give the length away" isn't true. A cap independent of n (e.g. always 60) avoids it. `core/modes/commit_line.py` `max_plies`, `web/src/components/CommitLine.tsx`.

**v0.5-B4 (minor, cosmetic): "Replies predicted: 0 of 0" on one-move puzzles.**
Steps: Commit the line on a mate-in-1 and submit. Expected: no calculation line when there are no replies. Actual: "Replies predicted: 0 of 0". Evidence: `tests/e2e/artifacts/qa-v05-real/commit-result.png`.

**v0.5-B5 (minor, pre-existing since v0.3, now frequent): the "Already played on Lichess: rating unaffected" badge is clipped.**
It shows as "Already played on Lichess: rating unaffect…" in the right column, collapsed or not, and FR-4.6 relies on it for nearly every SRS puzzle. It also shows for a signed-out user whose miss never reached Lichess (pending sync), where "on Lichess" isn't literally true. Evidence: `tests/e2e/artifacts/qa-v05-real/srs-due.png`, `collapsed.png`.

**v0.5-B6 (minor, docs/UX): the Show move count description only says "From the next session" when the switch is off.**
Turning it **on** mid-session shows the "on" text without saying it applies from the next session, though the running session keeps the length hidden (and its angle stays `mix`, correctly). `web/src/views/MixerView.tsx`. The User Guide states it correctly.

Observation (not a bug): after Hint before Submit, the attempt is recorded at Hint time, so `replies_correct/replies_total` stay NULL for that attempt even though the result panel shows the replies. That's defensible (help was used), but v0.6's FR-9.3 should decide how hinted Commit attempts count.

---

## Tests added
- `tests/unit/test_qa_v05_modes.py` (13): alternative mate on a later ply; alternative mate after a wrong prediction refused; the line ends at an accepted mate; missing reply/player moves; hint then submit; answer then submit refused; hidden cap bounds; SRS other-mode win, graduated never due, UTC−5 evening miss, shrunk boxes replay; ladder exact threshold; bigger window never drops.
- `tests/integration/test_qa_v05_edges.py` (29): `submit_line` wrong types (4) and junk moves (5); overlong with Show move count; submit twice; hint before submit; Commit Try again; engine refused before Submit and after Hint; mode switch after a correct first move; SRS re-import removal (2), queue size + most overdue, skip in review → box 1, shrunk intervals; ladder shared across modes + angle, ratios refused for preview/count, practice never counts, count = current level, empty-level dead end (B2); fast-forward then review (OffsetClock), refused outside dev, OffsetClock wired only for `--dev`.
- `tests/e2e/test_qa_v05_ui.py` (6): mode switch mid-puzzle records nothing; switch to SRS with nothing due (B1); Show move count cap; double-click Submit; Hint before Submit; screenshots of every v0.5 screen.
- `tests/smoke/test_qa_v05_real_app.py` (2): real app Commit submit → mode switch → miss → fast-forward → SRS session → Hide filters → relaunch (still hidden, mode kept); rapid mode switching ends on the chosen mode.

---

## Scope / architecture / security
- **Scope:** no Name the idea, Danger spotting or mistake reasons in `src/` or `web/src` (grep empty); the Modes control lists exactly three modes. No dead UI found.
- **Layers:** `core/` imports no I/O modules; no `datetime.now`/`time.time`/global `random` calls in `core/` or `services/` (`import random` is for the injected `random.Random` type only). `OffsetClock` is built only in `app.py` and only `if args.dev`; `set_time_offset` refuses outside `--dev` (tested). `keyring` only in `adapters/secret_store.py` (`app.py` mentions it in a docstring); `httpx` only in `adapters/http.py`. Only `bridge/api.py` imports an adapter (`Desktop`, pre-existing).
- **Decisions 12–17:** new repo methods use `db.session()` (thread-local); new `Api` dependencies stay underscore attributes, bridge allowlist test passes with the 4 new methods; no browser storage in `web/src` (grep empty; e2e and real app `localStorage+sessionStorage == 0`); tests use temp folders.
- **Migrations:** only the new `0004_modes.sql`; no applied migration edited. Upgrade from v3 tested (`test_user_db_v4.py`) and seen in the real dev folder (backup first).
- **Dependencies:** none added; lockfile diffs are the 0.5.0 version bump only.
- **Security:** no token/key patterns in the v0.5 diff, the new tests or `tests/e2e/artifacts` (FAKE placeholders only); no real usernames/game IDs/URLs added to fixtures; no secrets in the new DTOs. The CDP port is only set by the smoke harness and refused without `--dev` (`debug_port_refusal`).

## Docs
- `check_docs.py --strict`: 0 errors, 0 warnings. No `TODO(v0.5)` left; "Add a training mode" and the fast-forward note are accurate against the code.
- **User Guide "Training modes"** followed against the mock and the real app: Modes control, Commit entry (Undo/Clear/Submit, "Find 3 moves (both sides)"), result ("Your line", ✓/✗, "Replies predicted"), SRS due line and greyed filters, Start disabled with nothing due, Depth ladder line under Order and in the session bar, Level up!, Training settings labels ("Move up at (%)", "Over the last (puzzles)", "Review boxes (days)" + Save), Hide filters (« / F / » Show filters). All match. "Choosing your puzzles", "Stats" and "Keyboard shortcuts" changes match. Not covered in the guide: what happens when a switch can't start (B1).
- Screenshots: `docs_screenshots` regenerates byte-identical images. `commit-entry.png` and `depth-ladder.png` show the panel scrolled so the Mode control is out of view and Start is cut off at the bottom of `depth-ladder.png` (cosmetic, not misleading).
- CHANGELOG `[Unreleased]` covers every user-visible *Done when* item (modes, Commit, SRS, ladder, Stats by mode, Hide filters, Training settings). No v0.5 feature sends new data off the PC (SRS solves sync as before, angle `mix`).
- README status line and ARCHITECTURE §2/§4/§7 (four v0.5 entries) are up to date.

## Visual check
Screenshots in `tests/e2e/artifacts/qa-v05-*.png` (mock) and `tests/e2e/artifacts/qa-v05-real/*.png` (real app): Commit entry and result, Show-count full, after Hint, collapsed (light, dark, while playing, SRS), SRS panel, ladder panel, settings Training + Debug, dev banner, Stats by mode, after relaunch. No layout breakage beyond B4/B5. `qa-v05-settings-training-debug.png` and `qa-v05-ladder-panel.png` were captured mid-transition (fade / segmented indicator); that's capture timing, not a defect.

## For Adam's manual test
- **Run as written, on your dev folder:** `uv run python -m weaksquare --dev` / `--dev-server` migrated the dev `user.db` from schema 3 to 4 (backup `backups\user-3-20261103-035123.db`) and, on launch, ran the app's own Lichess history import with your dev sign-in ("0 entries imported"). No credential was read by QA.
- Real calendar-day rollover (a miss at ~11 pm due the next morning) with the real OS timezone: unit-tested with fixed offsets only.
- Ladder with the default 80% / 20 over a real session (QA used narrow windows).
- B1: switch to Spaced repetition with nothing due mid-session, and decide the intended behaviour.
- The feel of Commit-the-line entry on a long (4+) puzzle, including a promotion entered for either side (not exercised by any test).

---

# Round 2, 2026-11-02: re-verification

Branch `v0.5` at `65f2a9c` (round-1 fixes B1–B6, with the QA report and tests committed). Independent QA, same rules as round 1: no product code, docs or config changed by QA; new tests only under `tests/`. The real app ran only with temp `WEAKSQUARE_DATA_DIR` folders this round.

## Verdict: **FAIL** (one major: B7)

All six round-1 bugs are fixed, each with a regression test that I re-ran and checked against the behaviour. Default, e2e and smoke are green (apart from the pre-existing flake B9).

The B2 fix brought in one regression, B7 (**major**). With Order = Depth ladder, the live count now takes about 0.9 s on the full DB, over the 500 ms requirement. The builder's own full-DB test `test_perf_v05.py::test_ladder_count_at_a_level_is_fast` now fails every time.

B8 and B9 are minor pre-existing flakes in the test and docs tooling, not v0.5 code. Once B7 is fixed, I expect PASS WITH ISSUES.

## Re-verification of round-1 bugs

| Bug | Fix checked | Result | Evidence |
|---|---|---|---|
| B1 failed mode switch | `changeMode` awaits `start()` and only then sets and saves the mode | **FIXED** | e2e `test_switching_to_spaced_repetition_with_nothing_due_mid_session`: the control stays on Standard and the badge still says Standard, the filters aren't greyed, no `setting:trainer.mode` call, and the reason is shown (screenshot `qa-v05-switch-to-srs-nothing-due.png`). Real app (`test_v05_modes_in_the_real_app`): nothing due → Standard carries on; once something is due, the switch starts the review session. Rapid switching still ends on the chosen mode (`test_rapid_mode_switching…`) |
| B2 ladder dead end | `ladder.status(…, available)` and `SessionService.ladder_levels` | **FIXED** | New QA `test_qa_v05_round2.py::test_b2_mate_in_two_short_is_the_top_and_the_session_carries_on`: preview is level 2 with `top=True`; 4 wins → no level-up, session never ends early, still at level 2/top. `…mate_in_one…` still refuses with a reason (0 matches). Builder: `test_ladder.py` (4 new), `test_ladder_skips_levels_with_no_puzzles`. Full DB: Mate in 2 → `levels=[2]`, top |
| B3 length leak | `max_plies` = 60 when the length is hidden | **FIXED** | New QA `test_b3_hidden_cap_is_60_for_every_puzzle` (5 puzzles → `{60}`; shown → the solution length); unit `test_hidden_length_cap…` updated |
| B4 "0 of 0" | badge hidden when `replies_total == 0` | **FIXED** | e2e `test_one_move_commit_has_no_replies_line` |
| B5 clipped badge | wraps, now reads "Already played: rating unaffected" | **FIXED** | e2e `test_already_played_badge_is_whole`; real app `qa-v05-real/collapsed.png` shows the whole badge. User Guide, REQUIREMENTS FR-6.11b and CHANGELOG `### Fixed` use the new wording |
| B6 Show move count text | "From the next session" in both states | **FIXED** | e2e `test_show_move_count_says_it_applies_from_the_next_session_both_ways` |

The doc changes for B1, B2 and B3 (User Guide, REQUIREMENTS FR-4.5, ARCHITECTURE §7 entry) match the behaviour.

## Evidence: commands run (round 2)

| Command | Result |
|---|---|
| `uv run pytest` | **1 failed, 854 passed**. The failure is `test_account.py::test_cancel_sign_in`, which is flaky (B9) and fails about 1 run in 5 when run alone (re-run 5×: 4 passed, 1 failed). Adding the round-2 QA file: +3 passed |
| `uv run pytest -m e2e` | **159 passed** (419 s) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **24 passed, 1 skipped** (232 s). The timing flakes the builder mentioned didn't show up in this run |
| `uv run pytest -m fulldb` | **1 failed, 65 passed, 1 xfailed** (497 s). The failure is the builder's own `test_perf_v05.py::test_ladder_count_at_a_level_is_fast`, which is B7. Run alone 3×, it fails every time: 0.889 s, 0.887 s and 0.902 s against its 0.5 s limit; QA `test_qa_v05_ladder_levels_perf.py` 5 passed (timings under B7) |
| `ruff check`, `ruff format --check`, `mypy src`, `typecheck`, `lint` | all clean (224 files formatted; mypy: no issues in 70 files) |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `python scripts/check_docs.py --strict` | `0 error(s), 0 warning(s) [version v0.5]` |
| `uv run pytest -m docs_screenshots` | 21 passed, but `docs/img/presets.png` differs from the committed copy (B8). I restored the committed copy |

## New bugs (round 2)

**v0.5-B7 (major, introduced by the B2 fix): with Order = Depth ladder, the live match count takes about 0.75–1.0 s on the full DB, over the 500 ms target (REQUIREMENTS §4 "live match count … under 500 ms").**
- **Cause:** `count_matches` → `pool_spec` → `ladder_status` → `ladder_levels` now runs 3 per-level `COUNT`s before the pool count. `get_ladder_status` repeats the same 4 counts for every filter change, so one edit costs about 8 full counts.
- **Measured** (dev full DB, unloaded, two runs, levels + pool): All themes with default quality **975 ms**; All themes open 730 ms; Fork+Pin ALL 830 ms; Mate in 2 880 ms; narrow rating 20 ms. A single per-level count is 180–310 ms, so before the fix the same preview was about 200–310 ms.
- **Expected:** the count stays under 500 ms, as it did before the fix.
- **Suggested fix:** check whether a level has puzzles with an existence query (`LIMIT 1`) instead of `COUNT`, or compute the levels once per edit and share them between the two bridge calls.
- **Docs:** ARCHITECTURE §7 says "each well under the 500 ms target", which is true for each count but not for the request as a whole.
- **Evidence:** the builder's own `tests/fulldb/test_perf_v05.py::test_ladder_count_at_a_level_is_fast` fails every time (0.89 s against 0.5 s). `tests/fulldb/test_qa_v05_ladder_levels_perf.py` prints the timings per filter shape.

**v0.5-B8 (minor, pre-existing docs tooling): `docs_screenshots` doesn't produce `presets.png` deterministically.**
- **What differs:** in one version, ratio group 1 is "Fork + Discovered attack" (as at `11c9e9e`, and in my regeneration this round); in the other, "Fork" alone (as committed at `65f2a9c`).
- **Likely cause:** `_pick` in `tests/e2e/test_docs_screenshots.py` uses `.last` on checkboxes while the first group's theme popover may still be in the DOM, so "Discovered attack" sometimes lands in group 1.
- **Impact:** the caption isn't misleading, but "regenerate at every handoff" gives a diff.

**v0.5-B9 (minor, pre-existing since v0.3): `tests/integration/test_account.py::test_cancel_sign_in` is flaky.**
- **Test cause:** the test only waits for the listener if it already exists (`h.listeners.made and …started.wait(5)`). When the job thread hasn't created it yet, `cancel_sign_in()` runs first and is a no-op.
- **Product side:** a Cancel pressed in the first milliseconds after Sign in would be lost the same way, because `AccountService.cancel_sign_in` does nothing while `_listener` is None.
- **Effect:** it can turn `uv run pytest` and CI red at random.

## Tests added (round 2)
- `tests/integration/test_qa_v05_round2.py` (3): `test_b2_mate_in_two_short_is_the_top_and_the_session_carries_on`, `test_b2_mate_in_one_ladder_still_refuses_to_start_with_a_reason`, `test_b3_hidden_cap_is_60_for_every_puzzle`.
- `tests/fulldb/test_qa_v05_ladder_levels_perf.py` (5, `fulldb`): the ladder preview path (level counts + pool) for five filter shapes, with printed timings (B7).

## Scope / architecture / security (round 2)
- The fix commit only touches files B1–B6 need.
- `core/ladder.py` stays pure: `available` is passed in, and the counts happen in the service.
- No new dependencies or migrations.
- The secret scan is clean.

## For Adam's manual test (round 2 additions)
- **Mate in 2 ladder:** with Order = Depth ladder and Mate in 2, the ladder line says it's the top, and sessions keep going.
- **B7 slowdown:** with Order = Depth ladder on the full DB, the match count updates noticeably more slowly (about 1 s) than with Random.

---

# Round 3, 2026-11-03: re-verification

Branch `v0.5` at `6795945` (fixes for B7, B8 and B9; the round-2 report and tests are committed in it). Independent QA, same rules: no product code, docs or config changed by QA; new tests only under `tests/`.

## Verdict: **PASS WITH ISSUES** (minor only)

B7, B8 and B9 are fixed. The fast ladder preview makes exactly the same decisions as the full per-level count rule across 54 filter × history combinations.

Default, e2e and full-DB suites are green, and static checks, pre-commit and `check_docs --strict` are clean. Smoke has one pre-existing intermittent failure (B11), not v0.5 code.

Two new minor issues:
- **B10:** two rarer ladder-preview branches are still over 500 ms.
- **B11:** the intermittent smoke failure above.

## Re-verification

| Bug | Fix checked | Result | Evidence |
|---|---|---|---|
| B7 ladder count speed | `SessionService.ladder_preview`, `count_level_and_above`, `has_puzzles`, `levels_with_puzzles`; one preview per bridge call | **FIXED** for the normal case | Full DB, fresh history (`test_qa_v05_ladder_levels_perf.py`, now against 0.5 s): All themes defaults **269 ms**, open 190, Fork+Pin ALL 224, Mate in 2 267, narrow rating 7. The builder's `test_perf_v05.py::test_ladder_count_at_a_level_is_fast` passes. **Correctness:** the new QA `test_qa_v05_round3.py::test_fast_preview_matches_the_full_count_rule` gives 54 passed. It covers 9 filter shapes (All themes open/default, Fork, Fork+Pin ALL, Mate in 2, Mate in 1, a narrow Fork, a narrow rating band, Only my misses) × 6 recorded histories (none; level 2, 3 and 4 with a full winning window or a mixed one), plus real solved/missed history for the hiding. Level, top, window and pool all match `core.ladder.status` over a full count per level, and `count_matches`/`get_ladder_status` return the same values. The builder's `test_levels_with_puzzles_matches_a_count_per_level` passes |
| B8 screenshot picker | `_pick` ticks inside its own dropdown | **FIXED** | 3 regenerations: `presets.png` sha256 `ca30d7cd…` every time, and no git diff in `docs/` |
| B9 sign-in cancel race | `cancel_sign_in` also cancels the job; `_sign_in` checks before and after the listener starts | **FIXED** | `test_cancel_sign_in` + `test_cancel_right_after_sign_in_is_never_lost` (20 immediate cancels each run) run 15×: **15/15 passed**. Before the fix: 1 in 5 failed. Code read: a Cancel after approval still completes the sign-in (as before), and `runner.cancel` on a finished job is a no-op |

Observation (not a bug): when a theme set has no puzzles at **any** level (e.g. Mate in 1), the fast preview reports the window as 0 played, where the full rule would echo the recorded history. Nothing can start in that case, and the level and the 0 count agree, so it has no effect.

## Evidence: commands run (round 3)

| Command | Result |
|---|---|
| `uv run pytest` | **860 passed**, 286 deselected (159 s). QA round-3 file run separately: 54 passed |
| `uv run pytest -m e2e` | **159 passed** (424 s) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **1 failed, 23 passed, 1 skipped**. The failure is `test_qa_v04_real_app.py::test_engine_flow_in_the_real_app` (B11) |
| `uv run pytest -m fulldb` | **66 passed, 1 xfailed** (490 s). QA round-3 worst-case file: 2 passed, 2 xfailed (B10) |
| `ruff check`, `ruff format --check` (227 files), `mypy src`, `typecheck`, `lint` | all clean |
| `uv run pre-commit run --all-files` | gitleaks Passed, keyring-only Passed |
| `python scripts/check_docs.py --strict` | `0 error(s), 0 warning(s) [version v0.5]` |
| `uv run pytest -m docs_screenshots` ×3 | 21 passed each time; `docs/img` byte-identical to the commit |

## New bugs (round 3)

**v0.5-B10 (minor): two rarer ladder-preview branches are over 500 ms on the full DB.**
- **Measured** (own `user.db` with 500 solved puzzles, two runs): All themes with a full winning window at Short, which looks up the exact next open level: **530–537 ms**. Mate in 2 with a recorded level 4 that the filters leave empty, which tries 4 → 3 → 2 with a scan each: **780–795 ms**. Fork promoting 3 → 4: 462–475 ms. All themes at the top: 224–265 ms.
- **When the first branch happens:** after the window says you move up and before you've played a puzzle at the new level. The recorded level is still the old one, so every count in that gap takes the slow branch.
- **When the second happens:** when other filters (rating, side, openings) empty the recorded level.
- **Severity:** both are short-lived or rare, and close to the 550 ms already accepted for three-group ratios (ARCHITECTURE §7), hence minor.
- **Evidence:** `tests/fulldb/test_qa_v05_round3_ladder_worst_case.py` (non-strict xfail on the two slow cases).

**v0.5-B11 (minor, not v0.5 code): `test_qa_v04_real_app.py::test_engine_flow_in_the_real_app` fails intermittently.** It failed 3 times in 8 runs (1 in the full smoke run, 2 of 7 reruns, alone or together with `test_qa_v04_rc2_real_app.py`, which passed 7 of 7 reruns). There are two causes:
- **Shutdown log line:** an `ERROR … pywebview: Error occurred in script` (from `evaluate_js`) appears when the test closes the window while a 5 s search is still pushing results. The test asserts there are no ERROR lines.
- **Puzzle-dependent test step:** `Forward` is disabled when the randomly served puzzle has a short answer line, but the test clicks it 3 times.

Neither path changed in v0.5. The builder's `test_try_again_in_the_real_app` flake didn't reproduce here (8 of 8 passed).

## Tests added (round 3)
- `tests/integration/test_qa_v05_round3.py` (54 parametrized): fast ladder preview == full-count rule, also through `count_matches` and `get_ladder_status`.
- `tests/fulldb/test_qa_v05_round3_ladder_worst_case.py` (4, `fulldb`): timing of the promote, top and emptied-level branches (B10).

## For Adam's manual test (round 3)
- On the full DB with Order = Depth ladder, the match count should feel as quick as with Random (about 0.2–0.3 s). Right after a **Level up!**, before you play the next puzzle, it may take about half a second (B10).
