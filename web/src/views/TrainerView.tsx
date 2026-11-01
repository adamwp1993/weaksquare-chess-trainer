import { Alert, Anchor, Badge, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { Chess } from "chess.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Outcome, PuzzleView, SessionStats } from "../api/types";
import { Board } from "../components/Board";
import { SessionBar } from "../components/SessionBar";

const OPPONENT_DELAY_MS = 500;
const REPLY_DELAY_MS = 300;

type Message = { color: "green" | "red" | "gray"; text: string } | null;

function uciMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}

// Standard mode (FR-4.1): the opponent's first move plays, you answer, replies play automatically.
// Themes stay hidden until the attempt is decided (FR-3.14). A wrong move is a loss (FR-5.3); you
// can keep going to finish the line, or move on.
export function TrainerView({ sessionId, onNewSession }: { sessionId: number; onNewSession: () => void }) {
  const [view, setView] = useState<PuzzleView | null>(null);
  const [complete, setComplete] = useState(false);
  const [fen, setFen] = useState<string | null>(null);
  const [lastMove, setLastMove] = useState<[string, string] | null>(null);
  const [movable, setMovable] = useState<"white" | "black" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [lineDone, setLineDone] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chess = useRef<Chess | null>(null);
  const timers = useRef<number[]>([]);
  // One next_puzzle call at a time: a quick second click on Next/Skip would otherwise record a
  // failure for a puzzle you never saw (v0.1-B1).
  const loading = useRef(false);
  const [busy, setBusy] = useState(false);

  const later = (fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms));
  };

  const refreshStats = useCallback(() => {
    api.getSessionStats(sessionId).then(setStats, () => undefined);
  }, [sessionId]);

  const load = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    setBusy(true);
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setOutcome(null);
    setLineDone(false);
    setMessage(null);
    setMovable(null);
    try {
      const next = await api.nextPuzzle(sessionId);
      refreshStats();
      setView(next);
      if (!next) {
        setComplete(true);
        return;
      }
      const c = new Chess(next.fen);
      setFen(next.fen);
      setLastMove(null);
      later(() => {
        const opp = next.opponent_move;
        c.move(uciMove(opp));
        chess.current = c;
        setFen(c.fen());
        setLastMove([opp.slice(0, 2), opp.slice(2, 4)]);
        setMovable(next.player_color);
        setMessage({ color: "gray", text: `Your turn: find the best move for ${next.player_color}.` });
      }, OPPONENT_DELAY_MS);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      loading.current = false;
      setBusy(false);
    }
  }, [sessionId, refreshStats]);

  useEffect(() => {
    // Load the session's first puzzle once, when the trainer opens.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, [load]);

  const onMove = async (uci: string) => {
    const before = chess.current;
    if (!before || !view) return;
    const after = new Chess(before.fen());
    try {
      after.move(uciMove(uci));
    } catch {
      setFen(before.fen());
      return;
    }
    setFen(after.fen());
    setLastMove([uci.slice(0, 2), uci.slice(2, 4)]);
    setMovable(null);
    try {
      const fb = await api.submitMove(sessionId, uci);
      if (fb.outcome) {
        setOutcome(fb.outcome);
        refreshStats();
      }
      if (fb.kind === "correct" && fb.reply) {
        chess.current = after;
        setMessage({ color: "green", text: "Correct. Keep going." });
        const reply = fb.reply;
        later(() => {
          after.move(uciMove(reply));
          setFen(after.fen());
          setLastMove([reply.slice(0, 2), reply.slice(2, 4)]);
          setMovable(view.player_color);
        }, REPLY_DELAY_MS);
      } else if (fb.kind === "solved") {
        chess.current = after;
        setLineDone(true);
        const won = fb.outcome?.win ?? outcome?.win ?? false;
        setMessage(won ? { color: "green", text: "Solved!" } : { color: "gray", text: "That's the full line." });
      } else {
        // Wrong (or illegal): take the move back. The attempt is already decided as a loss.
        setFen(before.fen());
        setLastMove(null);
        setMovable(view.player_color);
        if (fb.kind === "wrong") {
          setMessage({ color: "red", text: "Not the move. This puzzle counts as failed; keep trying or go to the next one." });
        }
      }
    } catch (e) {
      setFen(before.fen());
      setMovable(view.player_color);
      setError((e as Error).message);
    }
  };

  if (complete) {
    return (
      <Stack gap="md">
        <SessionBar stats={stats} />
        <Paper withBorder p="lg" radius="md" data-testid="session-complete">
          <Stack gap="sm">
            <Title order={3}>Session complete</Title>
            <Text>
              {stats?.solved ?? 0} solved, {stats?.failed ?? 0} failed
              {stats?.accuracy != null && ` (${Math.round(stats.accuracy * 100)}% accuracy)`}.
            </Text>
            <Group>
              <Button onClick={onNewSession}>New session</Button>
            </Group>
          </Stack>
        </Paper>
      </Stack>
    );
  }

  const decided = outcome !== null;

  return (
    <Stack gap="md">
      <SessionBar stats={stats} />
      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Group align="flex-start" gap="lg" wrap="nowrap">
        <div style={{ flex: "1 1 560px", minWidth: 320 }}>
          {fen && view && (
            <Board fen={fen} orientation={view.player_color} movable={movable} lastMove={lastMove} onMove={onMove} />
          )}
        </div>
        <Stack gap="sm" style={{ flex: "0 0 260px" }}>
          {view && (
            <Text size="sm" c="dimmed" data-testid="puzzle-header">
              Puzzle {view.number}
              {stats?.queue_size ? ` of ${stats.queue_size}` : ""} · rated {view.rating} · you play {view.player_color}
            </Text>
          )}
          {message && (
            <Text c={message.color === "gray" ? undefined : message.color} fw={500} data-testid="trainer-message">
              {message.text}
            </Text>
          )}
          {outcome && (
            <Paper withBorder p="sm" radius="md" data-testid="outcome">
              <Stack gap={6}>
                <Text fw={700} c={outcome.win ? "green" : "red"}>
                  {outcome.win ? "Solved" : "Failed"}
                </Text>
                <Text size="sm">Themes:</Text>
                <Group gap={4} data-testid="outcome-themes">
                  {outcome.themes.map((t) => (
                    <Badge key={t.key} variant="light" style={{ textTransform: "none" }}>
                      {t.name}
                    </Badge>
                  ))}
                </Group>
                <Anchor size="sm" href={outcome.puzzle_url} target="_blank" rel="noreferrer">
                  Open this puzzle on Lichess
                </Anchor>
              </Stack>
            </Paper>
          )}
          <Button
            onClick={load}
            variant={decided || lineDone ? "filled" : "default"}
            disabled={!view || busy}
            data-testid="next-button"
          >
            {decided || lineDone ? "Next puzzle" : "Skip (counts as failed)"}
          </Button>
        </Stack>
      </Group>
    </Stack>
  );
}
