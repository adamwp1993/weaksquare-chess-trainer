// v0.15 (FR-14.4): the Analysis tab's lines, as a move tree in the study tree's shape (state/studyTree.ts): moves[0] is
// the start position, children[0] the main line, the rest side lines. A move you try that isn't there yet becomes a new
// branch; one that is just goes there. The tree lives in the page only, for as long as the app is open (Adam, v0.15
// planning), and nothing in it is scored or saved (FR-14.5).
import { Chess } from "chess.js";
import type { StudyMove } from "../api/types";

export const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/** Open in Analysis tab (FR-14.6): a line from its start, with the cursor after `cursor` moves. */
export interface AnalysisLine {
  startFen: string;
  ucis: string[];
  cursor: number;
  orientation: "white" | "black";
}

export interface AnalysisTree {
  moves: StudyMove[];
  cur: number;
}

export function newTree(fen: string = START_FEN): AnalysisTree {
  return {
    moves: [{ id: 0, parent: null, san: null, uci: null, fen, ply: 0, comment: "", shapes: [], nags: [], children: [] }],
    cur: 0,
  };
}

/** Whether there's anything to lose: any move at all. */
export function hasMoves(tree: AnalysisTree): boolean {
  return tree.moves.length > 1;
}

/** Play `uci` from the current position: to the existing move, or as a new branch. Null if it isn't legal. */
export function playMove(tree: AnalysisTree, uci: string): AnalysisTree | null {
  const { moves, cur } = tree;
  const here = moves[cur];
  const existing = here.children.find((c) => moves[c].uci === uci);
  if (existing !== undefined) return { moves, cur: existing };
  const chess = new Chess(here.fen);
  let m;
  try {
    m = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined });
  } catch {
    return null;
  }
  const id = moves.length;
  const node: StudyMove = {
    id, parent: cur, san: m.san, uci: m.from + m.to + (m.promotion ?? ""), fen: chess.fen(), ply: here.ply + 1,
    comment: "", shapes: [], nags: [], children: [],
  }; // prettier-ignore
  const next = moves.slice();
  next[cur] = { ...here, children: [...here.children, id] };
  next.push(node);
  return { moves: next, cur: id };
}

/** A line from a start position, as the main line, with the cursor after `cursor` moves (Open in Analysis tab). Stops
 * at the first move that isn't legal. */
export function treeFromLine(startFen: string, ucis: string[], cursor: number = ucis.length): AnalysisTree {
  let tree = newTree(startFen);
  const ids = [0];
  for (const uci of ucis) {
    const next = playMove(tree, uci);
    if (!next) break;
    tree = next;
    ids.push(next.cur);
  }
  return { moves: tree.moves, cur: ids[Math.max(0, Math.min(cursor, ids.length - 1))] };
}

/** "12. e4" style label for the move just played, or "Start". */
export function lastMoveLabel(moves: StudyMove[], id: number): string {
  const n = moves[id];
  if (n.parent === null) return "Start";
  const fen = moves[n.parent].fen.split(" ");
  const num = Number(fen[5]) || 1;
  return fen[1] === "b" ? `${num}… ${n.san}` : `${num}. ${n.san}`;
}

/** The UCI of each position's move, from its last move and SAN (promotion from "=Q"). For lines kept as positions. */
export function uciOf(lastMove: [string, string] | null, san: string | null): string | null {
  if (!lastMove) return null;
  const promo = san?.match(/=([QRBN])/)?.[1]?.toLowerCase() ?? "";
  return lastMove[0] + lastMove[1] + promo;
}

/** Compare positions by their first four FEN fields (the move counters don't make a different position). */
export function samePosition(a: string, b: string): boolean {
  return a.split(" ").slice(0, 4).join(" ") === b.split(" ").slice(0, 4).join(" ");
}

/** The moves of `line` (from `start`) that lead to `target`, or null if it never gets there. */
export function prefixTo(start: string, line: string[], target: string): string[] | null {
  let chess: Chess;
  try {
    chess = new Chess(start);
  } catch {
    return null;
  }
  if (samePosition(chess.fen(), target)) return [];
  for (let i = 0; i < line.length; i++) {
    try {
      chess.move({ from: line[i].slice(0, 2), to: line[i].slice(2, 4), promotion: line[i][4] });
    } catch {
      return null;
    }
    if (samePosition(chess.fen(), target)) return line.slice(0, i + 1);
  }
  return null;
}
