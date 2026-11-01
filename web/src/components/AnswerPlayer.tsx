import { Button, Group, Text } from "@mantine/core";
import { Chess } from "chess.js";
import type { MoveSound } from "../sound/player";

export interface AnswerPosition {
  fen: string;
  lastMove: [string, string] | null;
  san: string | null; // the move that led here
  sound: MoveSound | null; // …and its sound (FR-1.13)
}

/** Every position of an answer line: the start, then one per move. */
export function answerPositions(fen: string, moves: string[], sounds: MoveSound[] = []): AnswerPosition[] {
  const chess = new Chess(fen);
  const out: AnswerPosition[] = [{ fen, lastMove: null, san: null, sound: null }];
  moves.forEach((uci, i) => {
    const m = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined });
    out.push({ fen: chess.fen(), lastMove: [uci.slice(0, 2), uci.slice(2, 4)], san: m.san, sound: sounds[i] ?? null });
  });
  return out;
}

// Show answer (§7.2): the solution step by step with Back / Forward. The board itself is drawn by
// the trainer from `step`; this is only the controls and where you are in the line.
export function AnswerPlayer({
  positions,
  step,
  onStep,
}: {
  positions: AnswerPosition[];
  step: number;
  onStep: (step: number) => void;
}) {
  const last = positions.length - 1;
  return (
    <Group gap="xs" data-testid="answer-player" wrap="nowrap">
      <Button size="xs" variant="default" disabled={step <= 0} onClick={() => onStep(step - 1)} aria-label="Back">
        ◀ Back
      </Button>
      <Text size="sm" data-testid="answer-step" style={{ whiteSpace: "nowrap" }}>
        {step === 0 ? "Start" : `${step}/${last}: ${positions[step].san}`}
      </Text>
      <Button size="xs" variant="default" disabled={step >= last} onClick={() => onStep(step + 1)} aria-label="Forward">
        Forward ▶
      </Button>
    </Group>
  );
}
