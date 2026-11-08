import { Button, Group, Stack, Text } from "@mantine/core";
import { Chess } from "chess.js";
import { type AnalysisLine, prefixTo, uciOf } from "../state/analysisTree";
import type { AnswerPosition } from "./AnswerPlayer";

/** The analysis board's moves (FR-7.7): positions from where you opened it, and where you are. */
export interface AnalysisState {
  positions: AnswerPosition[];
  step: number;
}

export function openAnalysis(fen: string): AnalysisState {
  return {
    positions: [{ fen, lastMove: null, san: null, sound: null }],
    step: 0,
  };
}

/** Play `uci` from the current step (dropping anything after it), or null if it isn't legal. */
export function analysisMove(
  state: AnalysisState,
  uci: string,
): AnalysisState | null {
  const chess = new Chess(state.positions[state.step].fen);
  try {
    const m = chess.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: uci.length > 4 ? uci[4] : undefined,
    });
    const next: AnswerPosition = {
      fen: chess.fen(),
      lastMove: [m.from, m.to],
      san: m.san,
      sound: null,
    };
    return {
      positions: [...state.positions.slice(0, state.step + 1), next],
      step: state.step + 1,
    };
  } catch {
    return null;
  }
}

/** The moves played on this board, as UCI. */
export function analysisUcis(state: AnalysisState): string[] {
  return state.positions.slice(1).map((p) => uciOf(p.lastMove, p.san) ?? "");
}

/** Open in Analysis tab (FR-14.6): this board's moves, with the moves that led to where it was opened in front of them
 * (the game or the puzzle from its start, Adam, v0.15 planning). `history` lists the lines that may lead there, best
 * first; each is checked by replaying it, and the board alone is sent when none reaches its first position. */
export function lineForAnalysisTab(
  state: AnalysisState,
  history: { start: string; ucis: string[] }[],
  orientation: "white" | "black",
): AnalysisLine {
  const from = state.positions[0].fen;
  const played = analysisUcis(state);
  for (const h of history) {
    const before = prefixTo(h.start, h.ucis, from);
    if (before) return { startFen: h.start, ucis: [...before, ...played], cursor: before.length + state.step, orientation };
  }
  return { startFen: from, ucis: played, cursor: state.step, orientation };
}

// FR-7.7: move pieces for either side after the puzzle; the engine panel follows the position.
// Nothing here is scored.
export function AnalysisControls({
  state,
  onStep,
  onReset,
  onClose,
  closeLabel = "Close",
  onOpenInTab,
}: {
  state: AnalysisState;
  onStep: (step: number) => void;
  onReset: () => void;
  onClose: () => void;
  /** "Back to the answer" when there's an answer to go back to (FR-5.4). */
  closeLabel?: string;
  /** v0.15 (FR-14.6): open this position, and the moves that led to it, in the Analysis tab. */
  onOpenInTab?: () => void;
}) {
  const last = state.positions.length - 1;
  const moves = state.positions
    .slice(1, state.step + 1)
    .map((p) => p.san)
    .join(" ");
  return (
    <Stack gap={6} data-testid="analysis-controls">
      <Text size="sm" fw={600}>
        Analysis board: move either side. Nothing here is scored.
      </Text>
      <Text size="xs" c="dimmed" data-testid="analysis-moves">
        {moves || "Make a move on the board."}
      </Text>
      <Group gap="xs" wrap="wrap">
        <Button
          size="xs"
          variant="default"
          disabled={state.step <= 0}
          onClick={() => onStep(state.step - 1)}
          aria-label="Back"
        >
          ◀ Back
        </Button>
        <Button
          size="xs"
          variant="default"
          disabled={state.step >= last}
          onClick={() => onStep(state.step + 1)}
          aria-label="Forward"
        >
          Forward ▶
        </Button>
        <Button
          size="xs"
          variant="default"
          onClick={onReset}
          data-testid="analysis-reset"
        >
          Reset
        </Button>
        <Button
          size="xs"
          variant="light"
          color="gray"
          onClick={onClose}
          data-testid="analysis-close"
        >
          {closeLabel}
        </Button>
        {onOpenInTab && (
          <Button size="xs" variant="light" onClick={onOpenInTab} data-testid="analysis-open-tab">
            Open in Analysis tab
          </Button>
        )}
      </Group>
    </Stack>
  );
}
