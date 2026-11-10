# QA report: v1.0 (Fix tracking + release)

Round 1, 2026-11-10, branch `v1.0` at `888fbd0` (commits a7d8870…888fbd0 on top of `main`). I changed only `tests/` and
this report. No credentials were read or used, no `-m live`, and every run used a temp data folder (the dev data folder
only read-only, by `-m fulldb` / `-m engine` and `fetch_stockfish.py --dev`, which found nothing to do).

Adam's build decisions are treated as intended behavior: the FR-10.34 guard (fewer than 5 seen **and** fewer than 5
expected), Auto AI checkpoint summary **on** by default, two charts per weakness card, and the wizard rule (not finished
and (no data, or no puzzle DB, or a choice made)).

## Verdict: **FAIL** (1 major, 5 minor)

The checkpoint engine, statuses, triggers, backfill, Progress page and the wizard's happy paths all work, in the mock,
through the services and in the real app; the **fresh clone** goes from `setup.py` through the wizard to a working app
both starting fresh and restoring a v0.16 backup. One major bug in the wizard: the **Restore** choice is recorded before
the restore is accepted, so a restore that's refused or fails leaves the wizard believing your data was restored
(v1.0-B1). Everything else is minor.

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| *Done when*: status-transition tests cover every FR-10.35 rule on synthetic data | existing + new | PASS | `tests/unit/test_fix_tracking.py` (37: Improving ≤ 75%, Fixed 2-in-a-row + ≥ 75% over ≥ 20, streak reset, puzzles alone never Fixed, no-theme weakness by game rate, Regressed from Fixed and Improving, not from New/Training, Regressed stays until it improves, guard). New, through real checkpoints: `test_qa_v10_checkpoints.py::test_qa_one_weakness_goes_improving_fixed_then_regressed_and_back_to_the_top`, `::test_qa_perfect_puzzles_never_make_a_weakness_fixed_while_the_games_dont_improve`, `::test_qa_without_the_puzzle_gate_two_clean_checkpoints_stay_improving` |
| *Done when*: a checkpoint runs end to end on recorded data and its report shows under **Since last report** | existing | PASS | `test_checkpoints.py::test_run_now_saves_a_checkpoint_with_a_normal_coach_report`, `::test_the_report_shows_under_since_last_report`; e2e `test_progress_ui.py::test_a_checkpoints_report_opens_in_the_report_tab` |
| *Done when*: a due schedule runs while open or at the next launch; does nothing with no new games | existing + new | PASS | `test_checkpoints.py::test_a_due_schedule_runs_while_the_app_is_open`, `::test_a_due_schedule_with_no_new_games_does_nothing`; new `test_qa_a_weekday_schedule_that_came_due_while_closed_runs_at_the_next_launch` (weekday kind, at launch, hourly re-check, due again a week later) |
| *Done when*: a checkpoint never changes your training plan | existing | PASS | `test_checkpoints.py::test_a_checkpoint_never_touches_your_plan` (plan tables byte-identical) |
| *Done when*: fresh clone → `setup.py` → working app through the wizard, fresh and restoring a v0.16 backup | **run by hand** (temp clone, temp data folders) + new smoke | PASS (on Adam's own Windows profile, not a clean one) | See *Fresh clone* below; `tests/smoke/test_qa_v10_real_app.py::test_qa_restore_a_v016_backup_from_the_wizard_then_finish_into_the_app` |
| FR-10.32 count trigger (fires at N, not N−1; after a sync; at launch) | existing + new | PASS | `test_the_count_trigger_fires_at_n_new_games_not_before`, `test_launch_runs_a_checkpoint_that_came_due`; new `test_qa_the_count_trigger_is_wired_to_a_sync_that_brought_games`, `test_qa_a_sync_with_no_new_games_never_starts_one` |
| FR-10.32 eligibility (linked accounts, filters, never another player) | existing | PASS | `test_another_players_games_never_count`, `test_unrated_and_blitz_games_arent_eligible_by_default` |
| FR-10.32 Run checkpoint now; one at a time; Coach run puts it off | existing + new e2e | PASS | `test_one_checkpoint_at_a_time`, `test_a_coach_run_going_puts_the_checkpoint_off`; e2e `test_qa_run_checkpoint_now_twice_quickly_starts_one` |
| FR-10.33 normal report, metrics, statuses, mix rebuilt, plan untouched | existing | PASS | `test_checkpoints.py` (above), `test_filters_you_changed_get_the_banner_not_replaced` |
| FR-10.34 window, frozen baseline, guard (Adam's rule) | existing + new | PASS | unit guard tests; new `test_qa_a_guarded_weakness_keeps_its_status_through_a_real_checkpoint` |
| FR-10.34 backfill (points, statuses = live rules, no reports, once, resumes, < 50 skipped) | existing | PASS | `test_checkpoint_backfill.py` (10); real app: backfill key set after first launch and after a wizard restore |
| FR-10.36 game health | existing | PASS | `test_game_health_has_rates_cp_loss_by_phase_and_latest_ratings`; e2e health charts |
| FR-10.37 AI summary: auto only under cap and budget, else Get AI take; aggregates only; never on backfill; on by default | existing | PASS | `test_checkpoint_ai.py` (8); e2e `test_settings_are_saved_and_bad_ones_refused` (on by default) |
| FR-10.38 Progress tab: cards, baseline line, hollow guarded points, lower-is-better titles, reasons, examples, history, notices, empty state, Stats link | existing + new e2e + visual | PASS with B3, B4 | `test_progress_ui.py` (10); new screenshots light/dark; `test_qa_b3_…` / `test_qa_b4_…` (xfail) |
| FR-10.29 statuses in the Suggested mix (Regressed first, maintenance share, label) | existing + new | PASS | `test_suggested_mix_statuses.py` (5); new end-to-end check that a Regressed weakness leads *Why this mix* and the Progress page |
| FR-10.72 every new option has a tooltip | existing | PASS | `test_v012_tooltips.py` Progress walk (in the e2e run) |
| NFR-8 first-run wizard (shown/not shown, steps from facts, resumable, finish once) | existing + new | **FAIL (B1)** | `test_setup_core.py`, `test_setup_wizard.py`, `test_wizard_ui.py`, `test_real_app_v10.py`; new `test_qa_v10_ui.py` (refused restore B1, cancel, not-a-backup, finish refused early) |
| FR-15.4 restore from the wizard → restart → resumes past Welcome | new smoke + fresh clone | PASS (happy path); B1 on refusal/failure | `test_qa_restore_a_v016_backup_from_the_wizard_then_finish_into_the_app` |
| NFR-8 release from source; User Guide *First run*, *Installing*, *Updating*, *Troubleshooting* | run + read | PASS with B5 | Fresh clone, `setup.py` re-run as an update; docs check below |

## Bugs

| ID | Severity | Steps | Expected | Actual | Evidence |
|---|---|---|---|---|---|
| **v1.0-B1** | **major** | Fresh install → wizard → **Restore from a backup…** → pick a file → **Restore and restart** while anything runs in the background (e.g. the sync at launch or an analysis), **or** the restore job fails its full check (a damaged file whose manifest reads fine), **or** the swap at the restart fails (data put back) | Nothing restored, nothing recorded: the wizard stays on Welcome (Start fresh / Restore) with the reason shown | `WizardView.restore()` calls `chooseSetup("restore")` **before** `restoreBackup()`, and nothing undoes it. Refused: the error shows, but `setup.choice` is now `"restore"`, so at the next start (or any re-read of the setup state) Welcome is skipped for good. Job failed: `Welcome`'s effect calls `onChanged()`, the step jumps to Puzzles/Stockfish/Lichess and the error alert unmounts with Welcome, so **the failure is never seen**. With no puzzle database the next step even says *"Your data is restored"* (green), also after a failed swap, beside the red restore notice. Restore can then only be done from Settings | `tests/e2e/test_qa_v10_ui.py::test_qa_b1_a_refused_restore_leaves_no_restore_choice_behind` (xfail strict): after the refusal `getSetupState()` returns `step: "puzzles", choice: "restore"`. Failed-job path from `web/src/views/WizardView.tsx` lines 22–24, 38–39, 140–146 (the mock can't fail a restore job) |
| **v1.0-B2** | minor (gate) | `uv run ruff format --check .` (Developer Guide command; a CI step) | Clean | `1 file would be reformatted`: `tests/smoke/conftest.py` line 184 (builder's v1.0 change to `finish_wizard`). Pre-commit has no ruff hook. CI would be red, which the checkpoint gate forbids (same as v0.16-B8) | command output |
| **v1.0-B3** | minor | Progress tab, a weakness no puzzle theme trains (*Mistakes under 10% of your clock*, an opening) | No puzzle line (the accuracy chart is already hidden), or "not trained by puzzles" | The card says *"Puzzles: — first try over 0 tries · Why you missed it: …"* | `test_qa_b3_a_weakness_no_puzzle_trains_has_no_puzzle_line` (xfail strict); `tests/e2e/artifacts/qa-v10-progress-history-light.png` |
| **v1.0-B4** | minor (visual; relevant to Adam's two-chart decision) | Progress tab, any card with both charts | The two charts "share the time axis" (FR-10.38 v1.0 note): each checkpoint at the same x in both, so dates and the shaded rebuilt stretch line up | The rate chart has a 56 px right margin (room for the *Start* label), the accuracy chart 16 px, so the same checkpoint sits ~40 px apart (1280-wide window) and the shaded band ends at different places in the two charts of one card | `test_qa_b4_a_cards_two_charts_put_each_checkpoint_at_the_same_x` (xfail strict); `qa-v10-progress-same-day.png` (last points at x≈563 vs ≈603) |
| **v1.0-B5** | minor (doc) | Read the new CHANGELOG lines and Troubleshooting | US spelling (Adam's rule) | CHANGELOG `[Unreleased]`: *"Checkpoint reports are **labelled** …"*; User Guide Troubleshooting: *"A **cancelled** or failed import…"*. (Older lines also say "labelled"; only the v1.0 ones are filed.) | `CHANGELOG.md` line 25; `docs/USER_GUIDE.md` line 1485 |
| **v1.0-B6** | minor | Read FR-10.38 against the build | REQUIREMENTS and the build agree | FR-10.38 still says *"a trend line across checkpoints (game rate and puzzle accuracy **on the same chart**)"* in its main sentence; only the sub-bullet added at the build says two charts. If Adam confirms two charts at his manual test, the main sentence needs updating; if not, the UI does | `REQUIREMENTS.md` FR-10.38 |

Notes, not filed (for Adam to judge):
- **Puzzle accuracy may count a solve twice.** FR-10.34 adds local attempts and the Lichess dashboard's `nb`/`firstWins` per theme. Solves the app pushes to Lichess are likely in the dashboard too, so the Fixed gate's "at least 20 tries" could be met with about 10 real ones, and a puzzle with two of the weakness's themes counts twice in the dashboard part. The Coach has summed them the same way since v0.10 (FR-10.15); v1.0 makes it gate a status. Not verifiable without a live account.
- **First v1.0 start with fewer than 50 analyzed games but ≥ 10 eligible ones:** no backfill, so the next check (an hour later, or the next sync) runs the first live checkpoint, which analyzes up to 50 games for the baseline plus the window with Stockfish, unasked. That's FR-10.32/10.33 as written ("analyzes any that aren't analyzed yet" is in the User Guide), but it can be minutes of CPU right after the upgrade.
- Two checkpoints on the same day get the same x label (*Nov 10 … Nov 10*); both points are drawn (`test_qa_two_checkpoints_on_the_same_day_are_two_points` passes).
- A Coach run can start while a checkpoint runs (the checkpoint waits for a Coach run, not the reverse). They share the analysis queue, so nothing breaks.
- A backfill cut short and resumed after **Every N games** or the window was changed resumes by position (`points[len(done):]`), so its later points follow the new spacing. Rare (settings change during the first start's backfill).

## Tests added
- `tests/integration/test_qa_v10_checkpoints.py` (7 pass): one weakness New→Training→Improving→Fixed→Regressed through real checkpoints with the puzzle gate, notices for Improving→Fixed and Fixed→Regressed, Regressed first in *Why this mix* and on the Progress page; perfect puzzles never make Fixed; one try short of the gate stays Improving; weekday schedule due while closed runs at launch; count trigger wired to the library's sync hook; a sync with no new games starts nothing; a guarded weakness keeps its status.
- `tests/e2e/test_qa_v10_ui.py` (10 pass, 3 xfail): B1, B3, B4 (xfail strict); Restore cancelled; not-a-backup refused then Start fresh; finish refused early; Run checkpoint now double click; two checkpoints on one day; screenshots of every wizard step, the Progress tab (history, settings, empty) and the status notice, light and dark.
- `tests/smoke/test_qa_v10_real_app.py` (1 pass): the real app, a v0.16 backup (schema 14, "0.16.0") restored **from the wizard** through the native Open dialog → restart → notice → wizard past Welcome → finish → the backup's data, migrated to v1.0, `setup.finished`, backfill done.

## Fresh clone (*Done when*)
On this PC (Adam's Windows profile, not a clean one, which stays Adam's manual test):
1. `git clone --branch v1.0` of the local repo into a temp folder.
2. `WEAKSQUARE_DATA_DIR=<temp>\data-fresh`, then `python scripts/setup.py --no-shortcut` (system Python 3.15; `--no-shortcut` so the real Start-menu and desktop shortcuts weren't replaced). Every step ran: uv sync, npm, front-end build, Playwright, pre-commit, the **full puzzle download from Lichess** (6,193,530 puzzles, export of 2026-11-01, import 451 s) and the **real Stockfish 19 download** (SHA-256 checked). Exit 0.
3. The clone's own app (`.venv\Scripts\python.exe -m weaksquare --dev`, CDP port, same data folder): wizard at **Welcome** → Start fresh → straight to **Lichess** (puzzles and Stockfish already done) → Continue without signing in → **Start training** → *4,861,540 puzzles match*. Relaunch: no wizard.
4. A second temp data folder, `setup.py` again (full download and Stockfish again), then **Restore from a backup…** with a v0.16 backup (native Open dialog driven over Win32) → *Made Nov 2, 2026 … by WeakSquare 0.16.0: 0 games, 3 puzzle attempts …* → Restore and restart → the app relaunched itself, showed the restore notice, wizard at **Lichess** → finish → the app. `user.db`: the backup's marker and 3 attempts, migrated from 14 (`backups\user-14-….db` and `before-restore-….zip` kept), `setup.choice "restore"`, `setup.finished true`, `checkpoints.backfill_version 1`. Relaunch: no wizard.
5. *Updating*: `git pull` + `setup.py` again on the first folder: *puzzle database already imported … skipping*, *already installed: Stockfish 19 (nothing to do)*, exit 0.
The v0.16 backup was made with today's `make_backup` (format unchanged since v0.16: `git diff v0.16..HEAD` touches only the PC-only prefix list) over a `user.db` migrated with 0001–0014 only and app version "0.16.0".

## Scope, architecture, security
- Nothing from v1.1+ built; ROADMAP v1.2–v1.6 text only. No placeholder code or dead UI.
- `core/fix_tracking.py` and `core/setup.py`: no I/O, no `datetime.now()`, `time.time()` or global random; services use the injected clock. `CheckpointService` and `SetupService` take protocols; `CheckpointsRepo`, `has_user_data` are wired only in `app.py`.
- Migration `0015_checkpoints.sql` is new; no applied migration edited. No dependency added (`pyproject.toml`/`package.json` change only the version; lockfiles committed).
- 9 new bridge methods use `@bridge_call` and are in the allowlist test (passes). No localStorage/sessionStorage/IndexedDB/cookies in `web/src`. `keyring` only in `secret_store.py`. The CDP port is set only by the test harness (`app.py` refuses it outside `--dev`).
- Secrets: no token/key patterns in the diff or my tests (placeholders only); gitleaks passes. The AI summary prompt is aggregates only (builder's `test_the_summary_prompt_has_aggregates_only`). My fixtures use invented ids only.

## Docs findings
- `python scripts/check_docs.py --strict`: `check_docs: 0 error(s), 0 warning(s) [version v1.0]`.
- Developer Guide Commands table run as written (see Commands). None calls a `.ps1`, bare `npm`/`npx` or venv activation. `ruff format --check .` fails (B2). The new *Make a release* row matches NFR-8 (no packaged installer); not run (after sign-off).
- User Guide followed: *First run* (fresh clone, both paths: labels, order, "already done" steps, restore notice, never again), *Installing from source* / *Updating* (setup re-run skips what's there), *Tracking your progress* (against the mock: statuses table, Start line, hollow points, shaded rebuilt points, Checkpoints table, settings defaults 10 / 30 / Off / rated rapid+classical / 75-50-90 / 2-75-20 / AI on / notices on, all match), *Troubleshooting* (the front-end-not-built message, About → Logs folder exist as described). Spelling: B5.
- CHANGELOG `[Unreleased]` covers every user-visible *Done when* item (checkpoints, statuses, backfill, Progress tab, settings, notices, AI summary, mix, wizard, docs). README status reads v1.0 release candidate. Privacy section covers checkpoints' sync and the AI summary. FR-10.38 wording: B6.

## Visual check
`tests/e2e/artifacts/qa-v10-*.png`: every wizard step and the restore confirmation, the Progress tab with history, its settings open, empty, and the status notice, light and dark; the clone runs' screenshots stayed in the scratch folder. No clipping or overlap; dark mode readable. Findings: B3, B4.

## Commands

| Command | Result |
|---|---|
| `uv run pytest` (with `-p no:cacheprovider`) | **4149 passed**, 1 skipped, 2 xfailed (28:57, beside the clone's setup). Collected before my file existed; mine ran separately: **7 passed** (with the allowlist test: 10 passed). The known flakes passed |
| `uv run pytest -m e2e` | **599 passed, 3 xfailed** (19:14): my 10 pass, B1/B3/B4 xfail strict |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **91 passed**, 1 skipped (22:48), the builder's `test_real_app_v10.py` (2) and my `test_qa_v10_real_app.py` included |
| `uv run pytest -m fulldb` | 76 passed, 3 xfailed (pre-existing QA markers) (9:04), on the dev data folder's full `puzzles.db`, read-only |
| `uv run pytest -m engine` | 26 passed (1:34), the dev data folder's Stockfish, read-only |
| `uv run ruff check .` / `uv run ruff format --check .` | clean / **1 file would be reformatted (B2)**; mine formatted |
| `uv run mypy src` | no issues in 163 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean |
| `uv run pre-commit run --all-files` | all hooks passed (gitleaks, keyring hook) |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `python scripts/setup.py` | run in the temp clone with `WEAKSQUARE_DATA_DIR` and `--no-shortcut` (3 times: two fresh folders, one update), exit 0 each; see *Fresh clone* |
| `uv run python scripts/fetch_stockfish.py --dev` | *already installed: Stockfish 19 (nothing to do)* |
| `uv run python scripts/fetch_puzzle_db.py --dev` | not run as written (it would re-download into your dev folder); the same script ran twice through `setup.py` into temp folders with the full download |
| `uv run python -m weaksquare --dev`, `npm.cmd … run dev` modes | the real app ran from the clone and in the smoke suite; dev-server modes unchanged since v0.16, not rerun |
| `uv run pytest -m docs_screenshots`, live commands, *Make a release* | not run: screenshots are the builder's handoff step; live tests need your credentials; the release is after sign-off |

## For Adam's manual test
- **Two charts per weakness card** instead of one (your decision to confirm): see `qa-v10-progress-history-light.png`. If you keep two, consider B4 (they don't line up) and B6 (FR-10.38's main sentence).
- The clean-Windows-profile run of `setup.py` → wizard (I ran it on your profile with temp data folders and `--no-shortcut`, so the Start-menu/desktop shortcuts weren't exercised).
- Signing in to Lichess from the wizard (skipped in all my runs: no credentials).
- A real checkpoint on your games: the first start of v1.0 on your data runs the backfill (how long, and do the rebuilt statuses look right?), then a live one after 10 games; check the AI summary appears only under your cap and budget.
- B1: after a refused or failed restore in the wizard, close and reopen: you'll land past Welcome.
