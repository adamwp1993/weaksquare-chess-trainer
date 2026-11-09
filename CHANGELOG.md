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
- **Back up now** in **Settings → Your data**: saves all your data (games and analysis, puzzle history and stats, Coach reports, your plan, notes and journal, repertoire and studies) to one `.zip` file where you choose. It's consistent even while the app is busy, checked before it's saved, and never changes anything. It isn't encrypted, and your Lichess sign-in and AI keys are never in it. [FR-15.1, FR-15.2, FR-15.5]
- **Restore from a backup**: shows what's in the backup, then replaces all your data with it once you confirm **Replace my data**. The app restarts to finish. Your current data is saved first as a backup in the `backups` folder, so a restore can be undone. A file that isn't a backup, a damaged one, or one from a newer version is refused and nothing changes; one from an older version is upgraded. [FR-15.4]
- **Automatic backups**, off unless you turn them on: weekly (or as often as you set) into a folder you choose, keeping the last 5. They run while the app is open, or at the next start if one came due while it was closed. A missing folder is shown in Settings and retried. [FR-15.3]

### Fixed
- **Data folder names**: a data folder whose path contains `#` or `%` (set with `WEAKSQUARE_DATA_DIR`) couldn't open the puzzle database. It now works. [NFR-2]

## [v0.15] - 2026-11-08

Candidates: v0.15-rc1 (2026-11-08)

### Added
- **The Analysis tab**: a board of its own in the top bar. Move for either side and every different move you try becomes its own line, listed with side lines like a study. Stockfish's eval, top three lines and best-move arrow follow the board, worded from White's side. Nothing here is scored, saved to your stats or sent to an AI. Your lines are kept while the app is open. [FR-14.1, FR-14.4, FR-14.5]
- **Set up a position** by dragging pieces from a palette, or picking a piece and clicking squares, with the side to move and castling rights; or paste a FEN. A position that can't happen in a game is refused with what's wrong, and never reaches Stockfish. [FR-14.2]
- **Import a PGN** into the Analysis tab, side lines and comments included. A file with several games lets you pick one. A PGN that can't be read changes nothing. It isn't added to My games. [FR-14.3]
- **Popular replies** on the Analysis tab while you're signed in to Lichess: the most played moves with their games and results, from the explorer settings you chose in the opening trainer. Click one to play it. [FR-14.4]
- **Open in Analysis tab** on the analysis board after a puzzle and under Analyze from here in Game Review: the position comes with the moves that led to it. A board that already has moves asks before it's replaced. [FR-14.6]

### Changed
- **Explain my game** now fills the review's three parts instead of adding a block of its own. **Summary** gets a general summary of the game rather than an opening summary. **What to improve** opens with a short summary of what your mistakes had in common, and each key moment is tagged with the puzzle themes that train it. **What you did well** opens with a short summary, and the AI's words sit under the strengths they're about. A game explained before needs a new run for the new version. [FR-11.18, FR-11.36]
- **Suggested training**: the puzzles Explain my game recommends now have their own box at the end of What to improve, with a **Train these puzzles** button, instead of a small "Practise:" line. [FR-11.36]

### Fixed
- **Copying text**: you can now select text in the app with the mouse and copy it with Ctrl+C. The board still can't be selected. [NFR-8b]
- **Lichess studies**: a chapter containing a null move (`--`) was accepted when the study was added, then showed as damaged when opened. It's now listed as **Can't be used** with the reason, and the rest of the study works. Re-add the study, or use **Check for updates**, to see it. [FR-13.7]

## [v0.14] - 2026-11-08

Candidates: v0.14-rc1 (2026-11-08)

