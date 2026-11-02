import { Button, Group, Stack, Text } from "@mantine/core";
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

/** A labelled part of the answer: the refutation of your move, then the solution (§7.2 step 2). */
export interface AnswerSegment {
  label: string;
  from: number; // index of the segment's first position
}

function segmentEnd(segments: AnswerSegment[], segment: AnswerSegment | null, last: number) {
  if (!segment) return last;
  const next = segments.find((s) => s.from > segment.from);
  return next ? next.from - 1 : last;
}

// Show answer (§7.2): the solution step by step with Back / Forward. After a wrong move it starts with
// Stockfish's refutation of that move. The board itself is drawn by the trainer from `step`; this is
// only the controls, the part of the answer you're in, and where you are in it.
export function AnswerPlayer({
  positions,
  step,
  onStep,
  segments = [],
}: {
  positions: AnswerPosition[];
  step: number;
  onStep: (step: number) => void;
  segments?: AnswerSegment[];
}) {
  const last = positions.length - 1;
  const segment = [...segments].reverse().find((s) => step >= s.from) ?? null;
  const base = segment?.from ?? 0;
  const end = segmentEnd(segments, segment, last);
  return (
    <Stack gap={4}>
      {segment && (
        <Text size="sm" fw={600} data-testid="answer-segment">
          {segment.label}
        </Text>
      )}
      <Group gap="xs" data-testid="answer-player" wrap="nowrap">
        <Button size="xs" variant="default" disabled={step <= 0} onClick={() => onStep(step - 1)} aria-label="Back">
          ◀ Back
        </Button>
        <Text size="sm" data-testid="answer-step" style={{ whiteSpace: "nowrap" }}>
          {step === base ? "Start" : `${step - base}/${end - base}: ${positions[step].san}`}
        </Text>
        <Button size="xs" variant="default" disabled={step >= last} onClick={() => onStep(step + 1)} aria-label="Forward">
          Forward ▶
        </Button>
      </Group>
    </Stack>
  );
}
