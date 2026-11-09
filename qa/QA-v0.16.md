# QA report: v0.16 (Backup and restore)

# Round 2, 2026-11-09: re-verification at `83000f6` (fixes for B1-B10)

Same rules as round 1: I changed only `tests/` and this report. No credentials, no `-m live`, temp data folders only.
`-m docs_screenshots` rewrote one image (see Commands); I put the committed one back, so `docs/` is unchanged.

## Verdict: **PASS WITH ISSUES** (1 new minor; no blocker or major)

All ten round 1 bugs are fixed, B3 (the major) included. Trying to break the fixes turned up one minor gap in B1's class
(B11): a zip whose "version needed to extract" is unsupported makes `zipfile.ZipFile()` itself raise
`NotImplementedError`, which `_open` doesn't catch. It's refused with *Something went wrong* instead of the reason;
nothing changes, and retention skips it. No regressions.

## Re-verified

| Bug | Result | How |
|---|---|---|
| B1 (minor) | **FIXED** (gap: B11) | Round 1's 5 tests pass unmarked. Fuzzing: 600 single-byte changes (test) and 3,000 1–4-byte changes (scratch run) over a real backup: 2,947 *damaged*, 40 *not a backup*, 10 accepted (bytes that don't matter, e.g. timestamps), **3 crashes**, all `NotImplementedError: zip file version N` from the `ZipFile` constructor (B11) |
| B2 (minor) | **FIXED** | Round 1 test passes. New: a complete staged file with no manifest is discarded with *"The last restore didn't finish, so nothing was changed…"*, your data stays, and no before-restore copy is made; a manifest truncated by a crash mid-write is treated the same |
| B3 (major) | **FIXED** | Round 1 test passes: one backup in 5 ticks beside the damaged file, which survives. The backup is recorded before pruning, so a prune that fails can't make it due again. The B11 file also survives retention (`test_qa_r2_b11_retention_survives_it`) |
| B4 (minor) | **FIXED** | Round 1 test passes. New: a header that **lies small** (100 bytes, exactly 64 KB, 64 KB − 1) over an 80 MB manifest is refused with a peak under 8 MB; a header that lies big (1 GB) on a small manifest is refused; a `user.db` header that lies by −1 / +1 / +1 MB, with a manifest that agrees with it, is *damaged* and nothing is staged |
| B5 (minor) | **FIXED** | Round 1 test passes. New: a crash between the two renames (no `user.db`, a `.replaced`) puts your data back; with the staged restore still complete, that start then finishes the restore, and the before-restore copy holds **your** data (not nothing); with no staging left, only the recovery happens |
| B6 (minor) | **FIXED** | Round 1's two tests pass. New: clock 300 days **ahead** → backup → clock fixed: one backup due at once, then none until a week later; 4 normal weeks with keep 3 leave 3 real backups plus the future-dated one, untouched. Clock 200 days **behind** then right: 3 backups, no burst. Clock a year behind with 3 correct backups and keep 1: none of the three is deleted |
| B7 (minor) | **FIXED** | Round 1's 3 tests pass. **Real app** (new): data folder `C#dev %41 data` opens `puzzles.db` (match count shows), and a restore staged there is swapped in at the next start with its before-restore copy. The CHANGELOG has a **Fixed** line, since it's older than v0.16 |
| B8 (minor) | **FIXED** | `uv run ruff format --check .`: 529 files already formatted |
| B9 (doc) | **FIXED** | ROADMAP now says the text beside **Back up now** says so |
| B10 (wording) | **FIXED** | Notice: *"Sign-ins and AI keys aren't part of a backup: on a new PC, sign in to Lichess again…"*; User Guide step 4 says on the same PC you stay signed in. Real-app notice still found by both smoke tests |

## New bug

