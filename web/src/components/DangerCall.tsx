import { Button, Group, Paper, Stack, Text } from "@mantine/core";
import type { DangerReveal } from "../api/types";
import { Chess } from "chess.js";

// Danger spotting (FR-4.4): call the highlighted move Safe or Unsafe, then the truth after the end.

/** The moves' SAN from `fen`, without move numbers ("Nf3", "Bg4"); a move that isn't legal stops the list. */
export function sanLine(fen: string, ucis: string[]): string[] {
  const out: string[] = [];
  try {
    const c = new Chess(fen);
    for (const uci of ucis) out.push(c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san);
  } catch {
    // stop at the first move that doesn't fit
  }
  return out;
}

export function DangerCall({ san, busy, onCall }: { san: string; busy: boolean; onCall: (call: "safe" | "unsafe") => void }) {
  return (
    <Paper withBorder p="sm" radius="md" data-testid="danger-call">
      <Stack gap={8}>
        <Text size="sm">
          Is <b>{san}</b> safe to play here?
        </Text>
        <Group gap="xs" grow>
          <Button color="green" variant="light" disabled={busy} onClick={() => onCall("safe")} data-testid="danger-safe">
            Safe (S)
          </Button>
          <Button color="red" variant="light" disabled={busy} onClick={() => onCall("unsafe")} data-testid="danger-unsafe">
            Unsafe (U)
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          About half the highlighted moves are safe. If you say Unsafe and it is, you then play the punishing reply.
        </Text>
      </Stack>
    </Paper>
  );
}

/** After the end: was the candidate safe, and why. `fen` is the position the candidate was played in. */
export function DangerVerdict({ fen, reveal }: { fen: string; reveal: DangerReveal }) {
  const [san = reveal.candidate, reply] = sanLine(fen, [reveal.candidate, ...reveal.line.slice(0, 1)]);
  if (reveal.is_safe) {
    return (
      <Text size="sm" data-testid="danger-verdict">
        <b>{san}</b> was safe.
        {reveal.candidate_score && reveal.best_score
          ? ` Stockfish rates it ${reveal.candidate_score} (its best line: ${reveal.best_score}).`
          : ""}
      </Text>
    );
  }
  return (
    <Text size="sm" data-testid="danger-verdict">
      <b>{san}</b> was the blunder from the game{reply ? `: ${reply} punishes it` : ""}. Show answer steps through the
      whole line.
    </Text>
  );
}