### Added
- **Lichess studies**: a new **Studies** page. Paste a study's link (or a chapter's link, or its ID) under **Find studies** and it's downloaded, checked move by move and kept on your PC, so it works offline and stays if its author deletes it. [FR-13.1, FR-13.5, FR-13.7]
- **Four ways to find a study**: paste a link, open Lichess in your browser, browse lichess.org in a separate window with **Add this study** (it can't see WeakSquare, your settings or your sign-in), **Studies by author**, and a starter list of opening studies (links, titles and authors only). [FR-13.2, FR-13.3, FR-13.4, FR-13.5a, FR-13.6]
- **Work through a study**: step through chapters and their side lines with the author's text, arrows and highlights, or play along with interactive chapters. Your place is saved, **Continue** returns to it, and finished chapters are ticked. Nothing is scored. [FR-13.8, FR-13.10]
- **Hearts and filters** for My studies (All, Favorites, In progress, Finished); hearts stay in WeakSquare. **Check for updates** shows what changed in a study before you replace your copy. [FR-13.1, FR-13.7, FR-13.9]
- **Add to my repertoire** from a study: a chapter's or the whole study's main line (side lines if you want them), for White or Black, with a preview first. Where the study's move differs from yours, you choose which is your main move; nothing of yours is deleted. The moves are drilled in Practice. [FR-13.11]
- Chapters that are only text on a decorative board are kept as **Text** chapters; a chapter with an illegal move is listed with the reason and the rest of the study works. [FR-13.7]

- **Game Review in three parts**: a **Summary** of how the game went, **What to improve** (the key moments) and **What you did well**: only moves Stockfish's numbers back up (the only good move, punishing a mistake, a good defence, converting an advantage, a clean phase), each linked to its move. Works without an AI key, and never makes up praise. [FR-11.36]
- **Explain my game** adds a short *What you did well*, explaining only items from that list. An explanation saved before v0.14 isn't reused: asking again makes a new one, at the usual cost. [FR-11.18, FR-11.36]
### Changed
- **Signing in with Lichess** now also asks to read your studies (`study:read`), so you can add private studies you own or belong to. Sign-ins from before v0.14 keep working for everything else; adding a private study asks you to sign in again. [FR-6.1, FR-13.7]

## [v0.13] - 2026-11-07

Candidates: v0.13-rc1 (2026-11-07), v0.13-rc2 (2026-11-07), v0.13-rc3 (2026-11-07)

### Added
- **The opening trainer**: a new **Openings** page with the Lichess opening book. Search for an opening, choose your side and how many lines to show (up to **All**, every line the book has for it), and pick a line. [FR-12.1, FR-12.2, FR-12.7a]
- **Learn a line** by stepping through it with Stockfish's evals, or switch to **Play along**: the app plays the other side and nudges you if you go wrong. Unscored. [FR-12.3, FR-12.6, FR-12.16]
- **Extend past the book or stop at its end:** the book's lines are short, so you choose whether Stockfish continues them, in the background. Every move shows where it came from. [FR-12.13]
- **Popular moves from the Lichess explorer**, when you're signed in: they rank an opening's lines and continue them past the book, from Lichess games in the rating bands you choose, or masters' games. Answers are saved on your PC. [FR-12.2, FR-12.13]
- **Read about a position:** the Wikibooks *Chess Opening Theory* page for your line's moves, with its credit and licence. It's fetched when you open it and saved on your PC, and a setting turns it off. [FR-12.15]
- **AI notes on openings:** an overview, and **Explain this move**, grounded in Stockfish and Wikibooks. A saved note is free from then on and works offline, and **Regenerate** replaces one after showing the cost. Export or delete an opening's notes. [FR-12.5, FR-12.6, FR-12.7, FR-12.15]
- **Save notes for this opening:** prefetch with a scope, seeing the requests, tokens, cost, budget share and time before you Confirm. It runs in the background, can be cancelled, and goes in several runs if it's over your per-run cap. [FR-12.7a, FR-12.7b]
- **Openings** has its own model in Settings → AI. [FR-1.15]
- **"What if they play…?":** enter a move for the other side, get Stockfish's best replies, and add the branch to your repertoire. [FR-12.8]
- **Build my repertoire:** adds the replies you're likely to meet, with one answer for you at each position, and flags what needs a look. Nothing is saved until you've reviewed it. [FR-12.14]
- **Practice:** drill your repertoire with spaced repetition per position. The app plays the other side, and a miss shows your line and Stockfish's view. New positions come a few at a time. [FR-12.9, FR-12.10]
- **Opening stats:** accuracy, due positions and weakest positions per opening and line. They stay on your PC and affect no rating. [FR-12.11]
- **Study this opening** on an opening weakness in a Coach report opens the trainer. [FR-10.58]
- **Your repertoire:** add lines for White or Black, mark main moves and reorder them. Removing a move keeps any position another line still reaches. [FR-12.4]

### Fixed
- **Board letters and numbers are readable on every board.** They were small and faint inside the edge squares, and on Game Review and Puzzles the letters were often below the window. They now sit just outside the board, and the Puzzles, Game Review and opening Practice boards fit the window.

## [v0.12] - 2026-11-06
Candidates: v0.12-rc1 (2026-11-05), v0.12-rc2 (2026-11-06)

### Added
- **A training plan** in the Coach's new **Plan** tab: 1–4 weeks built from your latest report, on the weekdays you pick, sized by minutes per day, with your top weaknesses getting the most time. Free, on your PC. [FR-10.61, FR-10.62, FR-10.65]
- **Daily checklists that tick themselves**: a task ticks when the app sees it done, you can tick or untick any box by hand (your choice always wins), and you can skip or swap a task. A missed day's tasks carry over, up to one day's worth, unless you turn that off. [FR-10.64]
- **Start** on each task opens its screen: puzzle sessions, puzzles from your games, Retry on a named game, a review with best moves hidden, a lesson, or a reflection. A task never changes your filters, mode or presets. [FR-10.62, FR-10.63]
- **Today's plan** card on the main page, with the same checkboxes as the Plan tab. [FR-10.65]
- **A training journal** in the Coach's new **Journal** tab: your notes, your reflections on games, and an automatic daily log, with filters and search. [FR-10.67, FR-10.68, FR-10.70]
- **Add a note** in Game Review, on a game or one of its moves. The move gets a marker, and the note appears in your journal with a link back. [FR-10.69]
- **AI coaching proposes a plan**, checked task by task with the free plan filling any gaps. Compare the two, then **Use this plan**. The next run is told how your plan went, as numbers only. [FR-10.66]
- **Include my journal**, an option for one AI run, with a preview of exactly what's sent. Off every time. [FR-10.71]
- **Since last report** in every report: each weakness's rate then and now, New and Gone, game health, whole-game measures, puzzle accuracy on each weakness's themes, and the trend over your last 5 reports. AI coaching says what improved and what got worse, and a claim that contradicts the numbers is dropped. [FR-10.73]
- **An ⓘ on every option**: hover over it or tab to it to see what the option does and, for a choice, what each choice means and costs. [FR-10.72]

### Changed
- The Coach is now three tabs: **Report**, **Plan** and **Journal**. [FR-10.65]
- The weakness tables' **Since last report** column now says better or worse only with at least 5 games in that group in each report and 5 new games; otherwise *not enough new games yet*. A weakness that's new says **New** rather than *worse*. [FR-10.73]
- AI coaching allows longer answers, up to 7,500 tokens at Summary and 10,000 at Detailed, to leave room for the plan. Its estimate and worst-case cost are higher, so a costly model may now need a higher per-run cap, most of all at Detailed or a higher reasoning level. [FR-8.14]
- A saved AI answer is reused only if it has a plan and, with Include my journal, only while your journal text is unchanged. [FR-10.66, FR-10.71]

## [v0.11] - 2026-11-05
Candidates: v0.11-rc1 (2026-11-05)

### Added
- **Whole-game measures** in every Coach report on games, worked out on your PC from each game's analysis: per opening family (score, eval at move 15, early mistakes), mistakes per phase, how often you win from +2 and save from −2, results and mistakes per endgame type, mistakes on a low clock against the rest, and castling late. A group needs 5 games before it counts; below that it says *not enough data yet*. [FR-10.52] [FR-10.53]
- **Whole-game weaknesses:** an opening you come out of badly, an endgame type you err in, winning positions you don't win, low-clock mistakes and late castling join the report's weaknesses when the numbers show them, ranked per 10 games. A time weakness is flagged in **Why this mix**. [FR-10.57] [FR-10.58]
- **AI coaching reads your whole games:** it diagnoses tactical, strategic and practical weaknesses (openings, endgames, king safety, time and anything else it can show), and every weakness cites the moves in your games that show it. Click a move to open it in Game Review. Claims the app can't find in your games are left out, a weakness seen in fewer than 3 games is marked **Tentative**, and findings the app can't measure are **Observations**, noted again when they recur. [FR-10.51] [FR-10.54] [FR-10.55] [FR-10.57]
- **Advanced analysis** (off by default, for one run at a time): also sends the moves of 10–50 of your games (SAN only), with how it compares with a standard run in tokens, cost, share of your budget and minutes before you **Confirm**. [FR-10.56]
- **Include my notes** (off by default, for one run at a time): adds your mistake-reason notes, after a preview of exactly what's sent, with web addresses removed. [FR-10.60]
- **Every AI answer is kept** per report: switch between standard, Advanced and with-notes answers, and see which findings are new in each. [FR-10.56]
- **Lesson pointers:** for a weakness's topic, **Drill it here** (that topic's puzzles at a lower rating), Lichess Practice or Learn pages, and searches on YouTube, chess.com or your own site. Links open in your browser, and the app builds every link itself. Choose the search sites in **Settings → Coach**. [FR-10.59]
- **Retry your mistakes** now offers **Explain this move** once you've tried, with **Show me** on the Retry board. [FR-11.15] [FR-11.17]
- **Managing presets:** **Update** the loaded preset with your current filters, and **Manage presets…** to overwrite, rename or delete any preset without loading it. Saving a Coach preset under a name you already use offers **Replace it** or another name. [FR-3.13]