| ID | Severity | Steps | Expected | Actual | Evidence |
|---|---|---|---|---|---|
| **v0.16-B11** | minor | Restore from a zip whose central directory gives a "version needed to extract" above 6.3 for either member (set the byte at offset 6 of its central header to 88) | *"This backup is damaged"* or *"isn't a WeakSquare backup"* | `zipfile.ZipFile()` raises `NotImplementedError("zip file version 8.8")` while reading the directory; `_open` catches only `BadZipFile`, `OSError`, `ValueError`, so the bridge returns *Something went wrong* (code `internal`). Nothing changes, and `list_backups` now skips such a file, so retention is safe. Catching `READ_ERRORS` (or `Exception`) around the constructor fixes it | `tests/integration/test_qa_v016_round2.py::test_qa_r2_b11_an_unsupported_zip_version_is_refused_not_a_crash[manifest.json / user.db]`, `::test_qa_r2_b11_the_bridge_names_the_reason` (xfail); found by 3 of 3,000 fuzzed files |

Notes, not filed:
- `recover_interrupted_swap` deletes `user.db.replaced` whenever `user.db` also exists. If a rollback's `_remove_db(user_db)` itself failed (a locked file), the `.replaced` one would be your original and is deleted at the next start; the before-restore zip made before the swap still holds it, so nothing is lost.
- `readonly_uri` on a UNC data folder (`\\server\share`) gives `file://server/share/…`, which SQLite reads as a URI authority. Unchanged from before v0.16, and not a supported setup.
- `docs_screenshots` re-rendered `stats-reasons.png` with the **Why you missed** tab's hover shade (the pointer was left over it); the committed image has none. A capture flake, not a product change.

## Tests added this round
- `tests/integration/test_qa_v016_round2.py` (16 pass, 3 xfail): lying manifest headers (4), lying `user.db` headers (3), 600-case fuzz with retention listing, staged file with no or a truncated manifest, crash between the renames (with and without staging), clock ahead/behind/right, clock behind with retention; B11 (3 xfail) and B11 retention (passes).
- `tests/smoke/test_qa_real_app_v016.py::test_qa_r2_b7_the_real_app_runs_and_backs_up_in_a_data_folder_with_hash_and_percent`.

## Commands at `83000f6`

| Command | Result |
|---|---|
| `uv run pytest` | **4019 passed**, 1 skipped, 2 xfailed (24:22), my round 1 file and the builder's new tests included. My round 2 file ran separately: **16 passed, 3 xfailed** |
| `uv run pytest -m e2e` | **574 passed** (17:46) |
| `uv run pytest -m docs_screenshots` | **53 passed** (2:30); only `docs/img/stats-reasons.png` differed (hover shade, see notes); restored |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **87 passed**, 1 skipped, **1 failed** (21:10): `test_qa_v012_round2_real_app.py::test_qa2_the_new_tags_filter_link_and_hand_tick_in_the_real_app` (the journal entry was saved without its task link, `None == 7`). That file re-run alone 3 times: **3 passed** each time. It runs no v0.16 code (v0.12 journal), so I count it as a timing flake. `test_real_app_v016.py` (2) and my `test_qa_real_app_v016.py` (2) passed |
| `uv run ruff check .` / `uv run ruff format --check .` | clean / 529 files already formatted |
| `uv run mypy src` | no issues in 158 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean (exit 0) |
| `uv run pre-commit run --all-files` | all hooks passed |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings |

---

# Round 1, 2026-11-09, at `fc471d3` (branch `v0.16`)

I changed only `tests/` and this report. No credentials, no `-m live`, no network requests, no default data folder
(every test and real-app run used a temp folder through `WEAKSQUARE_DATA_DIR` or `config.Paths(tmp)`). I didn't run
`uv run pytest -m docs_screenshots` (it rewrites `docs/img/`), `scripts/setup.py` (it installs shortcuts) or
`fetch_puzzle_db.py` / `fetch_stockfish.py` (network); none of them changed in v0.16.

## Verdict: **FAIL** (1 major, 9 minor; no blocker)

