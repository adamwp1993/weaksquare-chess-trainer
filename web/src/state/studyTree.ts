// v0.14 (FR-13.8, 13.10): walking a study chapter's move tree. The backend sends it flattened (bridge/api.py
// `_flatten_study_tree`): moves[0] is the start position, children[0] is the main line, the rest side lines.
import type { StudyMove } from "../api/types";

/** The UCI moves from the start to `id`: your place, as saved (FR-13.10). */
export function pathTo(moves: StudyMove[], id: number): string[] {
  const out: string[] = [];
  let n: StudyMove | undefined = moves[id];
  while (n && n.parent !== null) {
    out.push(n.uci ?? "");
    n = moves[n.parent];
  }
  return out.reverse();
}

/** The node a saved path reaches, or as far as it still goes (a study can change under a saved place). */
export function follow(moves: StudyMove[], path: string[]): number {
  let id = 0;
  for (const uci of path) {
    const next = moves[id]?.children.find((c) => moves[c].uci === uci);
    if (next === undefined) break;
    id = next;
  }
  return id;
}

/** Whether `id` is on the chapter's main line (every step is a first child). */
export function onMainLine(moves: StudyMove[], id: number): boolean {
  let n = moves[id];
  while (n.parent !== null) {
    if (moves[n.parent].children[0] !== n.id) return false;
    n = moves[n.parent];
  }
  return true;
}

/** "Back to main line": the last main-line move before the current side line left it. */
export function backToMainLine(moves: StudyMove[], id: number): number {
  let n = id;
  while (!onMainLine(moves, n)) n = moves[n].parent ?? 0;
  return n;
}

export function mainLineEnd(moves: StudyMove[]): number {
  let id = 0;
  while (moves[id].children.length) id = moves[id].children[0];
  return id;
}

export function sideToMove(fen: string): "white" | "black" {
  return fen.split(" ")[1] === "b" ? "black" : "white";
}

/** "12." before a White move, "12…" before a Black one, from the position the move was played in. */
export function moveNumber(moves: StudyMove[], id: number): { number: number; white: boolean } {
  const parentFen = moves[moves[id].parent ?? 0].fen.split(" ");
  return { number: Number(parentFen[5]) || 1, white: parentFen[1] !== "b" };
}

const NAGS: Record<number, string> = { 1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!" };

export function nagText(nags: number[]): string {
  return nags.map((n) => NAGS[n] ?? "").join("");
}

export type GamebookResult =
  | { kind: "correct"; next: number }
  | { kind: "covered"; feedback: string } // a wrong move the author wrote about
  | { kind: "wrong" };

/** FR-13.8, gamebook chapters: your move against the author's. Nothing is scored. */
export function checkGamebookMove(moves: StudyMove[], at: number, uci: string): GamebookResult {
  const kids = moves[at].children;
  if (kids.length && moves[kids[0]].uci === uci) return { kind: "correct", next: kids[0] };
  const side = kids.slice(1).find((c) => moves[c].uci === uci);
  if (side !== undefined) {
    const text = moves[side].comment.trim();
    return { kind: "covered", feedback: text || "That's not the move this chapter is after. Try again." };
  }
  return { kind: "wrong" };
}
