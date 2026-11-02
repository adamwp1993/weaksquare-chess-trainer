# WeakSquare Chess Trainer: User Guide

WeakSquare Chess Trainer is a Windows desktop app for training chess tactics on the Lichess puzzle database. You choose exactly which puzzles you get (themes, rating, length, side), solve them on a board, and over time the app helps you find and fix the gaps in your play.

This guide covers **only what the app does today**. Each section says which version added it. For what changed in each version, see [CHANGELOG.md](../CHANGELOG.md).

<!--
Planned chapters, added only when their version ships (see CLAUDE.md "Documentation"):
  Getting started: first run and the puzzle download ......... v0.1
  Choosing your puzzles (filters, queue) ...................... v0.1, v0.2
  Solving a puzzle (the trainer, the session bar) ............. v0.1
  Presets and stats ........................................... v0.2
  Signing in with Lichess, syncing solves, offline mode ....... v0.3
  Getting unstuck: hints and the engine ....................... v0.4
  Training modes .............................................. v0.5, v0.6
  Mistake reasons ............................................. v0.6
  AI explanations and what they cost .......................... v0.7
  Your game library and Game Review ........................... v0.8, v0.9
  The Coach ................................................... v0.10
  Tracking your progress ...................................... v1.0
  Installing from source and updating ......................... v0.1, v1.0
  The About screen ............................................ v0.1
  Troubleshooting ............................................. grows each version
-->

## Your data and privacy
*Added in v0.1.*

- **Where your data lives:** everything is stored on this PC under `%LOCALAPPDATA%\WeakSquare`.
  - `puzzles.db` is the imported Lichess puzzle database. It's large but rebuildable: re-importing replaces it.
  - `user.db` holds everything you create: your attempts, presets and settings, and from later versions your games and analysis. Back up this file to keep your history.
  - Before an update changes `user.db`, the app saves a copy in the `backups` folder next to it and keeps the last five.
- **Sign-ins and API keys** are never written to files. Your Lichess sign-in (from v0.3), and from v0.7 any AI provider key, are stored in **Windows Credential Manager**. Signing out removes them. Each data folder has its own entry, so a test or development copy of the app never sees your real sign-in.
- **Nothing leaves your PC** unless you use a feature that needs the internet. Those features are listed in their own sections, along with what they send.
  - **Puzzle database download** (v0.1): requests the public puzzle file and its checksum list from database.lichess.org. Nothing else is sent.
  - **Update check** (v0.2): at most once a day, and when you click **Check for updates**, the app makes three plain requests to database.lichess.org: the checksum list (`sha256sums.txt`), the puzzle file's date and size (a `HEAD` request, which doesn't download it) and the front page, for the approximate puzzle count. Nothing about you or your training is sent. Turn it off in **☰ → Settings…**.
  - **Lichess sign-in and sync** (v0.3), only while you're signed in. See [Signing in with Lichess](#signing-in-with-lichess-syncing-solves-offline-mode) for when each happens. All of it goes to lichess.org over HTTPS:
    - **Signing in** opens lichess.org in your browser. The app then exchanges a one-time code for your sign-in.
    - **Your account:** your username and puzzle rating are read at start-up and after signing in.
    - **Your solves:** for each puzzle you finish, the app sends its ID, whether you solved it, whether it's rated, and the theme you chose it by (the *angle*, for example `mix` or `fork`). Nothing else about your session is sent.
    - **Your puzzle history:** the puzzles you've played on Lichess are read once, then only new ones.
    - **Signing out** tells Lichess to cancel your sign-in.
  - **Stockfish download** (v0.4): installing Stockfish (from setup, `fetch_stockfish.py` or the **Install Stockfish** button) downloads one file, the official Stockfish 19 Windows build, from github.com. Nothing about you is sent. The engine itself runs entirely on your PC and never uses the internet.
  - **Links that open your browser** (v0.1): **Open this puzzle on Lichess** (after a puzzle) and the **Source code** link on the About screen open the page in your default browser, like any link you click. The app itself sends nothing.