Every *Done when* item has passing evidence, and the whole restore works in the real window (driven through the native
Open dialog, see below). The verdict is FAIL because of one major: a damaged old backup in the automatic-backup folder
makes pruning crash, and from then on a new backup is written **every minute** and none is ever deleted (B3). It shares a
root cause with B1 (`zipfile` errors other than `BadZipFile`/`OSError` escape as crashes). Both are small fixes. The other
eight are minor, and one of them (B8) also keeps the checkpoint gate shut: `ruff format --check .` fails, so CI would be
red.

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| Done when: back up and restore into an empty folder gives the same data, every user table row for row | integration | PASS | `test_backup_and_restore_into_an_empty_folder_gives_the_same_data` (generic over `sqlite_master`); new: `test_qa_a_staged_restore_into_a_folder_with_no_user_db_saves_nothing_aside`, `test_qa_an_uncompressed_backup_is_accepted` |
| Done when: a backup taken while the app writes is consistent, passes integrity check | integration | PASS | `test_a_backup_taken_while_the_app_writes_is_consistent` (writer thread, 3 backups, each staged with CRC, SHA-256 and integrity checks) |
| Done when: not a backup / damaged / newer schema refused with a message, nothing changes | integration, e2e, new | **PASS with B1** | `test_bad_files_are_refused_and_nothing_changes` (9 kinds); new: `test_qa_zips_with_odd_member_names_are_not_backups` (9 layouts: duplicate, `sub/`, `../`, `..\`, `/`, `C:/`, upper case, dir entry), `test_qa_a_manifest_that_lies_about_the_size_is_damaged`, `test_qa_a_valid_sqlite_file_that_isnt_a_weaksquare_db_is_damaged`, `test_qa_a_newer_backup_is_refused_by_inspect_with_the_nfr3_message`. Nothing changes in every case, including B1's. **B1:** a broken deflate stream or an encrypted member gives *Something went wrong*, not the reason |
| Done when: an older-schema backup is restored and migrated | integration | PASS | `test_an_older_schema_backup_is_restored_and_migrated` (fixture built at migration 10) |
| Done when: current `user.db` copied aside before a restore | integration, real app (new) | PASS | `test_restore_saves_the_current_data_first_and_that_copy_undoes_it`, `test_before_restore_copies_keep_only_the_last_five`; new: `test_qa_a_wal_left_by_a_crash_is_saved_aside_and_not_applied_to_the_restored_db`; real app: `test_qa_restore_through_the_ui_restarts_the_real_app_and_swaps_the_data` (one `before-restore-*.zip`) |
| Done when: no credential ever in a backup | integration | PASS | `test_a_backup_holds_no_credential` (placeholders, UTF-8 and UTF-16); new: `test_qa_no_setting_in_a_backup_looks_like_a_secret` (no secret-shaped key, value or table) |
| Done when: automatic backup due runs while open or at next launch, keeps only N, reports a missing folder | integration, e2e, new | **PASS with B3, B6** | `test_automatic_backup_runs_when_due_and_keeps_only_n`, `test_an_automatic_backup_that_came_due_while_closed_runs_at_launch`, `test_a_missing_folder_is_reported_and_retried`, `test_a_missing_folder_is_shown_not_silent`; new: `test_qa_retention_never_touches_files_that_arent_ours` (8 look-alikes incl. a folder named like a backup), `test_qa_the_clock_jumping_forward_makes_one_backup_not_many`. **B3** (major), **B6** (clock set back) |
| FR-15.1 Back up now: Save dialog, dated name, checked copy, never changes anything | integration, e2e, new | PASS | `test_a_backup_never_changes_user_db`, `test_bridge_backup_now_suggests_the_dated_name_and_cancel_does_nothing`, `test_back_up_now_says_it_isnt_encrypted_and_reports_what_it_saved`; new: `test_qa_back_up_over_an_existing_file_replaces_it_atomically`, `..._onto_a_folder_named_like_the_file_fails_with_a_message`, `..._onto_a_read_only_file_fails_with_a_message`, `test_qa_a_name_without_zip_gets_zip_and_never_overwrites_user_db`, `test_qa_a_long_path_backup_either_works_or_fails_with_a_message`, `test_qa_unicode_and_odd_folder_names_back_up_and_restore` (**B7** for `#` / `%`) |
| FR-15.2 PC-only settings keep this install's values | integration, real app (new) | **PASS with B2** | `test_pc_local_settings_keep_this_installs_values`; real app: the old PC's `backup.auto` folder doesn't come across. **B2:** not when the staged file has no manifest |
| FR-15.3 off by default, weekly, keep 5, tooltips | integration, e2e | PASS | `test_automatic_backups_are_off_by_default`, `test_automatic_backups_ask_for_a_folder_and_show_the_next_one`, `test_changing_the_settings_replaces_the_timer`; `test_v012_tooltips.py` passes in the full e2e run |
| FR-15.4 shows date, version, counts; Replace my data only after confirming | e2e, real app (new) | PASS | `test_restore_shows_whats_in_it_and_replaces_only_after_you_confirm`; new: `test_qa_restore_choose_is_disabled_while_the_restore_runs_and_replace_fires_once` (double click → one call), `test_qa_cancelling_the_open_dialog_changes_nothing`, `test_qa_a_restore_that_fails_its_full_check_shows_the_reason_and_lets_you_choose_again` (the mock never fails a restore job, so this branch had no test) |
| FR-15.4 refused while jobs run, naming them | integration, e2e, new | PASS | `test_restore_is_refused_while_a_job_runs`, `test_restore_while_a_job_runs_names_it`; new: `test_qa_restore_is_refused_while_any_job_runs_and_nothing_is_staged` (backup, sync, explain, unknown kind), `test_qa_a_second_restore_and_backup_during_a_restore_are_refused` |
| FR-15.4 restart, swap at startup, rollback on failure | integration, real app | **PASS with B2, B5** | `test_a_swap_that_fails_partway_puts_the_original_back`, `test_save_aside_failing_means_nothing_is_restored`, `test_restore_stages_then_restarts`; smoke `test_a_staged_restore_is_swapped_in_at_the_next_real_start`, `test_after_restore_waits_for_the_old_window_to_let_go`; new: `test_qa_a_half_written_staged_db_from_an_interrupted_restore_is_not_kept` (also probed at 5–99 % truncation: migrate fails, original put back each time), `test_qa_a_leftover_manifest_without_a_staged_db_is_removed_and_nothing_changes`, `test_qa_a_restore_interrupted_during_migration_leaves_a_working_db`. **New real-app end to end:** `tests/smoke/test_qa_real_app_v016.py` |
| FR-15.4 bridge: no path from the page, one-time token | integration | PASS | `test_bridge_restore_needs_the_token_from_the_open_dialog`, `test_bridge_backup_settings_need_an_absolute_folder`; allowlist test passes |
| FR-15.5 not encrypted, said beside Back up now; never uploaded | e2e, code | PASS | `test_back_up_now_says_it_isnt_encrypted_...`; no HTTP import in `core/backup.py`, `adapters/backup_files.py`, `services/backup.py` |
| Restore notice after the restart | e2e, real app | PASS (wording: B10) | `test_the_notice_after_the_restart`, `test_the_notice_shows_even_when_the_app_opens_on_the_import_screen`; real app (new) |
| Docs: User Guide chapter, privacy section | read, followed against mock and real app | PASS with B9, B10 | see Docs findings |

## Bugs

| ID | Severity | Steps | Expected | Actual | Evidence |
|---|---|---|---|---|---|
| **v0.16-B3** | **major** | Turn on automatic backups into a folder that holds an older backup named `weaksquare-backup-<date>.zip` whose `manifest.json` is damaged (bit rot on a USB stick: a broken deflate stream; or an encrypted member, or Deflate64) → wait | One backup per interval; the damaged file is skipped by retention (as `list_backups` intends) | `list_backups` catches only `BackupError`/`OSError`, so `zlib.error` (or `RuntimeError`, `NotImplementedError`) escapes `prune`. `_run_auto` treats that as a failed backup: it sets *"The last automatic backup couldn't be saved"* (false: it was saved) and doesn't record `backup.last_auto_at`, so it's still due, and the timer (minimum 60 s) runs it again. Result: **a new full backup every minute, none ever deleted**, until the drive fills. 5 timer ticks → 5 backups | `tests/integration/test_qa_v016_backup.py::test_qa_b3_a_damaged_old_backup_in_the_folder_doesnt_make_a_backup_every_minute` (xfail). Suggest: catch every exception per file in `list_backups` (or fix B1 in `read_manifest`), and record the backup as made once `make_backup` succeeds, whatever `prune` does |
| **v0.16-B1** | minor | Restore from a backup whose `user.db` or `manifest.json` deflate stream is broken (1 bit flipped: 5 of 200 random flips in `user.db`, 23 of 100 in the manifest gave this), or that has an encrypted member | *"This backup is damaged…"* or *"isn't a WeakSquare backup"* (FR-15.4, Done when: refused **with a message**) | `zlib.error` / `RuntimeError` aren't caught in `read_manifest` / `extract_db`, so the bridge returns *"Something went wrong. The details are in the log file"* (code `internal`) and the restore job fails the same way. Nothing changes and the staged file is removed, so no data risk. ARCHITECTURE §7 says all such errors are `BackupError` | `test_qa_b1_a_broken_deflate_stream_is_damaged_not_a_crash[user.db / manifest.json]`, `test_qa_b1_an_encrypted_member_is_refused_not_a_crash[x2]`, `test_qa_b1_the_bridge_names_the_reason_for_a_broken_backup` (all xfail) |
| **v0.16-B2** | minor | The restore job is killed after `extract_db` wrote `user.restore.db` but before `carry_pc_settings` and the manifest (close the app during a long *Checking the backup…*: `cancel_all` waits 10 s, then the daemon thread dies) → start the app | The staged file isn't used without its manifest (the manifest is written last, so it's the natural commit marker), or it's re-checked | `apply_staged_restore` swaps in `user.restore.db` whenever it exists. A complete file brings the **other PC's** `backup.auto` folder, `lichess.account`, engine path etc. A half-written one is safe in practice (migrate fails and the original is put back: probed at 5–99 %), but the notice then says the restore *didn't finish*. The Developer Guide says "delete both to cancel", which covers only both files | `test_qa_b2_a_staged_db_without_a_manifest_never_brings_another_pcs_settings` (xfail); `test_qa_a_half_written_staged_db_from_an_interrupted_restore_is_not_kept` (passes) |
| **v0.16-B4** | minor | Choose a crafted backup whose `manifest.json` is 80 MB of spaces (under 1 MB on disk) | Refused after reading at most 64 KB (`MANIFEST_MAX_BYTES`) | `read_manifest` calls `zf.read(MANIFEST_NAME)` and checks the length afterwards: peak 199 MB of memory to refuse it. A larger one could exhaust memory. Checking `getinfo(MANIFEST_NAME).file_size` (or reading 64 KB + 1) first fixes it | `test_qa_b4_a_huge_manifest_is_refused_without_reading_it_all` (xfail) |
| **v0.16-B5** | minor | Kill the app during the startup migration after a restore swap (or let the rollback's `_remove_db` fail) → start again | `user.db.replaced` is cleaned up (the data is already saved as `before-restore-*.zip`) | `user.db.replaced`, a full copy of the old data, stays in the data folder until the next restore. No data loss: the restored DB opens and migrates (`test_qa_a_restore_interrupted_during_migration_leaves_a_working_db` passes) | `test_qa_b5_a_leftover_replaced_file_is_cleaned_up_at_the_next_start` (xfail) |
| **v0.16-B6** | minor | The PC clock is wrong (ahead) when an automatic backup runs, then it's corrected | Automatic backups go on weekly | `backup.last_auto_at` is in the future, so `next_due` is that time + 7 days: **no automatic backup until then** (200 days ahead → none for 207 days), with *Next automatic backup* showing that date. Retention sorts by `created_at`, so the future-dated file is always "newest" and is kept forever while the real ones are deleted: with **Keep the last 2** only one real backup survives | `test_qa_b6_the_clock_set_back_doesnt_stop_automatic_backups`, `test_qa_b6_retention_keeps_the_newest_real_backups_after_a_clock_mistake` (xfail) |
| **v0.16-B7** | minor (since v0.1) | Data folder path containing `#` or `%41` (e.g. a Windows user named `C#dev`) → Back up now | Works | `readonly_uri` builds `file:<path>?mode=ro` without percent-encoding, so SQLite cuts the path at `#` (or decodes `%41`): `check_db` raises → *"This backup is damaged"* on every backup and restore. The same helper opens `puzzles.db` and runs `read_version` at startup, so such a profile likely can't run the app at all; v0.16 adds two more callers | `test_qa_b7_check_db_works_in_a_folder_with_uri_characters`, `test_qa_unicode_and_odd_folder_names_back_up_and_restore[with#hash / with%41percent]` (xfail). Unicode, spaces, brackets, `&` and nested folders pass |
| **v0.16-B8** | minor (gate) | `uv run ruff format --check .` (Developer Guide command; also a CI step) | Clean | `3 files would be reformatted`: `tests/e2e/test_backup_ui.py`, `tests/e2e/test_docs_screenshots.py`, `tests/unit/test_backup_core.py` (builder's v0.16 files). Pre-commit has no ruff hook, so it didn't catch it. CI would be red, which the checkpoint gate forbids | command output |
| **v0.16-B9** | minor (doc) | Read ROADMAP v0.16 *Privacy* bullet | Matches FR-15.5 (changed at build: the text sits beside **Back up now** because the Save dialog can't carry it) | Still says "and the **save dialog** says so" | `ROADMAP.md` v0.16 section |
| **v0.16-B10** | minor (wording) | Restore a backup on the **same** install (e.g. undo with `before-restore-*.zip`) | Told to sign in again only if needed | The notice always says *"Sign in to Lichess again and re-enter any AI key in Settings"*, and User Guide step 4 says the same. On the same install the sign-in and keys are still in Credential Manager (per data folder) and `lichess.account` is kept as a PC-only setting, so you're still signed in. Right for a new PC, misleading for undo | `web/src/App.tsx` line 813; User Guide *Restore from a backup* step 4 |

Notes, not filed:
- A **Back up now** file saved into the automatic folder with its default name (`weaksquare-backup-<date>.zip`) counts as an automatic backup and is deleted by retention in time. The User Guide's wording (*files named `weaksquare-backup-<date>.zip`*) covers it, but a sentence saying so would help.
- A crash exactly between moving `user.db` aside and moving the staged file in leaves no `user.db`; the next start then deletes `user.db.replaced` and finishes the restore. The data survives in the `before-restore-*.zip` made at the first attempt.
- The restore token is used up when Restore is refused because a job runs; the UI clears the confirmation too, so you choose the file again. Consistent.

## Tests added
- `tests/integration/test_qa_v016_backup.py` (35 pass, 14 xfail): odd member names (9), lying size (3 sizes), huge declared size vs free space, a non-WeakSquare SQLite file, an uncompressed zip, newer backup message; leftover manifest alone, half-written staged file, crash during migration, empty install, stale WAL saved aside; retention look-alikes, clock jumping forward; Back up now over a file, onto a folder, onto a read-only file, `user.db` as the name, long path, Unicode and odd folders; restore refused for 4 job kinds, a second restore and a backup during a restore; secret-shaped settings. xfail: B1 (5), B2, B3, B4, B5, B6 (2), B7 (3).
- `tests/e2e/test_qa_v016_backup_ui.py` (4 pass): a restore job that fails its full check, Replace double-click and the disabled button while restoring, cancelling the Open dialog, Your data at the minimum window size with screenshots.
- `tests/smoke/test_qa_real_app_v016.py::test_qa_restore_through_the_ui_restarts_the_real_app_and_swaps_the_data` (passes): the real window, Settings → Restore from a backup… → the **native Open dialog** answered over Win32 with a path in a Unicode folder → the info → Replace my data → the window closes, the app relaunches itself with `--after-restore` on the same data folder, the notice shows, the data is swapped, the old PC's automatic-backup folder didn't come across, one `before-restore-*.zip`.

## Scope, architecture, security
- Nothing from v1.0 built (no first-run wizard restore, no installer). No dead UI.
- `core/backup.py` does no I/O (`json`, `re`, `datetime` values only). Concrete adapters (`BackupFiles`, `make_backup`, `prune`, `swap_in_staged`, `relaunch`) are wired only in `app.py`; `services/backup.py` takes a `Files` protocol. No `datetime.now()`, `time.time()` or global random in `core/` or `services/`.
- No new dependency (stdlib `zipfile`, `sqlite3`): `pyproject.toml`, `uv.lock`, `web/package.json`, `package-lock.json` change only the version. No migration added or edited.
- 7 new bridge methods use `@bridge_call`, are in the allowlist test (passes), and take no path from the page (folder for settings must be absolute and NUL-free; the restore file sits behind a `secrets.token_urlsafe` token compared with `compare_digest`). No localStorage, sessionStorage, IndexedDB or cookies in `web/src`.
- Secrets: backups hold only `user.db`; the builder's test and mine find no placeholder or secret-shaped value. `keyring` only in `secret_store.py` (pre-commit hook passes). gitleaks passes. My fixtures use invented names only. The CDP port is set only by the test harness (`app.py` refuses it outside `--dev`); the relaunched app inherits the environment, so a test's port carries over, which is what my real-app test relies on, and a normal launch has none.
- Messages carry no paths (NFR-5): checked in the bridge test and in B1's generic message.

## Docs findings
- `python scripts/check_docs.py --strict`: `check_docs: 0 error(s), 0 warning(s) [version v0.16]`.
- Developer Guide commands run as written: see the Commands table. None calls a `.ps1`, bare `npm`/`npx` or venv activation. `ruff format --check .` fails (B8). The new paragraph on `user.restore.db` / `user.restore.json` / `--after-restore` matches the code apart from B2 (one file without the other is still applied).
- User Guide *Backing up and restoring your data* followed against the mock and, for Restore, the real app: labels, defaults (off, 7 days, keep 5), order (Restore from a backup… → info → Replace my data → restart → notice), **About → Data folder → Open** for the `backups` folder, and the missing-folder warning all match. Step 4 and the notice: B10. *"WeakSquare only ever deletes its own backups there"* is true except while B3 is triggered (then it deletes none).
- "Your data and privacy" has the Backups bullet (not encrypted, sign-ins and keys never included, never uploaded), matching FR-15.5 and the code (no HTTP in the backup modules).
- CHANGELOG `[Unreleased]` has a line for Back up now, Restore and Automatic backups, covering every user-visible *Done when* item. README's status still names v0.15 as the latest release, right until sign-off. ROADMAP wording: B9.
- `docs/img/settings-your-data.png` matches the screen.

## Visual check
`tests/e2e/artifacts/qa-v016-restore-confirm.png`, `qa-v016-restore-failed.png`, `qa-v016-your-data-min-window.png`, `qa-v016-your-data-auto-on.png` (1000x700, automatic on, missing-folder warning). No clipping or overlap; every control stays inside the section at the minimum window size.

## Commands

| Command | Result |
|---|---|
| `uv run pytest` | **3963 passed**, 1 skipped, 2 xfailed (50:11, slowed by e2e running beside it). The builder's flake `test_qa_close_during_a_hung_search_returns_within_the_bound` passed this time. Collected before my file existed; it ran separately: **35 passed, 14 xfailed**. Builder's backup files + allowlist alone: 61 passed |
| `uv run pytest -m e2e` | **574 passed** (20:38), my 4 included |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **87 passed**, 1 skipped (23:45), `test_real_app_v016.py` (2) and my `test_qa_real_app_v016.py` included. (A first run without the build stopped with 87 errors because `gen_types.py` had touched `web/src/api/types.ts`: the guard working as documented) |
| `uv run ruff check .` / `uv run ruff format --check .` | clean / **3 files would be reformatted (B8)**, all builder files; mine formatted |
| `uv run mypy src` | no issues in 158 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean |
| `uv run pre-commit run --all-files` | all hooks passed (gitleaks, keyring hook) |
| `python scripts/check_docs.py --strict` | 0 errors, 0 warnings |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run pytest -m fulldb` / `-m engine` | not run: no v0.16 code path uses the puzzle DB or Stockfish |

## For Adam's manual test
- The real restore through the UI is covered end to end in a temp folder (my smoke test), but with the fixture data only: check a restore of your real-size `user.db` and how long *Checking the backup…* takes, and **don't close the app during it** until B2 is fixed.
- **Back up now** through the real Save dialog (my tests call the service; the dialog itself isn't driven). Check the suggested name and that typing a name without `.zip` saves `….zip`.
- Automatic backups on a real removable drive: unplug it, check the warning in Settings, plug it back in, check it recovers within the hour.
- After restoring into the dev copy, check you're asked to sign in (new data folder: yes); after an undo on the same install you'll still be signed in although the notice says otherwise (B10).
