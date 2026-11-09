// The mock client's "engine": deterministic lines from chess.js, for UI development and Playwright.
// Moves are ranked mates first, then captures (by the captured piece), then the rest by UCI; each pv
// is the move plus up to five greedy replies. Scores are worded from the solver's side, like the
// backend's core/engine.format_score (FR-7.2).
import { Chess, type Move } from "chess.js";
import type { Analysis, EngineLine } from "./types";

const VALUE: Record<string, number> = {
  p: 100,
  n: 300,
  b: 310,
  r: 500,
  q: 900,
  k: 0,
};

interface Ranked {
  uci: string;
  mate: boolean;
  gain: number;
}

function uciOf(m: Move) {
  return m.from + m.to + (m.promotion ?? "");
}

function ranked(chess: Chess): Ranked[] {
  return chess
    .moves({ verbose: true })
    .map((m) => {
      const probe = new Chess(chess.fen());
      probe.move(m);
      return {
        uci: uciOf(m),
        mate: probe.isCheckmate(),
        gain: m.captured ? VALUE[m.captured] : 0,
      };
    })
    .sort(
      (a, b) =>
        Number(b.mate) - Number(a.mate) ||
        b.gain - a.gain ||
        a.uci.localeCompare(b.uci),
    );
}

function play(chess: Chess, uci: string) {
  chess.move({
    from: uci.slice(0, 2),
    to: uci.slice(2, 4),
    promotion: uci.length > 4 ? uci[4] : undefined,
  });
}

/** "both": the Analysis tab (v0.15), worded from White's side. */
type Viewpoint = "white" | "black" | "both";

export function formatScore(cp: number | null, mate: number | null, player: Viewpoint = "white"): string {
  const both = player === "both";
  if (mate !== null) {
    if (both) return `${mate > 0 ? "White" : "Black"} mates in ${Math.abs(mate)}`;
    return mate > 0 ? `You mate in ${mate}` : `You're mated in ${-mate}`;
  }
  const v = (cp ?? 0) / 100;
  if (Math.abs(v) < 0.05) return "0.0 (level)";
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}${both ? "" : " for you"}`;
}

function gameOver(chess: Chess, player: Viewpoint): string | null {
  if (chess.isCheckmate()) {
    const mated = chess.turn() === "w" ? "white" : "black";
    if (player === "both") return mated === "white" ? "Checkmate: Black wins" : "Checkmate: White wins";
    return mated === player ? "You're checkmated" : "Checkmate: you win";
  }
  if (chess.isStalemate()) return "Stalemate: a draw";
  if (chess.isInsufficientMaterial()) return "Draw: insufficient material";
  return null;
}

/** MultiPV lines for `fen`, scored from `player`'s side. */
export function mockAnalysis(
  fen: string,
  player: Viewpoint,
  multipv = 3,
): Analysis {
  const chess = new Chess(fen);
  const over = gameOver(chess, player);
  if (over) return { fen, lines: [], game_over: over, superseded: false };
  const mover = chess.turn() === "w" ? "white" : "black";
  const sign = mover === (player === "both" ? "white" : player) ? 1 : -1;
  const lines: EngineLine[] = ranked(chess)
    .slice(0, multipv)
    .map((r, i) => {
      const b = new Chess(fen);
      play(b, r.uci);
      const pv = [r.uci];
      while (pv.length < 6 && !b.isGameOver()) {
        const best = ranked(b)[0];
        play(b, best.uci);
        pv.push(best.uci);
      }
      const mate = r.mate ? sign : null;
      const cp = r.mate ? null : sign * (r.gain + 35 - i * 20);
      return { score: formatScore(cp, mate, player), cp, mate, pv };
    });
  return { fen, lines, game_over: null, superseded: false };
}
