import type { TrainingMode } from "../api/ApiClient";

// The Modes control (§6), in order (v0.5, v0.6). Modes from later versions join here when they ship.
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
    value: "name_idea",
    label: "Name the idea first",
    description: "Tag the idea (setup and payoff) before you move, then solve as usual.",
  },
  {
    value: "danger_spotting",
    label: "Danger spotting",
    description: "Is the highlighted move safe? If not, punish it. Needs Stockfish; results stay on this PC.",
  },
  {
    value: "spaced_repetition",
    label: "Spaced repetition",
    description: "Puzzles you missed come back on their review day.",
  },
];

/** FR-3.11: the modes the depth-ladder order works in. */
export const LADDER_MODES: TrainingMode[] = ["standard", "commit_line"];

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
