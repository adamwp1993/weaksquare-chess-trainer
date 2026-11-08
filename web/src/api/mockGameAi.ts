// The mock's Game Review AI answers (v0.9): fixed text built from the game's real moves and the mock's
// analysis, so every move and arrow is legal. Like the backend's, the narrative has one discarded item
// (an unknown preset theme), so the "some annotations were discarded" note can be seen and tested.
import { Chess } from "chess.js";
import type { Explanation, GameNarrative, GameReview, ReviewMove } from "./types";

/** Explain this move: Stockfish's best move as the one-step "solution", like the backend's move_input. */
export function moveExplanation(move: ReviewMove, provider: string, model: string, costUsd: number): Explanation {
  const best = move.best_move ?? move.uci;
  const san = move.best_san ?? move.san;
  const played = best === move.uci;
  return {
    summary: played
      ? `${move.san} was the best move here: it keeps the pressure on.`
      : `${move.san} let your opponent in. ${san} was better: it keeps your pieces covered.`,
    steps: [
      {
        ply: 0,
        side: "you",
        san,
        uci: best,
        text: played ? "It improves your worst piece with tempo." : `${san} guards the square your opponent wanted.`,
        annotations: [
          { kind: "arrow", orig: best.slice(0, 2), dest: best.slice(2, 4), color: "green" },
          ...(played ? [] : [{ kind: "arrow" as const, orig: move.uci.slice(0, 2), dest: move.uci.slice(2, 4), color: "red" as const }]),
        ],
        variation: [],
      },
    ],
    key_ideas: played ? ["development"] : ["hanging piece", "loose pieces"],
    discarded: 0,
    provider,
    model,
    cost_usd: costUsd,
    cached: false,
    start_fen: move.fen_before,
    solution: [best],
  };
}

/** Explain my game: a short narrative over the key moments, with a recommended preset. */
export function gameNarrative(review: GameReview, n: number, plies: number[], provider: string, model: string, costUsd: number): GameNarrative {
  const moments = plies.map((ply) => {
    const m = review.moves[ply];
    const best = m.best_move ?? m.uci;
    const chess = new Chess(m.fen_before);
    const better = chess.move({ from: best.slice(0, 2), to: best.slice(2, 4), promotion: best[4] }).san;
    return {
      ply,
      played_san: m.san,
      text: `${m.san} left a piece without a defender, and your opponent's reply took it. ${better} kept everything covered.`,
      annotations: [
        { kind: "arrow" as const, orig: m.uci.slice(0, 2), dest: m.uci.slice(2, 4), color: "red" as const },
        { kind: "arrow" as const, orig: best.slice(0, 2), dest: best.slice(2, 4), color: "green" as const },
      ],
      better_line: [better],
      better_uci: [best],
    };
  });
  return {
    game_id: review.game.id,
    n,
    key_moments: plies,
    opening_summary: "You reached a normal position out of the opening, then the game turned on one loose piece.",
    turning_point: plies.length ? plies[plies.length - 1] : null,
    themes: ["loose pieces", "checking your opponent's threats"],
    takeaways: [
      "Before each move, look at what your opponent's last move attacks.",
      "Count the defenders of every piece you move away from.",
    ],
    moments,
    preset: { themes: ["hangingPiece", "fork"], names: ["Hanging piece", "Fork"], rating_min: 1200, rating_max: 1700 },
    discarded: 1,
    did_well: review.stories.flatMap((st) => st.strengths).slice(0, 2).map((x) => ({
      fact: x.text,
      text: "Spotting that kept the pressure on and gave your opponent no time to recover.",
    })),
    provider,
    model,
    cost_usd: costUsd,
    cached: false,
  };
}
