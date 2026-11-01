import { Alert, Anchor, Badge, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { Chess } from "chess.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Outcome, PuzzleView, SessionStats } from "../api/types";
import { AnswerPlayer, answerPositions, type AnswerPosition } from "../components/AnswerPlayer";
import { Board } from "../components/Board";
import { SessionBar } from "../components/SessionBar";
import { useShortcuts } from "../state/shortcuts";

const OPPONENT_DELAY_MS = 500;
const REPLY_DELAY_MS = 300;

type Message = { color: "green" | "red" | "gray"; text: string } | null;

function uciMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}

// Standard mode (FR-4.1): the opponent's first move plays, you answer, replies play automatically.
// Themes stay hidden until the attempt is decided (FR-3.14). A wrong move is a loss (FR-5.3); you
// can keep going to finish the line, or move on. When stuck (§7.2): Hint circles the piece that
// moves next, then Show answer steps through the rest of the line. Before the end, either one is a
// loss (FR-5.2); after it, Show answer is free (FR-5.4) and replays the whole line.
export function TrainerView({
  sessionId,
  onNewSession,
  onHistoryChange,
  coordinates = true,
}: {
  sessionId: number;
  onNewSession: () => void;
  coordinates?: boolean;
  /** An attempt may have been recorded: the mixer's history filters need a fresh count. */
  onHistoryChange?: () => void;
}) {
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
  const [hintSquare, setHintSquare] = useState<string | null>(null);
  const [hinted, setHinted] = useState(false);
  const [answer, setAnswer] = useState<{ positions: AnswerPosition[]; step: number } | null>(null);
  const [helpBusy, setHelpBusy] = useState(false);
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
    onHistoryChange?.();
  }, [sessionId, onHistoryChange]);

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
    setHintSquare(null);
    setHinted(false);
    setAnswer(null);
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
      if (fb.kind !== "wrong" && fb.kind !== "illegal") setHintSquare(null);
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

  const requestHelp = async (kind: "hint" | "answer") => {
    if (helpBusy) return;
    setHelpBusy(true);
    try {
      const help = await api.requestHelp(sessionId, kind);
      if (help.outcome) {
        setOutcome(help.outcome);
        refreshStats();
      }
      const lost = help.outcome ? " This puzzle now counts as failed." : "";
      if (kind === "hint") {
        setHintSquare(help.hint_square);
        setHinted(true);
        setMessage({ color: "gray", text: `Hint: the circled piece moves next.${lost}` });
      } else if (help.answer_fen) {
        timers.current.forEach(clearTimeout);
        timers.current = [];
        setHintSquare(null);
        setMovable(null);
        setLineDone(true);
        setAnswer({ positions: answerPositions(help.answer_fen, help.answer_moves), step: 0 });
        setMessage({ color: "gray", text: `The answer: step through it with Back and Forward.${lost}` });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setHelpBusy(false);
    }
  };

  const decided = outcome !== null;
  const shown = answer ? answer.positions[answer.step] : null;
  const canHint = view !== null && movable !== null && !lineDone && !answer && !helpBusy;
  const canAnswer = view !== null && !answer && !helpBusy && (hinted || decided || lineDone) && (lineDone || movable !== null);
  const stepAnswer = (delta: number) => {
    if (!answer) return;
    const to = Math.min(Math.max(answer.step + delta, 0), answer.positions.length - 1);
    if (to !== answer.step) setAnswer({ ...answer, step: to });
  };
  const next = () => {
    if (complete) onNewSession();
    else if (view && !busy) load();
  };

  // Keyboard shortcuts (state/shortcuts.ts has the list). Each does nothing unless its button is enabled.
  useShortcuts({
    n: next,
    Enter: next,
    h: () => canHint && requestHelp("hint"),
    a: () => canAnswer && requestHelp("answer"),
    ArrowLeft: () => stepAnswer(-1),
    ArrowRight: () => stepAnswer(1),
  });

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
            <Board
              fen={shown ? shown.fen : fen}
              orientation={view.player_color}
              movable={shown ? null : movable}
              lastMove={shown ? shown.lastMove : lastMove}
              onMove={onMove}
              hintSquare={hintSquare}
              coordinates={coordinates}
            />
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
          {answer && (
            <AnswerPlayer
              positions={answer.positions}
              step={answer.step}
              onStep={(to) => setAnswer({ ...answer, step: to })}
            />
          )}
          <Group gap="xs" grow data-testid="help-controls">
            <Button variant="light" color="gray" disabled={!canHint} onClick={() => requestHelp("hint")} data-testid="hint-button">
              Hint
            </Button>
            <Button
              variant="light"
              color="gray"
              disabled={!canAnswer}
              onClick={() => requestHelp("answer")}
              title={hinted || decided || lineDone ? undefined : "Use Hint first"}
              data-testid="answer-button"
            >
              Show answer
            </Button>
          </Group>
          {!decided && !lineDone && (
            <Text size="xs" c="dimmed">
              Hint and Show answer count the puzzle as failed. Show answer unlocks after a Hint.
            </Text>
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
