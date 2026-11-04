// v0.8: shared bits for My games, Game Review and My puzzles.
import type { ReasonKey } from "../api/ApiClient";
import type { GameSummary, ReasonOption, ReasonPrompt } from "../api/types";

/** FR-5.6, in chip order (keys 1–6). The same fixed set the backend uses for puzzles. */
export const REASON_OPTIONS: ReasonOption[] = [
  { key: "didntLook", label: "Didn't look for it", gap: "process" },
  { key: "missedResource", label: "Missed their reply / defense / threat", gap: "process" },
  { key: "miscalculated", label: "Saw the idea, calculated it wrong", gap: "calculation" },
  { key: "unknownPattern", label: "Didn't know this pattern", gap: "knowledge" },
  { key: "rushed", label: "Rushed / time pressure", gap: "time" },
  { key: "misclick", label: "Misclick", gap: "noise" },
];

/** A prompt for the reason chips on a game move or a Retry miss (the chips don't use attempt_id). */
export function gamePrompt(suggested: ReasonKey | null): ReasonPrompt {
  return { attempt_id: 0, source: "puzzle", suggested, reasons: REASON_OPTIONS };
}

export const PLATFORM_LABEL: Record<GameSummary["source"], string> = {
  lichess: "Lichess",
  chesscom: "chess.com",
  paste: "Pasted",
  file: "File",
};

export const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "daily"] as const;

export function cap(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** "2026-10-30T18:20:00+00:00" → "2026-10-30" (the game's own date; no clock needed). */
export function gameDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

export function resultLabel(g: GameSummary): string {
  if (g.user_result === "win") return "Won";
  if (g.user_result === "loss") return "Lost";
  if (g.user_result === "draw") return "Draw";
  return g.result === "*" ? "—" : g.result;
}

/** "Move 4" for ply 6 (White's 4th move), "Move 4…" for Black's. */
export function moveLabel(ply: number): string {
  return `${Math.floor(ply / 2) + 1}${ply % 2 === 1 ? "…" : "."}`;
}

export const CLASS_COLOR: Record<string, string> = {
  inaccuracy: "yellow",
  mistake: "orange",
  blunder: "red",
};
