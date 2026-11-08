// v0.13: walking a line in Learn mode (FR-12.6, 12.16). Pure, so step-through and play-along share one set of rules,
// and v0.14's studies can reuse them. The moves come from the backend: this only replays them and compares yours.
import { Chess } from "chess.js";
import type { OpeningLineMove } from "../api/types";

export const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

export interface LinePosition {
  fen: string;
  lastMove: [string, string] | null;
}

/** One position per step: the start, then after each move. */
export function linePositions(moves: OpeningLineMove[]): LinePosition[] {
  const chess = new Chess();
  const out: LinePosition[] = [{ fen: chess.fen(), lastMove: null }];
  for (const m of moves) {
    const played = chess.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
    out.push({ fen: chess.fen(), lastMove: [played.from, played.to] });
  }
  return out;
}

export function sideToMove(fen: string): "white" | "black" {
  return fen.split(" ")[1] === "w" ? "white" : "black";
}

export type PlayResult =
  | { kind: "correct" }
  | { kind: "wrong"; nudge: string }
  | { kind: "finished" };

/** Play-along: your move against the line's next one. A wrong move gets a nudge and you try again (FR-12.16). */
export function checkMove(moves: OpeningLineMove[], step: number, uci: string): PlayResult {
  const expected = moves[step];
  if (!expected) return { kind: "finished" };
  if (uci === expected.uci) return { kind: "correct" };
  return { kind: "wrong", nudge: `Not this line's move. Try the piece on ${expected.uci.slice(0, 2)}.` };
}

/** The label for where a move came from (FR-12.13). */
export function sourceLabel(source: string): string {
  if (source === "engine") return "Stockfish";
  if (source === "explorer") return "Popular";
  if (source === "you") return "You";
  if (source === "study") return "Study"; // v0.14 (FR-13.11): added from a Lichess study
  return "Book";
}

/** "1. e4 e5 2. Nf3" with each move's own number, for a move list. */
export function moveLabel(step: number): string {
  const number = Math.floor(step / 2) + 1;
  return step % 2 === 0 ? `${number}.` : `${number}…`;
}
