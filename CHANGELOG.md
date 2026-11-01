# Changelog

Notable changes to WeakSquare Chess Trainer, newest first. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Version numbers are the ROADMAP.md checkpoints (v0.1 … v1.0), not semantic versioning.

## How entries are written
- **Same commit as the change.** When a commit changes what the app does, the builder adds a line under `[Unreleased]` in that commit.
- **Written for the person using the app:** what you can now do, or what behaves differently. Don't describe the code. Put requirement IDs at the end in brackets, e.g. `[FR-3.2]`.
- **Groups:** Added, Changed, Deprecated, Removed, Fixed, Security. Leave out empty groups.
- **Fixed** is for bugs in a version Adam already signed off. Bugs found and fixed inside the version being built live in `qa/` reports, not here.
- **Handoff (step 6):** add a `Candidates:` line under `[Unreleased]` listing the rc tag and date. Add each new rc to that line.
- **Sign-off (step 9):** rename `[Unreleased]` to `[v0.x] - YYYY-MM-DD`, keep the Candidates line, and start a new empty `[Unreleased]` above it.
- `python scripts/check_docs.py` checks this structure and that every requirement ID cited here exists.

## [Unreleased]

### Added
- Project specification, architecture, roadmap, QA agent, documentation set and repo guardrails. No app code yet.
- Licensed AGPL-3.0-or-later.
- The app window opens from the **WeakSquare Chess Trainer** shortcut in the Start menu, which `python scripts/setup.py` creates along with everything else the app needs. Re-running setup is safe. [NFR-8]
- **About** screen (the **?** button): version, your data and logs folders with Open buttons, the license and a link to the source code. [NFR-7]
- Only one copy runs at a time: starting it again brings the open window to the front. [NFR-1]
- Before an update changes your `user.db`, a backup goes to the `backups` folder (the last five are kept). A `user.db` from a newer version of the app is refused and left untouched. [NFR-3]
- Problems are written to rotating log files in the `logs` folder, with sign-in tokens and keys removed. [NFR-4] [SR-10]
