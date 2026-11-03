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
