import type { TrainingMode } from "../api/ApiClient";

// The Modes control (§6), in order. Modes from later versions join here when they ship.
export const MODES: { value: TrainingMode; label: string; description: string }[] = [
  {
    value: "standard",
    label: "Standard",
    description: "Find the best move; the opponent replies automatically.",
  },
  {
    value: "commit_line",
    label: "Commit the line",
    description: "Enter the whole line, your moves and the replies you expect, then press Submit.",
  },
  {
    value: "spaced_repetition",
    label: "Spaced repetition",
    description: "Puzzles you missed come back on their review day.",
  },
];

export function modeLabel(mode: TrainingMode): string {
  return MODES.find((m) => m.value === mode)?.label ?? mode;
}

/** "Tue 4 Nov" for an ISO date, without time zones getting involved. */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  const day = date.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  const month = date.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" });
  return `${day} ${d} ${month}`;
}
