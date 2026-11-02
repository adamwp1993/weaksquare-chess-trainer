import { Alert, Anchor, Badge, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { Chess } from "chess.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ApiCallError } from "../api/ApiClient";
import type { AttemptRating, Outcome, PuzzleView, SessionStats } from "../api/types";
import { AnalysisControls, analysisMove, openAnalysis, type AnalysisState } from "../components/AnalysisBoard";
import { AnswerPlayer, answerPositions, type AnswerPosition, type AnswerSegment } from "../components/AnswerPlayer";
import { Board } from "../components/Board";
import { EngineInstallBanner } from "../components/EngineInstallBanner";
import { AnalyzeButton, EnginePanel } from "../components/EnginePanel";
import { RatingChange } from "../components/LichessStatus";
import { SessionBar } from "../components/SessionBar";
import { sounds } from "../sound/player";
import { legalArrow, useEngineStatus } from "../state/engine";
import { useShortcuts } from "../state/shortcuts";

const OPPONENT_DELAY_MS = 500;
const REPLY_DELAY_MS = 300;
const RATING_POLL_MS = 2000; // while a solve shows "Syncing…" (pushed sync events normally win)

type Message = { color: "green" | "red" | "gray"; text: string } | null;

function uciMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}

// Standard mode (FR-4.1): the opponent's first move plays, you answer, replies play automatically.
// Themes stay hidden until the attempt is decided (FR-3.14). A wrong move is a loss (FR-5.3); you
// can keep going to finish the line, or move on. When stuck (§7.2): Hint circles the piece that
// moves next, then Show answer steps through the rest of the line. Before the end, either one is a
// loss (FR-5.2); after it, Show answer is free (FR-5.4) and replays the whole line.
// Stockfish (v0.4): after a wrong move, Show answer starts with the engine's refutation of it (§7.2).
// Once the puzzle is over, the engine panel and the analysis board appear (FR-7.2, 7.7); never before (FR-7.3).
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
  const [answer, setAnswer] = useState<{ positions: AnswerPosition[]; step: number; segments: AnswerSegment[] } | null>(null);
  const [refutation, setRefutation] = useState<"loading" | "missing" | { error: string } | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [bestMove, setBestMove] = useState<string | null>(null);
  const [engine, refreshEngine] = useEngineStatus();
  const [helpBusy, setHelpBusy] = useState(false);
  const [rating, setRating] = useState<AttemptRating | null>(null);
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

  const decide = useCallback(
    (o: Outcome) => {
      setOutcome(o);
      setRating(o.lichess);
      refreshStats();
    },
    [refreshStats],
  );

  // FR-6.11b: the change fills in when Lichess replies (pushed), or offline once the queue drains.
  const attemptId = outcome?.attempt_id ?? null;
  useEffect(() => {
    if (attemptId === null) return;
    const unsubscribe = api.onEvent((event) => {
      if (event.name !== "sync") return;
      const mine = event.payload.attempts.find((a) => a.attempt_id === attemptId);
      if (mine) {
        setRating(mine);
        api.getSessionStats(sessionId).then(setStats, () => undefined);
      }
    });
    return unsubscribe;
  }, [attemptId, sessionId]);
  const waitingForLichess = rating?.status === "syncing" || rating?.status === "offline";
  useEffect(() => {
    if (attemptId === null || !waitingForLichess) return;
    const timer = setInterval(() => {
      api.getAttemptRatings([attemptId]).then((r) => {
        if (r[0]) setRating(r[0]);
        if (r[0]?.status === "done") api.getSessionStats(sessionId).then(setStats, () => undefined);
      }, () => undefined);
    }, RATING_POLL_MS);
    return () => clearInterval(timer);
  }, [attemptId, waitingForLichess, sessionId]);

  const load = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    setBusy(true);
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setOutcome(null);
    setRating(null);
    setLineDone(false);
    setMessage(null);
    setMovable(null);
    setHintSquare(null);
    setHinted(false);
    setAnswer(null);
    setRefutation(null);
    setAnalysis(null);
    setBestMove(null);
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
        sounds.play(next.opponent_sound); // before you've clicked anything (FR-1.13)
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
      sounds.play(fb.move_sound);
      if (fb.outcome) {
        decide(fb.outcome);
        sounds.later(fb.outcome.win ? "solved" : "failed");
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
          sounds.play(fb.reply_sound);
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
        decide(help.outcome);
        sounds.play("failed");
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
        setAnalysis(null); // the answer replaces the analysis board
        const solution = answerPositions(help.answer_fen, help.answer_moves, help.answer_sounds);
        setAnswer({ positions: solution, step: 0, segments: [] });
        setMessage({ color: "gray", text: `The answer: step through it with Back and Forward.${lost}` });
        if (help.refute) loadRefutation(solution);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setHelpBusy(false);
    }
  };

  // §7.2 step 2: put Stockfish's answer to your wrong move in front of the solution once it arrives.
  const loadRefutation = (solution: AnswerPosition[]) => {
    setRefutation("loading");
    api.getRefutation(sessionId).then(
      (r) => {
        const refPositions = answerPositions(r.fen_before, [r.wrong_move, ...r.line]);
        const wrongSan = refPositions[1]?.san ?? r.wrong_move;
        const verdict = r.score ?? r.game_over ?? "";
        const segments: AnswerSegment[] = [
          { label: `Why ${wrongSan} fails${verdict ? `: ${verdict}` : ""}`, from: 0 },
          { label: "The solution", from: refPositions.length },
        ];
        setRefutation(null);
        setAnswer((a) =>
          a && a.positions === solution
            ? { positions: [...refPositions, ...solution], segments, step: a.step === 0 ? 0 : a.step + refPositions.length }
            : a,
        );
      },
      (e: Error) => {
        if (e instanceof ApiCallError && e.code === "engine_not_installed") {
          refreshEngine();
          setRefutation("missing");
        } else setRefutation({ error: e.message });
      },
    );
  };

  const decided = outcome !== null;
  const shown = answer ? answer.positions[answer.step] : null;
  const analysisPos = analysis ? analysis.positions[analysis.step] : null;
  const boardFen = analysisPos ? analysisPos.fen : shown ? shown.fen : fen;
  const startFen = view ? (() => { const c = new Chess(view.fen); c.move(uciMove(view.opponent_move)); return c.fen(); })() : null;
  const arrow = analysisPos ? legalArrow(analysisPos.fen, bestMove ?? undefined) : null;
  const canHint = view !== null && movable !== null && !lineDone && !answer && !helpBusy;
  const canAnswer = view !== null && !answer && !helpBusy && (hinted || decided || lineDone) && (lineDone || movable !== null);
  const stepAnalysis = (to: number) => {
    if (!analysis) return;
    setAnalysis({ ...analysis, step: Math.min(Math.max(to, 0), analysis.positions.length - 1) });
  };
  const onAnalysisMove = (uci: string) => {
    if (!analysis) return;
    const next = analysisMove(analysis, uci);
    setAnalysis(next ? next : { ...analysis }); // an illegal move snaps back
  };
  const stepAnswer = (delta: number) => {
    if (analysis) return stepAnalysis(analysis.step + delta);
    if (!answer) return;
    const to = Math.min(Math.max(answer.step + delta, 0), answer.positions.length - 1);
    if (to === answer.step) return;
    if (to > answer.step) sounds.play(answer.positions[to].sound);
    setAnswer({ ...answer, step: to });
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
              fen={boardFen ?? fen}
              orientation={view.player_color}
              movable={analysisPos ? "both" : shown ? null : movable}
              lastMove={analysisPos ? analysisPos.lastMove : shown ? shown.lastMove : lastMove}
              onMove={analysisPos ? onAnalysisMove : onMove}
              hintSquare={analysisPos ? null : hintSquare}
              coordinates={coordinates}
              arrows={arrow ? [arrow] : undefined}
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
          {view?.already_played && (
            <Badge color="gray" variant="light" style={{ textTransform: "none" }} data-testid="already-played">
              Already played on Lichess: rating unaffected
            </Badge>
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
                <RatingChange info={rating} />
                <Anchor size="sm" href={outcome.puzzle_url} target="_blank" rel="noreferrer">
                  Open this puzzle on Lichess
                </Anchor>
              </Stack>
            </Paper>
          )}
          {answer && !analysis && (
            <AnswerPlayer
              positions={answer.positions}
              step={answer.step}
              segments={answer.segments}
              onStep={(to) => stepAnswer(to - answer.step)}
            />
          )}
          {refutation === "loading" && (
            <Text size="sm" c="dimmed" data-testid="refutation-loading">
              Stockfish is checking your move…
            </Text>
          )}
          {refutation === "missing" && engine && <EngineInstallBanner status={engine} onChanged={refreshEngine} />}
          {refutation && typeof refutation === "object" && (
            <Text size="xs" c="red" data-testid="refutation-error">
              {refutation.error}
            </Text>
          )}
          {lineDone && view && startFen && boardFen && refutation !== "missing" && (
            <EnginePanel
              sessionId={sessionId}
              startFen={startFen}
              fen={boardFen}
              purpose={analysis ? "board" : "panel"}
              status={engine}
              onStatusChanged={refreshEngine}
              onBestMove={setBestMove}
            >
              {analysis ? (
                <AnalysisControls
                  state={analysis}
                  onStep={stepAnalysis}
                  onReset={() => setAnalysis(openAnalysis(startFen))}
                  onClose={() => setAnalysis(null)}
                />
              ) : (
                <AnalyzeButton onClick={() => setAnalysis(openAnalysis(boardFen))} />
              )}
            </EnginePanel>
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