### Changed
- **AI coaching** on reports with games now sends a short digest of each game (labelled G1, G2…, no names, dates, links or raw clocks) as well as the report's numbers, so its estimate is higher than in v0.10. Reports on your puzzle history only work as before. [FR-8.16] [FR-10.54]

### Fixed
- The number boxes in Settings (Engine, Games and AI) step up and down again with the arrow keys and their up/down buttons. Before, the engine's think time per position couldn't be raised above 1 that way, and a box went back to its saved value while you changed it. [FR-7.4] [FR-11.8]

## [v0.10] - 2026-11-04
Candidates: v0.10-rc1 (2026-11-04), v0.10-rc2 (2026-11-04)

### Added
- **Show best moves** in Game Review: a switch, off by default and remembered, that hides the best-move arrow, the engine lines, *better was …* and the AI's better lines, so you can look for the better move yourself first. The eval graph, the symbols, why your move fails and the AI's text stay. [FR-11.35]
- **Analyze from here** in Game Review: a free board from any position of the game, where you move either side and Stockfish follows (with Show best moves on). **Back to the game** returns where you were; nothing you play changes the game or its analysis. [FR-11.34]
- **My puzzles:** filter by **severity** and by **From my games (made automatically)**; after a puzzle from your games, **Open the game** and **Archive this puzzle**. [FR-10.40] [FR-10.44] [FR-3.15]
- **Theme tags on your mistakes:** your game mistakes, saved puzzles and imported puzzles get the same themes as Lichess puzzles (fork, pin, back-rank mate…), worked out on your PC by Lichess's own tagger. [FR-10.12] [FR-11.10] [FR-10.49]
- **The Coach:** a new page that finds your weaknesses on your PC, for free: your Missed and Allowed tactics by theme and your habit tags, each per 10 games with how much they cost you, your mistake reasons, examples you can open in Game Review, your puzzle history (with the Lichess puzzle dashboard when you're signed in), a puzzles-vs-games gap table, and a recommended preset. Run it on your last 25–200 games or on games you send from My Games, and compare each report with your last one. [FR-10.1] [FR-10.2] [FR-10.4] [FR-10.14] [FR-10.15] [FR-10.16] [FR-10.17] [FR-10.18] [FR-10.19] [FR-10.20] [FR-10.26] [FR-11.30]
- **AI coaching (optional):** **Get AI coaching** on any Coach report turns its numbers and a few example positions into a short summary, notes on your top 3–5 weaknesses and 1–3 puzzle presets you can **Load** or **Save**. It shows the estimate first and runs when you **Confirm**, within your per-run cap and monthly budget, on its own model, picked right in the AI coaching box or in Settings → AI → Coach (**Same as Explain** by default). It sends no names, usernames, dates or links. [FR-10.21] [FR-10.22] [FR-10.23] [FR-10.24] [FR-10.25] [FR-1.15]
- **Coach another player:** enter any Lichess or chess.com username or profile link to analyze that player's public games. Their games and report are kept apart from yours: they're hidden from My Games unless you pick them in the Player filter, and they never change your puzzles or your Suggested mix. [FR-10.3]
- **Suggested mix:** after a Coach run, your puzzle selection becomes a mix built from your top weaknesses, with **Why this mix** in plain words, the drill mode your mistake reasons point to, a share of puzzles from your own games and a share of long combinations. If you've changed your filters, a banner offers **Apply**, **Compare** or **Dismiss** instead of replacing them. [FR-10.28] [FR-10.29] [FR-10.30] [FR-10.31] [FR-10.44]
- **Puzzles from your games:** every analysis of one of your games turns your clear mistakes into puzzles in **My puzzles**, checked with Lichess's own rules for a puzzle with one answer. A mistake you **missed** is solved as you; one you **allowed** is solved as your opponent (*Find what your opponent could have played*). Choose which mistakes count in Settings → Games: blunders only, mistakes and blunders (default), or inaccuracies too. Changing it archives or restores puzzles without analyzing your games again, and games you analyzed before this version get their puzzles once, in the background. [FR-10.39] [FR-10.40] [FR-10.41] [FR-10.42] [FR-10.43]
- **Habit tags on your game mistakes:** *hung a piece*, *missed a free capture*, *ignored a threat* and *moved a defender*, the most common club-level slips, checked on your PC. [FR-10.27]

## [v0.9] - 2026-11-04
Candidates: v0.9-rc1 (2026-11-04)

### Added
- **Explain this move:** on any of your analyzed moves in Game Review, the AI explains why Stockfish's move is best and what was wrong with yours, with **Show me** on the board. Every move and square it mentions is checked against the game. [FR-11.17] [FR-11.20]
- **Explain my game:** one request covering your top key moments (5 by default, up to 10): an opening summary, the turning point, recurring themes, 2–3 takeaways, a note on each key moment you can show on the board, and often a puzzle recommendation with **Train these**. It shows the estimated tokens and cost first and runs only when you **Confirm**. It sends the game's moves only, as You and Opponent: no names, ratings, dates, links or clocks. [FR-11.18] [FR-11.19] [FR-11.21]
- **AI-reviewed** status and filter in My games, and **Review + Explain my game**, which analyzes the game first if needed. [FR-11.25] [FR-11.29]
- **A model for each AI feature:** Game Review has its own model (**Same as Explain** by default) and reasoning level, set in Settings → AI, on the startup page or right on the Review page. Keys, the price table, the per-run cap and the monthly budget are shared, and Settings shows this month's spend per feature. [FR-1.15]

### Changed
- **Spending limits:** the monthly budget and the per-run cap now cover Game Review's AI too, and saved game explanations are free like saved puzzle explanations. [FR-8.13] [FR-8.14]

## [v0.8] - 2026-11-04
Candidates: v0.8-rc1 (2026-11-04)

### Added
- **My games:** one list of your Lichess and chess.com games, newest first, synced in the background when the app opens and with **Refresh** (metadata and PGNs only). Filter by platform, time control, result, color, status, rated, opponent, opening and date. Link chess.com by username, with **Verify**, in Settings → Games. [FR-11.23] [FR-11.24] [FR-11.25] [FR-11.26] [FR-11.27] [FR-11.28]
- **Import a game:** paste a PGN, open a .pgn file (pick a game when it holds several), or paste a Lichess or chess.com game URL. The app asks which side you played when it can't tell. Variants are refused with a clear message, and importing a game you already have reuses its analysis. [FR-11.1] [FR-11.2] [FR-11.3] [FR-11.4] [FR-11.5] [FR-11.6] [FR-11.7]
- **Game Review:** Stockfish grades every move on your PC, in the background and one game at a time, with progress and Cancel. The review has a move list with ?! ? ?? symbols, an eval graph you can click, a summary per side, your key moments (*played X, better was Y*), the engine's top lines at any move, and why a mistake fails, step by step. [FR-11.8] [FR-11.9] [FR-11.11] [FR-11.12] [FR-11.13] [FR-11.14] [FR-11.29] [FR-11.30] [FR-11.31]
- **Retry your mistakes:** replay each of your mistakes and blunders without the answer; any move within 30 cp of the best counts. Results stay on this PC and show in Stats. [FR-11.15] [FR-11.22]
- **Save as puzzle and My puzzles:** save any key moment as a puzzle, then train **My puzzles** on their own or mixed with Lichess puzzles (**Puzzles from: Lichess DB / My puzzles / Both**), in Standard, Commit the line and Spaced repetition. Puzzles from your games accept any move Stockfish rates within 30 cp of the best. They never sync to Lichess. [FR-11.16] [FR-3.15] [FR-10.43]
- **Import puzzles from your own files:** PGN, EPD or CSV, as a labelled set with an import report; checked strictly like Lichess puzzles, any mate counting for mate-in-1. The file never leaves your PC. [FR-10.46] [FR-10.47] [FR-10.48] [FR-10.49] [FR-10.50]
- **Why you missed it, in your games:** the reason chips on your game mistakes and Retry misses, and Stats → Why you missed can now show puzzles, your games, or both. [FR-5.7] [FR-9.7]

### Changed
- **Why you missed it:** Settings → Training → **Ask why you missed** has a new choice, **Game Review only**, which asks about your mistakes in Game Review but not after puzzles. [FR-5.8]

## [v0.7] - 2026-11-03
Candidates: v0.7-rc1 (2026-11-03)

### Added
- **AI explanations:** once a puzzle is over, **Explain** asks Claude (Anthropic) or GPT (OpenAI) to explain it in plain words: the idea, each move, and why your move failed. It's grounded in the solution, Stockfish's lines and the board's attack and defence facts, and every move and square it mentions is checked against the position before it's shown. **Show me** steps through the solution with its arrows and circles drawn on the board. It needs Stockfish and your own API key, and works in every mode, Danger spotting included. [FR-8.1] [FR-8.2] [FR-8.3] [FR-8.4] [FR-8.5] [FR-8.7] [FR-8.8]
- **AI settings:** choose a provider and model (nothing is pre-selected; the list shows each model's cost per Explain), save your API key to Windows Credential Manager, and check it with **Test key**, which is free. On the startup page, a saved key is checked quietly at launch. [FR-1.2] [FR-1.3] [FR-1.4] [FR-1.6] [FR-1.8]
- **Spending limits:** an editable price table, a monthly budget (default $5, warns at 80%, stops at 100%), a per-run cap (default $0.50), a hard limit on every request's length, a reasoning setting (Low by default), and a spend indicator in the top bar. Explanations are saved, so showing one again is free. [FR-1.10] [FR-8.6] [FR-8.9] [FR-8.10] [FR-8.11] [FR-8.12] [FR-8.13] [FR-8.14] [FR-8.15]

## [v0.6] - 2026-11-03
Candidates: v0.6-rc1 (2026-11-03)

### Added
- **Name the idea first:** a new training mode. Before your first move you tag the idea (setup and payoff motifs), then solve as usual; afterwards you see which ideas you found, which you missed and which tags were extra. [FR-4.3]
- **Danger spotting:** a new training mode that shows the position just before a blunder with one move highlighted. Call it **Safe** or **Unsafe**; if it's the blunder, punish it with the right reply. About half the highlighted moves are safe ones that Stockfish has checked, so "Unsafe" isn't always the answer. It needs Stockfish, and the results stay on this PC (they don't sync, and they don't affect Spaced repetition or the history filters). [FR-4.4]
- **Why you missed it:** after a failed puzzle, six chips (keys **1–6**) ask why: didn't look, missed their reply, miscalculated, didn't know the pattern, rushed, or misclick. The app highlights a likely reason; you can add a short note, skip, or change your answer until you move on. Turn the question off, or change what counts as rushed, in Settings → Training. [FR-5.6] [FR-5.7] [FR-5.8] [FR-5.9]
- **Misclicks don't count against you here:** a miss you tag Misclick is left out of your accuracy (the session bar, Stats and the depth ladder) and counted on its own. It still counts as a loss on Lichess. [FR-5.10]
- **Stats:** a **Why you missed** breakdown (filter by theme and mode, with a weekly trend), and each mode's own measure: Commit's calculation accuracy, Name the idea's ideas found and tags right, and Danger-spotting accuracy on safe moves and on blunders. [FR-9.3] [FR-9.7]

### Fixed
- Clicking a square on the board works anywhere in the square again. After something above the board appeared or changed height, a move only registered when you clicked near the middle of the square.

## [v0.5] - 2026-11-03
Candidates: v0.5-rc1 (2026-11-03)

### Added
- **Training modes:** a **Modes** control at the top of the filters panel picks how you train: **Standard** (as before), **Commit the line** or **Spaced repetition**. The app remembers your choice; changing it starts a new session. [FR-4.2] [FR-4.6]
- **Commit the line:** enter the whole line, your moves and the replies you expect, with no feedback, then press **Submit**. Every one of your moves must match the solution to win; the replies you predicted are scored separately as calculation accuracy. The solution's length is hidden unless you turn on **Show move count** (solves then count for less on Lichess, because you knew the length). [FR-4.2]
- **Spaced repetition:** puzzles you miss come back on a schedule (1, 3, 7, 14 and 30 days by default, editable in Settings). A miss in any mode, including your misses from earlier versions, starts a puzzle at the first box; solving it in Spaced repetition moves it up, and solving it from the last box retires it. [FR-4.6]
- **Depth ladder:** a new **Order** option serves 2-move puzzles, then 3-move, then 4+ once you're accurate enough (80% over your last 20 at that level by default; both adjustable in Settings). Your level is kept for each set of themes and never drops. [FR-4.5] [FR-3.11]
- **Stats by mode:** the Stats page has accuracy per training mode. [FR-9.1]
- **Hide the filters while you play:** **«** at the top of the filters panel (or **F**) folds it into a slim bar with your mode and a summary; the board gets bigger. **Show filters** brings it back unchanged, and the app remembers your choice. [FR-1.14]
- **Settings → Training:** the depth ladder's threshold and window, and the Spaced-repetition review boxes. [FR-4.5] [FR-4.6]

### Fixed
- The **Already played: rating unaffected** badge (it said "on Lichess") is no longer cut off in the side column. [FR-6.11b]
- **Cancel** right after **Sign in with Lichess** now always cancels; very early, it could be missed and the sign-in kept waiting. [FR-6.1a]

## [v0.4] - 2026-11-02
Candidates: v0.4-rc1 (2026-11-02), v0.4-rc2 (2026-11-02)

### Added
- **Why your move fails:** after a wrong move, **Show answer** shows the solution with *Why your move fails* and Stockfish's evaluation above it; its **Show me** steps through your move and Stockfish's best reply (up to 5 moves). [FR-7.2]
- **Stockfish after each puzzle:** once a puzzle is over, a panel shows the evaluation of the starting position and the top 3 lines for whatever is on the board, following you through the answer. Evaluations read from your side, e.g. "+3.2 for you". Nothing from the engine is ever shown while you're solving. [FR-7.2] [FR-7.3] [FR-7.7]
- **Show me:** each of Stockfish's lines has a **Show me** button that puts the line on the board for you to step through with Back / Forward; **Done** returns. [FR-7.7]
- **Try again (not scored):** once a puzzle is over, solve it again from the start for practice. Nothing is recorded or sent to Lichess; the puzzle keeps your first result. [FR-5.12]
- **Show answer** stays clickable after a puzzle: click it again to go back to the start of the answer, for example after exploring on the analysis board, whose **Close** now reads **Back to the answer**. [FR-5.4]
- **Analysis board:** **Analyze on the board** lets you move pieces for either side after a puzzle, with Stockfish's evaluation, top lines and a best-move arrow after each move. Nothing there is scored. [FR-7.7]
- **Install Stockfish from the app:** where the engine would appear and it isn't installed, *Stockfish isn't installed* offers **Install Stockfish**, with progress. [FR-7.5]
- **Settings → Engine:** think time, threads and hash, **Use my own engine…** (any UCI engine that passes a self-test) and **Reinstall**. About shows the engine in use and where it is. [FR-7.4] [FR-7.5] [NFR-7]
- **Stockfish 19 installs with setup:** `scripts/setup.py` now downloads the official Stockfish 19 build from GitHub (about 80 MB), checks it against a pinned SHA-256 before unpacking it, tests it and installs it into your data folder. `scripts/fetch_stockfish.py` installs or repairs it on its own, and running it again does nothing when the engine is already fine (`--force` reinstalls). [FR-7.1] [FR-7.5]

## [v0.3] - 2026-11-02
Candidates: v0.3-rc1 (2026-11-02)

### Added
- **Sign in with Lichess** from the new startup page or the gear settings. Lichess opens in your own browser, so your password manager and two-factor sign-in work. The sign-in is kept in Windows Credential Manager, never in a file. With a sign-in Lichess accepts, the startup page is a single **Continue as *your name*** button. [FR-1.1] [FR-1.5] [FR-1.6] [FR-6.1] [FR-6.1a] [FR-6.5]
- **Solves sync to Lichess** as you play, with an honest angle (`mix` only when themes and move count are All). Offline or signed out, they wait and sync later, and the top bar says how many are waiting. [FR-1.7] [FR-6.8] [FR-6.13] [FR-6.14] [FR-6.16]
- **Your Lichess puzzle rating** in the top bar, the **+/−** change on each puzzle's result (or why there isn't one), and the session's total in the session bar. All of them come straight from Lichess. [FR-6.11a] [FR-6.11b] [FR-6.11c]
- **Rated** switch for the session: off sends your solves as unrated. [FR-1.9] [FR-6.15]
- **Exclude played on Lichess** (on by default): your Lichess puzzle history is read when you sign in, and those puzzles are left out. A puzzle you've already played there shows *Already played on Lichess: rating unaffected*. [FR-3.9] [FR-6.17]
- **Sign out** cancels your sign-in on Lichess as well as removing it from this PC. If Lichess can't be reached, the app asks first. [FR-6.6]
- A **gear** icon opens Settings, now with your Lichess account at the top. [FR-1.8]
- **Rating trend** on Stats: a chart of your Lichess puzzle rating over time and the change in each session, from what Lichess returned. [FR-9.4] [FR-6.11d]

### Changed
- Puzzles you played before this version stay on this PC and aren't sent to Lichess.

## [v0.2] - 2026-11-01
Candidates: v0.2-rc1 (2026-11-01)

### Added
- **Mix by ratio:** give theme groups a share of the session, e.g. 50% forks, 30% pins or skewers, 20% one-movers. Each group shows its own count, and the mix holds to within one puzzle. [FR-3.10]
- **Opening filter:** choose opening families or individual variations, with search. [FR-3.7]
- **Quality filter:** minimum popularity and minimum plays, on by default at 50 and 100 (adjustable, or off). [FR-3.8]
- **Your history:** leave out puzzles you've solved here (on by default), or train only your misses. [FR-3.9]
- **Order:** random, easy → hard, or grouped by theme. [FR-3.11]
- **Presets:** save your filters under a name, then load, rename or delete them. [FR-3.13]
- **Hint** circles the piece that moves next, and **Show answer** (unlocked by a Hint) steps through the rest of the solution with Back and Forward. Either one before the end fails the puzzle; after it, Show answer is free. [FR-5.2] [FR-5.4]
- **Stats** (☰ → Stats): accuracy by theme, length and rating band, plus the "first move right, line wrong" rate. [FR-9.1] [FR-9.2]
- **Keyboard shortcuts:** N or Enter for the next puzzle, H for Hint, A for Show answer, arrows to step through it, C for coordinates, ? for the list.
- Show or hide the board coordinates (C, the ☰ menu, or Settings); your choice is saved.
- **Dark mode:** Light, Dark or Match system in ☰ → Settings…, applied at once and remembered; the app opens in your saved scheme. [FR-1.12]
- **Move sounds:** moves, captures, checks, mates, and solved or failed puzzles, with an on/off switch, volume and four sound sets (sfx, piano, 8-bit, futuristic). In the default sfx set, a solved puzzle plays a short, soft chime. [FR-1.13]
- **Update check:** once a day, a banner tells you when Lichess has a newer puzzle export (with its date, download size and an approximate count), with Update now, Not now and Skip this export. **Check for updates** in the update dialog checks at once, and Settings can turn the daily check off. It's silent offline and sends nothing about you. [FR-2.5]
- **App icon and desktop shortcut:** setup also puts a shortcut on your desktop (`--no-desktop-shortcut` to skip), and the shortcuts, window and taskbar show the WeakSquare icon. [NFR-8a]
- After a puzzle-database update, the finish message gives the exact numbers, e.g. "6,201,004 puzzles: 44,112 new, 450 removed." [FR-2.5]

### Changed
- The puzzle-database screen says plainly that it downloads the **entire** Lichess puzzle database: about 300 MB, about 6 million puzzles, roughly 1.5 GB once imported. [FR-2.1a]
- Phase, goal and origin themes are chosen in the theme list's own groups, alongside the other themes. [FR-3.6]
- The filter panel scrolls on its own, so the board stays in view, and the match count updates as you play.
- Dimmed text, the green messages and the teal buttons are darker (lighter in Dark), so all text meets WCAG AA contrast.
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
