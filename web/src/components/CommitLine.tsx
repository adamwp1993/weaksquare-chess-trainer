import { Badge, Button, Group, Paper, Stack, Text } from "@mantine/core";
import { Chess, type Move } from "chess.js";
import type { CommitFeedback } from "../api/types";
import type { MoveSound } from "../sound/player";

// Commit the line (FR-4.2): the entry controls while you enter the line, and the graded line after Submit.

/** The sound for a move you enter. Entered moves only reach the backend at Submit, so this mirrors
 * core/move_sounds.py's priority locally: checkmate > check > capture > castling > a move. */
export function entrySound(move: Move): MoveSound {
  if (move.san.endsWith("#")) return "checkmate";
  if (move.san.endsWith("+")) return "check";
  if (move.captured) return "capture";
  if (move.san.startsWith("O-O")) return "castle";
  return "move";
}

/** The position after the opponent's first move plus your entered line. */
export function entryBoard(startFen: string, entry: string[]): Chess {
  const c = new Chess(startFen);
  for (const uci of entry) c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined });
  return c;
}

export function CommitControls({
  entered,
  target,
  max,
  busy,
  onUndo,
  onClear,
  onSubmit,
}: {
  entered: number;
  /** Show move count: the solution's length (both sides); null while it's hidden. */
  target: number | null;
  max: number | null;
  busy: boolean;
  onUndo: () => void;
  onClear: () => void;
  onSubmit: () => void;
}) {
  const full = max !== null && entered >= max;
  return (
    <Paper withBorder p="sm" radius="md" data-testid="commit-controls">
      <Stack gap={6}>
        <Text size="sm" data-testid="commit-count">
          {target !== null
            ? `Find ${target} moves (both sides): ${entered} of ${target} entered.`
            : `${entered} ${entered === 1 ? "move" : "moves"} entered (both sides).`}
        </Text>
        {full && target === null && (
          <Text size="xs" c="dimmed">
            That's as long as a line can be.
          </Text>
        )}
        <Group gap="xs" grow>
          <Button size="xs" variant="default" disabled={entered === 0 || busy} onClick={onUndo} data-testid="commit-undo">
            Undo
          </Button>
          <Button size="xs" variant="default" disabled={entered === 0 || busy} onClick={onClear} data-testid="commit-clear">
            Clear
          </Button>
        </Group>
        <Button disabled={entered === 0 || busy} loading={busy} onClick={onSubmit} data-testid="commit-submit">
          Submit
        </Button>
      </Stack>
    </Paper>
  );
}

function toMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}

/** SAN for your moves on your own board, and for the solution's moves (on the solution's board). */
function gradedRows(startFen: string, result: CommitFeedback) {
  const mine = new Chess(startFen);
  const theirs = new Chess(startFen);
  const rows: { i: number; g: CommitFeedback["grades"][number]; playedSan: string | null; expectedSan: string }[] = [];
  result.grades.forEach((g, i) => {
    let playedSan: string | null = null;
    if (g.played) {
      try {
        playedSan = mine.move(toMove(g.played)).san;
      } catch {
        playedSan = g.played;
      }
    }
    let expectedSan = g.expected;
    try {
      expectedSan = theirs.move(toMove(g.expected)).san;
    } catch {
      // the solution's board can't go further (shouldn't happen): show the UCI
    }
    rows.push({ i, g, playedSan, expectedSan });
  });
  return rows;
}

/** Your submitted line, move by move, against the solution. */
export function CommitResult({ startFen, result }: { startFen: string; result: CommitFeedback }) {
  const rows = gradedRows(startFen, result);
  return (
    <Paper withBorder p="sm" radius="md" data-testid="commit-result">
      <Stack gap={4}>
        <Text size="sm" fw={600}>
          Your line
        </Text>
        {rows.map(({ i, g, playedSan, expectedSan }) => (
          <Group key={i} gap={6} wrap="nowrap" data-testid="commit-ply">
            <Text size="sm" w={18} c={g.correct ? "green" : "red"} aria-label={g.correct ? "right" : "wrong"}>
              {g.correct ? "✓" : "✗"}
            </Text>
            <Text size="sm" w={70} c="dimmed">
              {g.player ? "You" : "Reply"}
            </Text>
            <Text size="sm" fw={500} td={g.correct || !playedSan ? undefined : "line-through"}>
              {playedSan ?? "—"}
            </Text>
            {!g.correct && (
              <Text size="xs" c="dimmed">
                solution: {expectedSan}
              </Text>
            )}
          </Group>
        ))}
        {result.extra.length > 0 && (
          <Text size="xs" c="dimmed" data-testid="commit-extra">
            {result.extra.length} more {result.extra.length === 1 ? "move" : "moves"} after the end of the solution (ignored).
          </Text>
        )}
        <Group gap={6}>
          <Badge variant="light" color="blue" style={{ textTransform: "none" }} data-testid="commit-calculation">
            Replies predicted: {result.replies_correct} of {result.replies_total}
          </Badge>
        </Group>
      </Stack>
    </Paper>
  );
}