## Getting started: the puzzle database
*Added in v0.1. Changed in v0.2: the wording says what you download.*

WeakSquare trains on the Lichess open puzzle database, which is public domain. **Download from Lichess** fetches the **entire** database, every puzzle and not a sample: about 300 MB compressed, about 6 million puzzles, and roughly 1.5 GB on disk once imported. It's stored on your PC, so after the first download everything works offline. With every filter cleared, including the quality filter under **More filters**, the match count equals the number of puzzles imported. With the default quality filter on, it's lower (see *Choosing your puzzles*).

If setup already imported it, the app opens straight to your puzzles. Otherwise the first screen is **Get the puzzle database**:

![The first-run screen](img/first-run.png)

1. Click **Download from Lichess**. The app downloads the whole database (about 300 MB), checks it against the checksum Lichess publishes, and imports it. Expect a few minutes; the progress bar shows each stage. Make sure you have about 2 GB free: the download and the imported database (about 1.5 GB) are both on disk until the import finishes.
2. When it's finished, the app switches to your puzzles.

![The import in progress](img/first-run-importing.png)

**Already have the file?** Click **Use a file I already have…** and choose a `lichess_db_puzzle.csv.zst` (or an unpacked `.csv`) from database.lichess.org.

**Updating:** Lichess publishes a new export regularly, and the app tells you when there is one (see [Keeping the puzzle database up to date](#keeping-the-puzzle-database-up-to-date)). You can also choose **☰ → Update puzzle database…** at any time. You can keep training while it runs; the new puzzles are switched in when it's finished.

**The one-time upgrade** (*Added in v0.2*): the first time v0.2 starts, it shows **Upgrading your puzzle database**. The opening and quality filters need extra information in the database, so the app rebuilds it once from the copy you already have. Nothing is downloaded, it takes about 2 minutes, and your attempts and settings aren't touched. If it stops (for example, you close the app), it starts again next time and your current database keeps working until it finishes.

**Gotchas**
- **Cancel** stops at any point and leaves your current puzzles as they were. An interrupted download picks up where it stopped next time.
- If the download doesn't match Lichess's checksum, it's deleted and nothing changes. Try again later (Lichess may be updating the file).
- Importing never touches your attempts or settings.
- **What it sends:** the download is a plain file request to database.lichess.org. Nothing about you or your training is sent.

## Signing in with Lichess, syncing solves, offline mode
*Added in v0.3.*

Signing in is optional. When you're signed in, every puzzle you finish is also recorded on your Lichess account, your Lichess puzzle rating is shown in the app, and you can leave out puzzles you've already played on Lichess.

### The startup page
The app opens on a startup page every time.

![The startup page](img/startup.png)

- **First time, or signed out:** the page says *Not signed in*. Click **Sign in with Lichess**, or **Continue without signing in**.
- **Signed in:** one button, **Continue as *your name***. **Show all options** reveals **Sign out** and **Sign in as someone else**.
- **Lichess can't be reached** (for example, no internet): your sign-in is kept and the button says **Continue offline as *your name***. Your solves are saved here and sync later.
- **Your sign-in expired or was revoked** (Lichess sign-ins last about a year): the page says so and asks you to sign in again. If it happens while you're training, a banner with **Sign in again** appears above your puzzles; your solves wait until you do.

### Signing in
1. Click **Sign in with Lichess**. Lichess opens **in your usual web browser**, not inside WeakSquare, so your password manager and two-factor sign-in work as normal.
2. Sign in to Lichess if you aren't already, and approve WeakSquare. It asks only to read and record your puzzle activity (`puzzle:read` and `puzzle:write`).
3. The browser says *"Signed in. You can close this tab and return to WeakSquare."* The app comes back to the front and shows **Signed in as *your name***.

While you're in the browser, the app shows *Waiting for you in your browser…* with **Cancel**. After 5 minutes it stops waiting and you can try again. If it fails, the reason is shown (for example *Sign-in failed: Lichess refused the request*). You can always continue without signing in.

### Your puzzle rating
While you're signed in, the top bar shows **Puzzle rating 1834**, with a **?** after it while Lichess still calls your rating provisional. The number always comes from Lichess. The app never calculates or estimates it, so it matches lichess.org.

After each puzzle, the result panel shows its **Lichess rating** change, e.g. **+8** in green or **−12** in red, usually within a second or two. Until Lichess replies it says **Syncing…**. When there's no number, it says why:
- **Will sync later:** you're offline or not signed in. The number fills in once the solve has synced.
- **Unrated (Rated is off):** you switched off **Rated** for this session (below).
- **Already played: rating unaffected:** you've played this puzzle on Lichess before, and Lichess only rates your first try.
- **Not rated by Lichess:** Lichess returned no change.

A puzzle you've already played on Lichess also shows the badge **Already played on Lichess: rating unaffected** while you solve it.

The session bar adds **+34 this session**, the total of the changes Lichess returned this session. The rating trend over time is on the Stats page.

![A solved puzzle with its rating change](img/rating-change.png)

**Why do themed sessions move my rating so little?** Lichess weighs a solve by what you knew in advance. If you choose only forks, you know a fork is coming, so a win counts for about a fifth of a normal one. WeakSquare reports this honestly as the *angle*:
- It's `mix` only when the themes are **All**, the number of moves is **All** and you're not using ratios.
- Otherwise it's the theme you chose that the puzzle has. Motifs (fork, pin…) come before phases and goals (endgame, crushing…).
- If you narrowed only the number of moves, it's the length (one-move, short, long or very long).

Excluded themes, openings, rating, side and quality don't change it.

### Rated
The **Rated** switch above **Start** applies to the session you start. It's on every time you open the app. Switch it off to practise without risking your rating: your solves are still recorded on Lichess, as unrated.

### Syncing and offline mode
- Solves sync right away when you're signed in, and syncing never slows down solving.
- Offline, or before you sign in, solves wait on this PC. The top bar says **Offline: 3 solves waiting to sync** (or **Not signed in: 3 solves waiting to sync**). They're sent automatically when Lichess can be reached again, or when you next sign in. Nothing is lost if you close the app.
- A solve made while signed in to one Lichess account only ever goes to that account. Solves made while signed out go to the next account you sign in with.
- Puzzles you played before v0.3 aren't sent to Lichess. They were recorded before the app knew whether they were rated or which theme you chose them by, and they still count in your Stats.
- If Lichess asks the app to slow down (it allows about 200 solves an hour), the app waits at least a minute before sending anything again, even if you keep solving. The top bar shows how many solves are waiting.

### Excluding puzzles you've played on Lichess
When you sign in, the app reads which puzzles you've played on Lichess, then only the new ones each time. **More filters → Your history → Exclude played on Lichess** (on by default) leaves those puzzles out, along with every puzzle you've synced from here, because Lichess wouldn't rate them again. Untick it to get them back. While you're signed out with no history read yet, it's greyed out.

### Signing out
Open the gear (**⚙**, top right) and choose **Sign out** under **Lichess account**. The app cancels your sign-in on Lichess, then removes it from Windows Credential Manager. Solves still waiting to sync stay waiting.

If Lichess can't be reached, the app asks before removing anything. **Remove from this PC anyway** deletes it here; cancel it yourself later at lichess.org/account/security (*Sessions*/*API access tokens*).

**Gotchas**
- **Sign in as someone else** uses whichever account your browser is signed in to on lichess.org. To switch accounts, sign out of lichess.org in your browser first (or sign in there as the other account).
- After signing in, if the browser tab doesn't close itself, just close it.
- The app may not come back in front of the browser on its own (Windows sometimes blocks that). Click it in the taskbar.
- Your sign-in is stored in Windows Credential Manager under **weaksquare** (Control Panel → Credential Manager → Windows Credentials).

## Keeping the puzzle database up to date
*Added in v0.2.*

Once a day, when you start the app, it checks quietly in the background whether Lichess has published a newer puzzle export. It never interrupts a puzzle. When there's one, a banner appears above your puzzles:

![The update banner](img/update-banner.png)

- **Update now** downloads and imports the new export, exactly like **☰ → Update puzzle database…**. You can keep training meanwhile. When it's finished, the dialog shows the exact numbers, for example *"6,193,530 puzzles: 44,112 new, 7,923 removed."* Your attempts on removed puzzles stay in your history and Stats.
- **Not now** hides the banner until the next time you start the app.
- **Skip this export** stays quiet until Lichess publishes a newer export than this one.

The banner's puzzle count comes from the database.lichess.org page, which can lag behind the file, so it's labeled approximate. If the page can't be read, the line is left out and everything else still works.

**Checking yourself:** **☰ → Update puzzle database… → Check for updates** checks right away, even if the app already checked today, and says what it found.

**Turning it off:** **☰ → Settings… → Check for a newer puzzle database once a day.** Check for updates still works.

**Gotchas**
- Offline, the check stays silent and simply tries again at the next start.
- A database imported from a file you chose has no checksum to compare, so the app compares the export dates instead.
- See [Your data and privacy](#your-data-and-privacy) for exactly what the check sends.

## Choosing your puzzles
*Added in v0.1. Changed in v0.2: ratios, openings, quality, your history, order and presets. Changed in v0.3: Exclude played on Lichess, and Rated.*

The left-hand panel, **Choose your puzzles**, decides which puzzles you get. The count under the filters updates as you change them, so you always know how many puzzles match. The panel scrolls on its own, so the board stays in view.

1. Pick **Themes**, or leave it at **All themes**. To mix themes in fixed shares instead, switch on **Mix by ratio** (below).
2. Choose **ANY** (a puzzle needs at least one of your themes) or **ALL** (it needs every one).
3. Narrow it down with **Exclude themes**, **Rating**, **Number of moves** and **You play**.
4. Open **More filters** for openings, quality and your history. Its summary line shows what's on, even while it's closed.
5. Choose the **Order**, then how many **Puzzles** you want, or switch on **Endless**.
6. Leave **Rated** on to count the session toward your Lichess puzzle rating (see [Rated](#rated)).
7. Press **Start**.

![The filter panel with Fork, ALL, rating 1100–1700 and 2-move puzzles](img/mixer.png)

| Control | What it does |
|---|---|
| **Themes** | Opens a list of every theme in the database, grouped (Motifs, Advanced, Mates, Mate patterns, Phases, Special moves, Goals, Lengths, Origin) with how many puzzles have each. Type in **Search themes** to find one. **Select all** ticks every theme shown by the search; **Clear** unticks everything. Leaving it empty means all themes. |
| **Match: ANY / ALL** | ANY: puzzles with *at least one* chosen theme. ALL: puzzles with *every* chosen theme, e.g. Fork + Long finds long puzzles that involve a fork. |
| **Exclude themes** | Puzzles with *any* of these themes are left out, whatever else they match. |
| **Rating** | Drag either end of the slider, or type exact numbers in the boxes. A typed number applies when you press **Enter** or click elsewhere. If the maximum you type is below the minimum, the minimum moves down to match. The range runs from the easiest to the hardest puzzle in the database. |
| **Number of moves** | How many moves *you* make: 1, 2, 3 or 4 and more. Tick any combination, or **All**. This is counted from the solution itself, not from the One-move/Short/Long/Very long theme tags. |
| **You play** | White, Black or Either. |
| **Puzzles** / **Endless** | A session of a fixed number of puzzles (1 to 500), or an endless one. |
| **Preset** | Loads a saved set of filters. See [Presets](#presets). |
| **Mix by ratio** | Replaces **Themes** with groups, each with a share of the session, e.g. 50% Fork, 30% Pin or Skewer, 20% One-move. A group matches *any* of its themes. Each group shows how many puzzles it has, and the shares must add up to 100% (**Total** turns red until they do). **Add group** re-splits the shares evenly; **Even split** does that for the groups you have. Every other filter applies to all groups. Switching ratios off brings back the themes you had before. |
| **More filters → Openings** | Puzzles from the openings you choose. Type to search. Each opening family is listed with its variations; choosing **(any variation)** takes the whole family. Only puzzles that start before move 20 have an opening, so choosing one leaves out the rest. |
| **More filters → Quality** | **Min popularity** (Lichess players' votes, from -100 to 100) and **Min plays**. They're on by default at 50 and 100, which leaves out puzzles players rated poorly or that few have played. Change either number, or empty a box and press **Enter** to turn it off. |
| **More filters → Your history** | **Exclude solved here** (on by default) leaves out puzzles you've solved at least once in this app; ones you've only failed can still come up. **Exclude played on Lichess** (on by default, *added in v0.3*) leaves out puzzles in your Lichess history, which Lichess wouldn't rate again; it needs a Lichess sign-in. **Only my misses** gives you only puzzles whose last attempt here was a fail, so a puzzle drops out once you solve it. While it's on, the other two aren't needed and are greyed out. |
| **Order** | **Random**; **Easy → hard** (lowest rating first); or **By theme**, which serves all the puzzles of your first chosen theme, then the next (with ratios: group by group). |

No puzzle repeats within a session. Your filters are remembered the next time you open the app, and the count updates as you play, because solved puzzles drop out.

![The theme list with search and Select all / Clear](img/theme-picker.png)

**Gotchas**
- If the count says **0 puzzles match**, Start is disabled. Widen a filter. A common cause is ALL with two themes that never appear together, such as One-move and Very long.
- Themes are hidden while you solve (see below), so choosing a single theme tells you the idea in advance. Mix several themes for a real test.
- **Exclude solved here and Exclude played on Lichess are on by default.** If a puzzle you want to repeat doesn't come up, untick them under **More filters → Your history**. When you're signed in, a puzzle you solve here also syncs to Lichess, so you need to untick both to see it again.
- With ratios, a group with no matching puzzles says **No puzzles: left out**. If you start anyway, a note says so and the other groups share its slots. If a group runs out during the session, the others fill in for it.
- **Easy → hard** and **By theme** sort the whole session when it has a fixed size. With **Endless** they sort each block of 50 puzzles, which the panel points out.
- The filters you used in v0.1 get the new defaults (quality on, Exclude solved on) once, the first time v0.2 opens. After that, your choices are kept.

## Presets
*Added in v0.2.*

A preset is a named set of filters, such as "Combo night" with a 50/30/20 ratio, that you can load in one click. Presets are saved on this PC with the rest of your data.

![Saving a preset](img/presets.png)

1. Set up the filters you want.
2. Click **Save as…**, type a name and click **Save**.
3. Later, choose it from **Preset** to load those filters. You can still change them before you press Start.

The **⋯** button next to it renames or deletes the preset you loaded.

**Gotchas**
- Names are up to 60 characters, and two presets can't share a name, ignoring capitals. If you save under a name that exists, the app asks before replacing it with **Replace it**.
- Loading a preset replaces all your filters. Saving after a change doesn't update the preset unless you save it under the same name and replace it.
- A preset saved by a newer version of the app may use filters this version doesn't have. It's listed as **(can't be used)**, says why, and is left untouched.

## Stats
*Added in v0.2. Changed in v0.3: the Lichess rating trend.*

Choose **☰ → Stats** to see how you're doing across every puzzle you've played in this app.

![Your stats](img/stats.png)

- **Puzzles played** and **Accuracy**: a puzzle counts as solved only with no wrong move and no help.
- **First move right, line wrong**: of the puzzles where your first move was right, how often the rest of the line went wrong. Spotting the idea but miscalculating the follow-up shows up here, so a falling number means your calculation is improving.
- **By theme**, **By length** (how many moves you make) and **By rating** (200-point bands, using the puzzle's rating when you played it) break the same numbers down. A puzzle with several themes counts once under each.
- **Lichess puzzle rating** (*added in v0.3*): your rating over time, one point each time Lichess reported a new rating for your synced solves, and a table of the change in each session (newest first). Hover over the line to see a point's rating. It's empty until you sign in with Lichess and sync rated puzzles. The numbers are exactly what Lichess returned.

**Gotchas**
- If a database update removes a puzzle you played, your attempt still counts in the totals and by rating, but not by theme or length. A note under the tables says how many.
- Attempts from v0.1 get their puzzle's rating filled in the first time you open Stats, where the puzzle is still in the database.

## Solving a puzzle
*Added in v0.1. Changed in v0.2: Hint, Show answer and keyboard shortcuts.*

1. The board turns to your side and the opponent's move plays first. Then it's your turn: find the best move.
2. Drag a piece, or click it and then its destination. When a pawn promotes, choose the piece.
3. If your move is right, the opponent's reply plays automatically. Keep going until the line is complete.
4. When the puzzle ends, the result panel shows whether you **Solved** or **Failed** it, and reveals its **themes**. When you're signed in, it also shows the **Lichess rating** change (see [Your puzzle rating](#your-puzzle-rating)). **Open this puzzle on Lichess** shows it on the Lichess website.
5. Press **Next puzzle**.

![The trainer, waiting for your move](img/trainer.png)

**How it's scored**
- **Solved** means you played every move of the solution with no wrong move.
- A **wrong move fails the puzzle at once**. The move is taken back and you can keep trying to finish the line, with nothing more to lose.
- When the solution is a checkmate, **any** checkmating move counts.
- Pressing **Skip (counts as failed)** before you've finished also records a failed attempt.
- Using **Hint** or **Show answer** before the puzzle is decided fails it too (see below). After it's decided, Show answer is free.

**The session bar** at the top shows this session's **Solved**, **Failed**, **Accuracy** and **Played**, and once you're signed in to Lichess, the rating change this session (e.g. **+34 this session**). On the right, **All time** counts every attempt you've ever made; your attempts are saved as you go, so they survive closing the app. When a fixed-length session ends, you get a summary and a **New session** button.

![A solved puzzle with its themes revealed](img/solved.png)

## Getting unstuck: Hint and Show answer
*Added in v0.2.*

When you can't find the move, the **Hint** and **Show answer** buttons beside the board help, one step at a time.

1. **Hint** circles the piece that moves next. You can still play the move and finish the line yourself.
2. **Show answer** unlocks once you've used a Hint. It shows the rest of the solution from where you are, one move at a time: **Forward ▶** plays the next move (yours and the opponent's replies), **◀ Back** takes it back, and the line under the board names each move. The puzzle ends there, and **Next puzzle** moves on.

![A hint: the circled knight moves next](img/hint.png)

![Stepping through the answer](img/answer.png)

**How it's scored**
- Using either button **before the puzzle is decided fails it** (like on Lichess), and your Stats record that you needed help. The result panel shows **Failed** and the themes straight away.
- If the puzzle is already decided (a wrong move, or you finished the line), Show answer is free and doesn't need a Hint. After a solved puzzle it replays the whole solution from the start.
- After a wrong move you can open the answer directly. *Changed in v0.4:* it then starts by showing why your wrong move fails, using Stockfish (see [Stockfish](#stockfish-why-a-move-fails-evals-and-the-analysis-board)).

## Stockfish: why a move fails, evals and the analysis board
*Added in v0.4.*

WeakSquare uses **Stockfish 19**, the free chess engine, running on your PC. It's there to help you learn from a puzzle **after** you've tried it: it never shows an evaluation, a line or a hint while a puzzle is in progress.

### Installing Stockfish
Setup installs it for you (see [Installing from source](#installing-from-source)). If it isn't installed, the places that use it show **Stockfish isn't installed** with an **Install Stockfish** button:

![Stockfish isn't installed](img/engine-install.png)

1. Click **Install Stockfish**. The app downloads the official Stockfish 19 build from GitHub (about 80 MB) and shows its progress.
2. Before using the file, the app checks it against a fingerprint (SHA-256) recorded in the app, so a damaged or altered download is refused and deleted. It then runs a short self-test.
3. When it's done, the engine panel appears. You don't need to restart.

Stockfish is stored in your data folder under `engines\sf_19`. Each data folder has its own copy.

### Why your move fails
If you play a wrong move and then click **Show answer**, the answer starts with **Why *your move* fails**. It shows your move, then Stockfish's best reply line (up to 5 moves by both sides), with the evaluation. Step through it with **Forward ▶** and **◀ Back** (or **→** and **←**), then carry on into **The solution**.

![Why your move fails](img/refutation.png)

If you made several wrong moves, the first one is shown: that's the one that cost you the puzzle. If you didn't play a wrong move, Show answer goes straight to the solution.

### The engine panel
Once the puzzle is over (you finished the line, or you used Show answer), the **Stockfish** panel appears beside the board:
- **Puzzle start:** the evaluation of the position you had to solve, kept at the top.
- **This position:** the evaluation and Stockfish's **top 3 lines** for whatever is on the board. It follows you as you step through the answer.

![The engine panel after a puzzle](img/engine-panel.png)

**Reading the evaluation.** Evaluations are always from **your side** (the side you played in the puzzle):

| You see | It means |
|---|---|
| **+3.2 for you** | You're ahead by about three pawns' worth. |
| **−1.4 for you** | You're behind by about one and a half pawns. |
| **0.0 (level)** | Neither side is better. |
| **You mate in 3** / **You're mated in 2** | A forced checkmate, in that many of the mating side's moves. |

### The analysis board
Click **Analyze on the board** in the panel to play out your own ideas. You can move pieces for **either side** (legal moves only), and after each move Stockfish re-evaluates and draws an arrow for its best move. **◀ Back** and **Forward ▶** step through your moves, **Reset** goes back to the puzzle position, and **Close** returns to the puzzle. Nothing you do on the analysis board is scored or saved.

![The analysis board](img/analysis-board.png)

### Engine settings
In **⚙ Settings → Engine**:

| Setting | What it does |
|---|---|
| **Think time (s)** | How long Stockfish thinks about each position. 1 second by default, from 0.2 to 10. Longer is a little stronger and keeps the CPU busy for longer. |
| **Threads** | How many processor cores it may use. By default all but one, so the app stays responsive. |
| **Hash (MB)** | Memory for the engine's working tables. 256 MB by default, from 16 to 2048. |
| **Use my own engine…** | Pick another UCI engine's `.exe` (for example a Stockfish build you prefer). It's used only if it passes the same self-test. **Use the managed Stockfish** switches back. |
| **Reinstall** | Downloads and checks the pinned Stockfish again. |

![Settings, Engine](img/settings-engine.png)

**Gotchas**
- Stockfish only thinks when you look at a position after a puzzle (about one think time per position), so it doesn't use the CPU while you solve. Stepping quickly through a line asks about the newest position only.
- If Stockfish ever stops unexpectedly, the app restarts it and says so. Try again.
- If your own engine can't be found any more (the file was moved or deleted), the app says so and offers **Use the managed Stockfish**.

## Keyboard shortcuts
*Added in v0.2.*

| Key | What it does |
|---|---|
| **N** or **Enter** | Next puzzle (before the puzzle is decided, that's Skip, which counts as failed). On the session summary, a new session. |
| **H** | Hint |
| **A** | Show answer (once it's unlocked) |
| **←** / **→** | Step back / forward through the answer, or through your moves on the analysis board (v0.4) |
| **C** | Show or hide the letters and numbers around the board |
| **?** | The list of shortcuts (also in **☰ → Keyboard shortcuts**) |

Shortcuts do nothing while you're typing in a box or a dialog is open, and a key does nothing when its button is greyed out.

**Board coordinates:** press **C**, choose **☰ → Hide board coordinates** / **Show board coordinates**, or use the switch in **Settings**. Your choice is saved.

## Appearance and sounds
*Added in v0.2.*

Click the gear (**⚙**, top right) or choose **☰ → Settings…** to change how the app looks and sounds. *Changed in v0.4:* it also has an **Engine** section (see [Engine settings](#engine-settings)). *Changed in v0.3:* the same dialog starts with **Lichess account**, where you sign in or out (see [Signing in with Lichess](#signing-in-with-lichess-syncing-solves-offline-mode)). Every change applies at once and is saved on this PC, so the app starts the same way next time.

![The Settings dialog](img/settings.png)

| Setting | What it does |
|---|---|
| **Appearance: Light / Dark / Match system** | The color scheme for every screen. **Light** is the default. **Match system** follows the Windows app mode (Settings → Personalization → Colors → *Choose your app mode*) and switches as soon as you change it, even with WeakSquare open. The board keeps its usual colors in every scheme. |
| **Board coordinates** | The letters and numbers around the board (also **C**). |
| **Move sounds** | On by default. Sounds for your moves and the opponent's (a move, a capture, a check, a mate), and for a solved or failed puzzle. Off is completely silent. |
| **Volume** | 70% by default. |
| **Sound set** | **Standard effects (sfx)** (the default), **Piano**, **8-bit (NES)** or **Futuristic**. **Play a sample** plays a capture in the chosen set. |

![The trainer in Dark](img/trainer-dark.png)

**Gotchas**
- The app opens in your saved scheme straight away. If WeakSquare can't read the saved setting within a second and a half, it opens in Light and switches as soon as it can.
- Castling plays the ordinary move sound, because none of the sets has a castling sound. In these sets, checkmate uses the check sound. A mate plays only that sound (not also a capture or a check), followed by the solved sound.
- A new sound cuts off the one before, so fast moves never pile up.
- The sounds are Lichess's sets by Enigmahack, licensed AGPL-3.0 like this app. They're bundled with the app, so nothing is downloaded when they play.

## Installing from source
*Added in v0.1. Changed in v0.2: a desktop shortcut and the app icon.*

WeakSquare runs from its source code; there's no installer to download. You need Windows 10 or 11 with **Git**, **Python 3.12 or newer** and **Node.js LTS** installed.

1. Open PowerShell (or a Command Prompt) in the folder where you want the app, and run:
   ```powershell
   git clone https://github.com/adamwp1993/weaksquare-chess-trainer
   cd weaksquare-chess-trainer
   python scripts/setup.py
   ```
2. Setup takes a few minutes. It installs everything into the project folder, builds the app, downloads and imports the puzzle database (see *Getting started*), installs Stockfish (*Added in v0.4*; add `--skip-engine` to install it from the app later), and adds **WeakSquare Chess Trainer** to your Start menu and your desktop. To skip the puzzle download, add `--skip-puzzle-db`; the app then offers it on first run.
3. Start the app from the Start menu or the desktop.

Both shortcuts, the window and its taskbar button show the WeakSquare icon: four board squares with a black queen. `--no-desktop-shortcut` skips the desktop one, and `--no-shortcut` skips both. If your Desktop is in OneDrive, the shortcut goes there, where Windows shows it.

**Updating:** in the same folder, run `git pull`, then `python scripts/setup.py` again. Setup skips anything that's already up to date, and your data isn't touched.

**Gotchas**
- If setup says uv isn't on your PATH, that's fine: setup carries on without it.
- Only one copy of the app runs at a time. Starting it again brings the open window to the front.
- Running setup again replaces the two shortcuts rather than adding more. If you deleted the desktop shortcut on purpose, use `--no-desktop-shortcut` next time.
- A shortcut you pinned to the taskbar yourself, before v0.2, keeps its old icon. Unpin it and pin the app again.

## The About screen
*Added in v0.1. Changed in v0.4: the Stockfish row.*

Open the menu (**☰**, top right) and choose **About** to see:

![The About screen](img/about.png)


| Item | What it shows |
|---|---|
| **Version** | The app version you're running. |
| **Data folder** | Where your puzzles, attempts and settings live. **Open** shows it in File Explorer. |
| **Logs folder** | Log files that help diagnose problems. **Open** shows it in File Explorer. Sign-in tokens and keys are removed before anything is written. |
| **Puzzle database** | How many puzzles are imported, and the date of the Lichess export they came from. |
| **Stockfish** | *Added in v0.4.* The engine in use (Stockfish 19, or your own) and where its program file is, or that it isn't installed. |
| **License** and **Source code** | The app is open source under AGPL-3.0-or-later. The link opens the code in your browser. |
