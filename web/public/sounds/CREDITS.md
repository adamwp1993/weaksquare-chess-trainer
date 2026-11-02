# Sound credits

The move sounds (FR-1.13) are four of Lichess's sound sets, made by [Enigmahack](https://github.com/Enigmahack) and licensed **AGPL-3.0-or-later**, the same license as this app. Lichess lists them in [`COPYING.md`](https://github.com/lichess-org/lila/blob/9934f0a6efa320e71575308c874f4bff5e00225c/COPYING.md) (`public/sounds/futuristic`, `nes`, `piano` and `sfx`: Enigmahack, AGPLv3+).

- **Source:** `https://github.com/lichess-org/lila/tree/9934f0a6efa320e71575308c874f4bff5e00225c/public/sound/<set>/`, at commit `9934f0a6efa320e71575308c874f4bff5e00225c` (2026-11-01). Only the `.ogg` files are used.
- **Not used:** Lichess's default "standard" set and the other sets that `COPYING.md` lists as non-free exceptions, and `lisp` (CC BY-NC-SA, not AGPL-compatible).
- **Changes:** none, except that each set's `Checkmate.ogg` is a copy of its `Check.ogg`, because in lila it's a symlink to that file.
- **Castling** has no sound of its own in these sets, so it plays `Move.ogg`. **Puzzle solved** plays `Victory.ogg` (in sfx: `GenericNotify.ogg`, chosen by Adam in the v0.2 manual test because sfx's Victory was too loud and long) and **puzzle failed** plays `Defeat.ogg`.

`tests/contract/test_sound_credits.py` checks that every file in this folder is listed here and every listed file exists.

| File | Author | License | SHA-256 |
|---|---|---|---|
| `futuristic/Capture.ogg` | Enigmahack | AGPL-3.0-or-later | `a9ccdeb949eb4515…` |
| `futuristic/Check.ogg` | Enigmahack | AGPL-3.0-or-later | `19803dc3853ac599…` |
| `futuristic/Checkmate.ogg` | Enigmahack | AGPL-3.0-or-later | `19803dc3853ac599…` (a copy of Check.ogg: lila's Checkmate.ogg is a symlink to it) |
| `futuristic/Defeat.ogg` | Enigmahack | AGPL-3.0-or-later | `391cca7ab7b907af…` |
| `futuristic/Move.ogg` | Enigmahack | AGPL-3.0-or-later | `5a392004b58ef1bb…` |
| `futuristic/Victory.ogg` | Enigmahack | AGPL-3.0-or-later | `64f79defd729caff…` |
| `nes/Capture.ogg` | Enigmahack | AGPL-3.0-or-later | `7324d28582ac4798…` |
| `nes/Check.ogg` | Enigmahack | AGPL-3.0-or-later | `c4ff9d8188d64f25…` |
| `nes/Checkmate.ogg` | Enigmahack | AGPL-3.0-or-later | `c4ff9d8188d64f25…` (a copy of Check.ogg: lila's Checkmate.ogg is a symlink to it) |
| `nes/Defeat.ogg` | Enigmahack | AGPL-3.0-or-later | `4dbd676d6f178873…` |
| `nes/Move.ogg` | Enigmahack | AGPL-3.0-or-later | `b62f4fc772488147…` |
| `nes/Victory.ogg` | Enigmahack | AGPL-3.0-or-later | `a4a354c9ab363008…` |
| `piano/Capture.ogg` | Enigmahack | AGPL-3.0-or-later | `50eb46a84373cf67…` |
| `piano/Check.ogg` | Enigmahack | AGPL-3.0-or-later | `9a9e94449194c9a5…` |
| `piano/Checkmate.ogg` | Enigmahack | AGPL-3.0-or-later | `9a9e94449194c9a5…` (a copy of Check.ogg: lila's Checkmate.ogg is a symlink to it) |
| `piano/Defeat.ogg` | Enigmahack | AGPL-3.0-or-later | `cda1545d55391422…` |
| `piano/Move.ogg` | Enigmahack | AGPL-3.0-or-later | `bab61fb5a5798e19…` |
| `piano/Victory.ogg` | Enigmahack | AGPL-3.0-or-later | `77c1b204716609fd…` |
| `sfx/Capture.ogg` | Enigmahack | AGPL-3.0-or-later | `02a34072cbea8e2f…` |
| `sfx/Check.ogg` | Enigmahack | AGPL-3.0-or-later | `f3dcea0448052894…` |
| `sfx/Checkmate.ogg` | Enigmahack | AGPL-3.0-or-later | `f3dcea0448052894…` (a copy of Check.ogg: lila's Checkmate.ogg is a symlink to it) |
| `sfx/Defeat.ogg` | Enigmahack | AGPL-3.0-or-later | `c29f4e9def07a47d…` |
| `sfx/Move.ogg` | Enigmahack | AGPL-3.0-or-later | `af2eb5498a76d40a…` |
| `sfx/GenericNotify.ogg` | Enigmahack | AGPL-3.0-or-later | `5432f3c89260dad7…` |
