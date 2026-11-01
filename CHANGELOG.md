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
- **Mix by ratio:** give theme groups a share of the session, e.g. 50% forks, 30% pins or skewers, 20% one-movers. Each group shows its own count, and the mix holds to within one puzzle. [FR-3.10]
- **Opening filter:** choose opening families or individual variations, with search. [FR-3.7]
- **Quality filter:** minimum popularity and minimum plays, on by default at 50 and 100 (adjustable, or off). [FR-3.8]
- **Your history:** leave out puzzles you've solved here (on by default), or train only your misses. [FR-3.9]
- **Order:** random, easy → hard, or grouped by theme. [FR-3.11]
- **Presets:** save your filters under a name, then load, rename or delete them. [FR-3.13]
- After a puzzle-database update, the finish message gives the exact numbers, e.g. "6,201,004 puzzles: 44,112 new, 450 removed." [FR-2.5]

### Changed
- Phase, goal and origin themes are chosen in the theme list's own groups, alongside the other themes. [FR-3.6]
- The filter panel scrolls on its own, so the board stays in view, and the match count updates as you play.
- The first time v0.2 starts, it upgrades your puzzle database for the new opening and quality filters. This rebuilds it from the copy you already have (no download, about 2 minutes, with a progress bar), and your attempts and settings aren't touched. [FR-2.3]

## [v0.1] - 2026-11-01
Candidates: v0.1-rc1 (2026-11-01)

### Added
- Project specification, architecture, roadmap, QA agent, documentation set and repo guardrails.
- Licensed AGPL-3.0-or-later.
- The app window opens from the **WeakSquare Chess Trainer** shortcut in the Start menu, which `python scripts/setup.py` creates along with everything else the app needs. Re-running setup is safe. [NFR-8]
- **About** screen (the **?** button): version, your data and logs folders with Open buttons, the license and a link to the source code. [NFR-7]
- Only one copy runs at a time: starting it again brings the open window to the front. [NFR-1]
- Before an update changes your `user.db`, a backup goes to the `backups` folder (the last five are kept). A `user.db` from a newer version of the app is refused and left untouched. [NFR-3]
- Problems are written to rotating log files in the `logs` folder, with sign-in tokens and keys removed. [NFR-4] [SR-10]
- **Puzzle database import:** on first run the app downloads the Lichess puzzle database (about 300 MB, roughly 6 million puzzles), checks it against the checksum Lichess publishes, and imports it with a progress bar. You can also import a file you already have, cancel at any time, and later update from the menu (**☰ → Update puzzle database…**). An interrupted download resumes. A cancelled or failed import leaves your current puzzles and all your data untouched. [FR-2.1] [FR-2.3] [SR-6]
- **Choose your puzzles:** pick any mix of themes from a grouped, searchable list, matching ANY or ALL of them; exclude themes; set a rating range with a slider or exact numbers; choose the number of moves (1, 2, 3, 4+) and the side you play. A live count shows how many puzzles match, and your filters are remembered. [FR-3.1] [FR-3.2] [FR-3.3] [FR-3.4] [FR-3.5]
- Sessions of a fixed number of puzzles or endless, in random order with no repeats. [FR-3.11] [FR-3.12]
- **Solve puzzles on a board:** the opponent's move plays first, your correct moves get the reply automatically, and any checkmating move counts when the solution is a mate. A wrong move fails the puzzle but you can finish the line. Themes stay hidden until the puzzle is decided. [FR-4.1] [FR-5.1] [FR-5.3] [FR-3.14]
- Every attempt is saved. A session bar shows solved, failed and accuracy for the session, plus your all-time totals. [FR-5.5]
