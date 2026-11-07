// v0.8 Game Review (FR-11.8–11.16): the board and move list with ?! ? ?? symbols, the eval graph, the
// summary per side, key moments with mistake reasons and Save as puzzle, the engine's lines and the
// refutation at any move (all from the stored analysis), and Retry mode on your mistakes.
// v0.9 (§11.4): Explain this move on your moves, Explain my game with its Confirm dialog and the Game Review
// model dropdown, the AI's notes on the key moments, and Train these.
// v0.10: Show best moves (FR-11.35), off by default and remembered, hides everything that gives the better
// move away; Analyze from here (FR-11.34) opens a free board on the interactive engine.
import { Alert, Badge, Button, Grid, Group, Paper, Progress, Radio, Stack, Switch, Table, Text, Title } from "@mantine/core";
import { Chess } from "chess.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ReasonKey } from "../api/ApiClient";
import type { EngineStatus, Explanation, GameMoment, GameNarrative, GameReview, JournalEntry, RetryResult, ReviewMove, SuggestedPreset } from "../api/types";
import { AnalysisControls, analysisMove, openAnalysis, type AnalysisState } from "../components/AnalysisBoard";
import { EnginePanel } from "../components/EnginePanel";
import { legalArrow } from "../state/engine";
import { answerPositions, AnswerPlayer } from "../components/AnswerPlayer";
import { Board, type BoardShape } from "../components/Board";
import { EvalGraph } from "../components/EvalGraph";
import { showMeFor } from "../components/ExplainPanel";
import { GameNarrativePanel, MomentNote, MoveExplain } from "../components/GameAiPanel";
import { GameNotes } from "../components/GameNotes";
import { ReasonChips } from "../components/ReasonChips";
import { CLASS_COLOR, PLATFORM_LABEL, cap, gameDate, gamePrompt, moveLabel, resultLabel } from "../state/games";
import { useShortcuts } from "../state/shortcuts";
import { useJob } from "../state/useJob";
import { Labeled, OptionInfo } from "../components/OptionInfo";

const sq = (uci: string): [string, string] => [uci.slice(0, 2), uci.slice(2, 4)];

function finalFen(start: string, moves: ReviewMove[]): string {
  const c = new Chess(start);
  for (const m of moves) c.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
  return c.fen();
}

/** A line stepped through on the board; Show me adds each step's arrows and the AI's note (FR-8.5). */
interface Showing {
  fen: string;
  line: string[];
  step: number;
  shapes?: BoardShape[][];
  notes?: string[];
}

export function ReviewView({
  gameId,
  onBack,
  backLabel = "← My games",
  initialPly,
  coordinates,
  autoExplain = false,
  onTrain,
  startRetry = false,
  hideBest = false,
}: {
  /** v0.12 (FR-10.63): a Retry task opens straight in Retry mode. */
  startRetry?: boolean;
  /** v0.12 (FR-10.62): a review task opens with best moves hidden, without changing your saved setting. */
  hideBest?: boolean;
  gameId: number;
  onBack: () => void;
  backLabel?: string;
  /** v0.10: open at this move's position (a Coach example, a puzzle's link back to its game). */
  initialPly?: number;
  coordinates: boolean;
  /** Review + Explain my game (FR-11.29): analyze if needed, then open Explain my game's Confirm. */
  autoExplain?: boolean;
  onTrain?: (p: SuggestedPreset) => void;
}) {
  const [review, setReview] = useState<GameReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(initialPly ?? 0); // moves played on the board
  const [showing, setShowing] = useState<Showing | null>(null);
  const [notes, setNotes] = useState<Map<number, GameMoment>>(new Map());
  const autoAnalyzed = useRef(false);
  const [job, setJob] = useState<string | null>(null);
  const analysis = useJob(job);
  const [color, setColor] = useState<"white" | "black" | "both">("white");
  const [retry, setRetry] = useState<number | null>(null); // index into retry_plies
  const [result, setResult] = useState<RetryResult | null>(null);
  const [retryShapes, setRetryShapes] = useState<BoardShape[] | null>(null); // Explain's "Show me" in Retry
  const [shownAt, setShownAt] = useState(0);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [showBest, setShowBest] = useState(false); // FR-11.35: off until you turn it on
  const [free, setFree] = useState<AnalysisState | null>(null); // Analyze from here (FR-11.34)
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [freeBest, setFreeBest] = useState<string | null>(null);

  const [gameNotes, setGameNotes] = useState<JournalEntry[]>([]); // v0.12 (FR-10.69)

  useEffect(() => {
    if (hideBest) return; // it stays off for this task, whatever your setting says
    api.getSettings().then((s) => setShowBest(s.show_best), () => undefined);
  }, [hideBest]);
  const toggleBest = (on: boolean) => {
    setShowBest(on);
    if (!hideBest) api.setSetting("review.show_best", on).catch((e: Error) => setError(e.message)); // FR-10.62
  };
  const loadNotes = useCallback(() => {
    api.getGameNotes(gameId).then(setGameNotes, () => undefined);
  }, [gameId]);
  useEffect(loadNotes, [loadNotes]);
  // FR-10.64, 10.68: the moves you look at are what a pass through the game is made of. `cursor` counts moves played.
  useEffect(() => {
    if (cursor >= 1) api.markReviewPly(gameId, cursor - 1).catch(() => undefined);
  }, [gameId, cursor]);
  const loadEngine = useCallback(() => {
    api.getEngineStatus().then(setEngine, () => undefined);
  }, []);
  const analyzeHere = useCallback(
    (f: string, purpose: "start" | "panel" | "board") => api.analyzeGamePosition(gameId, f, purpose === "board" ? "board" : "panel"),
    [gameId],
  );

  const load = useCallback(() => {
    api.getReview(gameId).then(setReview, (e: Error) => setError(e.message));
  }, [gameId]);
  useEffect(load, [load]);
  useEffect(() => {
    if (analysis && analysis.state !== "running") load();
  }, [analysis, load]);
  // Review + Explain my game on a game that isn't analyzed yet: analyze it first (FR-11.29).
  useEffect(() => {
    if (!autoExplain || !review || review.analyzed || autoAnalyzed.current || review.game.user_color === null) return;
    autoAnalyzed.current = true;
    api.analyzeGames([gameId], false).then(setJob, (e: Error) => setError(e.message));
  }, [autoExplain, review, gameId]);
  const narrativeChanged = useCallback((x: GameNarrative | null) => setNotes(new Map((x?.moments ?? []).map((m) => [m.ply, m]))), []);
  const showExplanation = useCallback((x: Explanation) => {
    const s = showMeFor(x);
    setShowing({ fen: x.start_fen, line: x.solution, step: 0, shapes: s.shapes, notes: s.notes });
  }, []);

  const moves = useMemo(() => review?.moves ?? [], [review]);
  const end = useMemo(() => (review ? finalFen(review.start_fen, moves) : ""), [review, moves]);
  const n = moves.length;
  const go = (c: number) => {
    setShowing(null);
    setCursor(Math.max(0, Math.min(n, c)));
  };
  // FR-10.63: a Retry task opens straight in Retry mode, once, when there's something to retry.
  const autoRetried = useRef(false);
  useEffect(() => {
    if (!startRetry || autoRetried.current || !review?.analyzed || review.retry_plies.length === 0) return;
    autoRetried.current = true;
    setRetry(0);
    setResult(null);
    setShownAt(Date.now());
  }, [startRetry, review]);
  const notedPlies = useMemo(() => new Set(gameNotes.map((x) => x.ply)), [gameNotes]);
  const retrying = retry !== null && review !== null;
  useShortcuts(
    {
      ArrowLeft: () =>
        free
          ? setFree({ ...free, step: Math.max(0, free.step - 1) })
          : showing
            ? setShowing({ ...showing, step: Math.max(0, showing.step - 1) })
            : go(cursor - 1),
      ArrowRight: () =>
        free
          ? setFree({ ...free, step: Math.min(free.positions.length - 1, free.step + 1) })
          : showing
            ? setShowing({ ...showing, step: Math.min(showing.line.length, showing.step + 1) })
            : go(cursor + 1),
    },
    !retrying,
  );

  if (error) return <Alert color="red">{error}</Alert>;
  if (!review) return <Text c="dimmed">Loading…</Text>;
  const g = review.game;
  const orientation = g.user_color === "black" ? "black" : "white";
  const analyze = async (force: boolean) => {
    setError(null);
    try {
      setJob(await api.analyzeGames([gameId], force));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // ---- Retry mode (FR-11.15) -----------------------------------------------------------------
  if (retrying) {
    const ply = review.retry_plies[retry];
    const m = moves[ply];
    const tryMove = async (uci: string) => {
      setBusy(true);
      try {
        setResult(await api.retryMove(gameId, ply, uci, Date.now() - shownAt));
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    };
    const goRetry = (i: number | null) => {
      setResult(null);
      setRetryShapes(null);
      setNote("");
      setShownAt(Date.now());
      setRetry(i);
    };
    const shapes: BoardShape[] = retryShapes ?? (result ? result.best_line.slice(0, 1).map((u) => ({ orig: u.slice(0, 2), dest: u.slice(2, 4), color: "green" })) : []);
    return (
      <Stack data-testid="retry-mode">
        <Group justify="space-between">
          <Title order={4}>
            Retry your mistakes · {retry + 1} of {review.retry_plies.length}
          </Title>
          <Button variant="default" onClick={() => goRetry(null)} data-testid="retry-exit">
            Back to the review
          </Button>
        </Group>
        <Grid>
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Board fen={m.fen_before} orientation={m.mover} movable={result || busy ? null : m.mover} onMove={tryMove} coordinates={coordinates} shapes={shapes} maxWidth={560} fitWindow />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Stack>
              <Text size="sm">
                In the game you played <b>{moveLabel(ply)} {m.san}</b>
                {m.symbol}. Find a better move: anything within the tolerance of the best counts.
              </Text>
              {result && (
                <Alert color={result.found ? "green" : result.engine_checked ? "red" : "yellow"} data-testid="retry-result">
                  <Text size="sm" fw={600}>
                    {result.found
                      ? `Found: ${result.played_san} (${result.played_score})`
                      : result.engine_checked
                        ? `Not quite: ${result.played_san} (${result.played_score})`
                        : `${result.played_san} couldn't be checked without Stockfish, so it isn't counted.`}
                  </Text>
                  <Text size="sm">
                    Best was {result.best_san ?? "?"}
                    {result.best_line.length > 1 ? `, then ${answerPositions(m.fen_before, result.best_line).slice(2).map((p) => p.san).join(" ")}` : ""}.
                  </Text>
                  {!result.engine_checked && <Text size="xs">Install Stockfish to have moves like this checked.</Text>}
                </Alert>
              )}
              {/* Adam, 2026-11-04 (v0.11 build): Explain this move in Retry, once you've tried, so it never helps
                  before your attempt (FR-11.15). Its "Show me" draws on this board. */}
              {result && <MoveExplain key={ply} gameId={gameId} ply={ply} onShowMe={(x) => setRetryShapes(showMeFor(x).shapes[0] ?? [])} />}
              {result && !result.found && result.engine_checked && review.ask_reasons && (
                <ReasonChips
                  prompt={gamePrompt(result.suggested_reason as ReasonKey | null)}
                  chosen={null}
                  busy={busy}
                  note={note}
                  onNote={setNote}
                  onChoose={(r) => api.setRetryReason(result.retry_id, r, note.trim() || null).then(() => goRetry(retry + 1 < review.retry_plies.length ? retry + 1 : null))}
                  onSkip={() => goRetry(retry + 1 < review.retry_plies.length ? retry + 1 : null)}
                />
              )}
              <Group>
                <Button variant="default" disabled={retry === 0} onClick={() => goRetry(retry - 1)}>
                  Previous
                </Button>
                <Button onClick={() => goRetry(retry + 1 < review.retry_plies.length ? retry + 1 : null)} data-testid="retry-next">
                  {retry + 1 < review.retry_plies.length ? "Next mistake" : "Done"}
                </Button>
              </Group>
            </Stack>
          </Grid.Col>
        </Grid>
      </Stack>
    );
  }

  // ---- the review ------------------------------------------------------------------------------
  const gameFen = cursor < n ? moves[cursor].fen_before : end;
  const fen = free ? free.positions[free.step].fen : showing ? answerPositions(showing.fen, showing.line)[showing.step].fen : gameFen;
  const here = cursor < n ? moves[cursor] : null; // the next move: its position's engine lines
  const last = cursor > 0 ? moves[cursor - 1] : null; // the move just played
  const yours = (m: ReviewMove) => g.user_color === "both" || g.user_color === m.mover;
  const isError = (m: ReviewMove | null) => !!m && !!m.classification && m.classification in CLASS_COLOR;
  const shapes: BoardShape[] = free ? [] : (showing?.shapes?.[showing.step] ?? []);
  if (!free && !showing && showBest && here?.best_move) shapes.push({ orig: here.best_move.slice(0, 2), dest: here.best_move.slice(2, 4), color: "green" });
  const freeArrow = free && showBest ? legalArrow(fen, freeBest ?? undefined) : null;
  if (freeArrow) shapes.push({ orig: freeArrow[0], dest: freeArrow[1], color: "green" });
  const lastMove = free
    ? free.positions[free.step].lastMove
    : showing
      ? answerPositions(showing.fen, showing.line)[showing.step].lastMove
      : last
        ? sq(last.uci)
        : null;

  return (
    <Stack gap="md" data-testid="review-view">
      <Group justify="space-between">
        <Group gap="sm">
          <Button variant="default" onClick={onBack} data-testid="review-back">
            {backLabel}
          </Button>
          <Title order={4}>
            {g.white ?? "?"} – {g.black ?? "?"}
          </Title>
          <Text size="sm" c="dimmed">
            {PLATFORM_LABEL[g.source]} · {gameDate(g.played_at)} · {resultLabel(g)}
          </Text>
        </Group>
        <Group gap="xs">
          {review.analyzed && (
            <Switch
              label={<Labeled id="review.showBest">Show best moves</Labeled>}
              checked={showBest}
              onChange={(e) => toggleBest(e.currentTarget.checked)}
              data-testid="review-show-best"
            />
          )}
          {review.analyzed && review.retry_plies.length > 0 && (
            <Button
              onClick={() => {
                setRetry(0);
                setResult(null);
                setShownAt(Date.now());
              }}
              data-testid="retry-start"
            >
              Retry your mistakes ({review.retry_plies.length})
            </Button>
          )}
          {g.url && (
            <Button variant="subtle" onClick={() => api.openGameOnline(g.id)}>
              {g.url.includes("chess.com") ? "Open on chess.com" : "Open on Lichess"}
            </Button>
          )}
        </Group>
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {g.user_color === null && (
        <Paper withBorder p="sm" data-testid="review-color">
          <Group data-option-group>
            <Text size="sm">
              Which side did you play?
              <OptionInfo id="review.side" />
            </Text>
            <Radio.Group value={color} onChange={(v) => setColor(v as typeof color)}>
              <Group>
                <Radio value="white" label="White" />
                <Radio value="black" label="Black" />
                <Radio value="both" label="Both sides" />
              </Group>
            </Radio.Group>
            <Button size="xs" onClick={() => api.setGameColor(g.id, color).then(load)}>
              Save
            </Button>
          </Group>
        </Paper>
      )}
      {!review.analyzed && (
        <Paper withBorder p="md" data-testid="review-not-analyzed">
          {analysis?.state === "running" ? (
            <Stack gap={6}>
              <Text size="sm">{analysis.message}</Text>
              <Progress value={(analysis.progress ?? 0) * 100} animated />
              <Group>
                <Button size="xs" variant="subtle" color="red" onClick={() => job && api.cancelJob(job)}>
                  Cancel
                </Button>
              </Group>
            </Stack>
          ) : (
            <Group justify="space-between">
              <Text size="sm">
                Stockfish hasn't analyzed this game yet. It grades every move on your PC, for free, in the background.
              </Text>
              <Button onClick={() => analyze(false)} data-testid="review-analyze">
                Analyze
              </Button>
            </Group>
          )}
          {analysis?.state === "failed" && <Alert color="red" mt="sm">{analysis.message}</Alert>}
        </Paper>
      )}
      {review.analyzed && !review.current && (
        <Alert color="blue" data-testid="review-stale">
          <Group justify="space-between">
            <Text size="sm">This analysis used other engine settings than today's.</Text>
            <Button size="xs" variant="default" onClick={() => analyze(true)}>
              Analyze again
            </Button>
          </Group>
        </Alert>
      )}

      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Stack gap="xs">
            <Board
              fen={fen}
              orientation={orientation}
              movable={free ? "both" : null}
              onMove={(uci) => {
                const next = free ? analysisMove(free, uci) : null;
                if (next) setFree(next);
              }}
              lastMove={lastMove}
              coordinates={coordinates}
              shapes={shapes}
              maxWidth={560}
              fitWindow
            />
            {free ? (
              <Stack gap="xs" data-testid="review-free">
                <AnalysisControls
                  state={free}
                  onStep={(s) => setFree({ ...free, step: s })}
                  onReset={() => setFree(openAnalysis(free.positions[0].fen))}
                  onClose={() => setFree(null)}
                  closeLabel="Back to the game"
                />
                {showBest ? (
                  <EnginePanel
                    analyze={analyzeHere}
                    startLabel="Game position:"
                    startFen={free.positions[0].fen}
                    fen={fen}
                    purpose="board"
                    status={engine}
                    onStatusChanged={loadEngine}
                    onBestMove={setFreeBest}
                  />
                ) : (
                  <Text size="xs" c="dimmed" data-testid="review-free-hidden">
                    Stockfish's eval and lines stay hidden while Show best moves is off.
                  </Text>
                )}
              </Stack>
            ) : showing ? (
              <Stack gap={4}>
                <AnswerPlayer positions={answerPositions(showing.fen, showing.line)} step={showing.step} onStep={(s) => setShowing({ ...showing, step: s })} />
                {showing.notes?.[showing.step] && (
                  <Text size="xs" data-testid="review-show-note">
                    {showing.notes[showing.step]}
                  </Text>
                )}
                <Button size="xs" variant="subtle" onClick={() => setShowing(null)}>
                  Back to the game
                </Button>
              </Stack>
            ) : (
              <Group gap={4} justify="center">
                <Button size="xs" variant="default" onClick={() => go(0)} aria-label="Start">|‹</Button>
                <Button size="xs" variant="default" onClick={() => go(cursor - 1)} aria-label="Back" data-testid="review-prev">‹</Button>
                <Text size="sm" w={110} ta="center" data-testid="review-move">
                  {last ? `${moveLabel(last.ply)} ${last.san}${last.symbol ?? ""}` : "Start"}
                </Text>
                <Button size="xs" variant="default" onClick={() => go(cursor + 1)} aria-label="Forward" data-testid="review-next">›</Button>
                <Button size="xs" variant="default" onClick={() => go(n)} aria-label="End">›|</Button>
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => {
                    loadEngine();
                    setShowing(null);
                    setFree(openAnalysis(gameFen));
                  }}
                  data-testid="review-analyze-here"
                >
                  Analyze from here
                </Button>
              </Group>
            )}
            {review.analyzed && last && (
              <Paper withBorder p="sm" data-testid="review-current">
                <Group gap="xs" mb={4}>
                  <Text size="sm" fw={600}>
                    {moveLabel(last.ply)} {last.san}
                    {last.symbol}
                  </Text>
                  {last.classification && (
                    <Badge size="sm" color={CLASS_COLOR[last.classification] ?? "gray"} variant="light">
                      {cap(last.classification)}
                    </Badge>
                  )}
                  {last.eval_text && <Text size="sm" c="dimmed">{last.eval_text}</Text>}
                </Group>
                {showBest && isError(last) && last.best_san && (
                  <Text size="sm" data-testid="review-better">
                    Better was {last.best_san}
                    {last.cp_loss ? ` (it cost about ${(last.cp_loss / 100).toFixed(1)})` : ""}.
                  </Text>
                )}
                {isError(last) && last.refutation.length > 0 && (
                  <Button size="compact-xs" variant="light" mt={4} onClick={() => setShowing({ fen: cursor < n ? moves[cursor].fen_before : end, line: last.refutation, step: 0 })} data-testid="review-refutation">
                    Why {last.san} fails: show me
                  </Button>
                )}
                {yours(last) && <MoveExplain key={last.ply} gameId={gameId} ply={last.ply} onShowMe={showBest ? showExplanation : undefined} />}
              </Paper>
            )}
            {review.analyzed && showBest && !showing && !free && here && here.lines.length > 0 && (
              <Paper withBorder p="sm" data-testid="review-lines">
                <Text size="xs" c="dimmed" mb={4}>
                  Engine lines here ({here.mover} to move)
                </Text>
                {here.lines.map((l, i) => (
                  <Group key={i} gap={6} wrap="wrap">
                    <Text size="sm" w={56} fw={600}>
                      {l.score}
                    </Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => setShowing({ fen: here.fen_before, line: l.pv, step: 1 })}>
                      {l.sans.slice(0, 8).join(" ")}
                      {l.sans.length > 8 ? " …" : ""}
                    </Button>
                  </Group>
                ))}
              </Paper>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Stack gap="md">
            {g.user_color !== null && (
              <GameNarrativePanel
                gameId={gameId}
                analyzed={review.analyzed}
                autoConfirm={autoExplain}
                onNarrative={narrativeChanged}
                onJump={(p) => go(p + 1)}
                onTrain={(p) => onTrain?.(p)}
              />
            )}
            {review.analyzed && <EvalGraph moves={moves} ply={cursor - 1} onPly={(p) => go(p + 1)} />}
            {review.analyzed && (
              <Table withTableBorder data-testid="review-summary">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th />
                    <Table.Th ta="right">?!</Table.Th>
                    <Table.Th ta="right">?</Table.Th>
                    <Table.Th ta="right">??</Table.Th>
                    <Table.Th ta="right">Avg. loss</Table.Th>
                    <Table.Th ta="right">Accuracy</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {review.summaries.map((s) => (
                    <Table.Tr key={s.color}>
                      <Table.Td>
                        {cap(s.color)}
                        {g.user_color === s.color ? " (you)" : ""}
                      </Table.Td>
                      <Table.Td ta="right">{s.inaccuracies}</Table.Td>
                      <Table.Td ta="right">{s.mistakes}</Table.Td>
                      <Table.Td ta="right">{s.blunders}</Table.Td>
                      <Table.Td ta="right">{s.avg_cp_loss !== null ? `${Math.round(s.avg_cp_loss)} cp` : "—"}</Table.Td>
                      <Table.Td ta="right">{s.platform_accuracy !== null ? `${Math.round(s.platform_accuracy)}%` : "—"}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
            {review.analyzed && review.summaries.some((s) => s.low_clock_errors) && (
              <Text size="xs" c="dimmed">
                Mistakes on a low clock:{" "}
                {review.summaries.map((s) => `${cap(s.color)} ${s.low_clock_errors ?? 0}`).join(" · ")}
              </Text>
            )}
            {review.analyzed && (
              <Stack gap="xs" data-testid="key-moments">
                <Title order={5}>Key moments</Title>
                {review.key_moments.length === 0 && <Text size="sm" c="dimmed">No mistakes of yours to show. Well played.</Text>}
                {review.key_moments.map((p) => {
                  const m = moves[p];
                  const open = cursor === p + 1;
                  return (
                    <Paper key={p} withBorder p="xs" data-testid={`moment-${p}`}>
                      <Group justify="space-between" wrap="nowrap">
                        <Button variant="subtle" size="compact-sm" onClick={() => go(p + 1)}>
                          {moveLabel(p)} Played {m.san}
                          {m.symbol}
                          {showBest ? `, better was ${m.best_san ?? "?"}` : ""}
                        </Button>
                        <Group gap={4} wrap="nowrap">
                          {m.reason && <Badge size="xs" variant="outline">{m.reason}</Badge>}
                          <Button
                            size="compact-xs"
                            variant="light"
                            disabled={m.saved}
                            onClick={() =>
                              api.saveGamePuzzle(gameId, p).then(
                                (r) => {
                                  setSaved(r.created ? "Saved to My puzzles." : "Already in My puzzles.");
                                  load();
                                },
                                (e: Error) => setError(e.message),
                              )
                            }
                            data-testid={`save-${p}`}
                          >
                            {m.saved ? "Saved" : "Save as puzzle"}
                          </Button>
                        </Group>
                      </Group>
                      {notes.has(p) && (
                        <MomentNote
                          m={notes.get(p)!}
                          onShow={!showBest ? undefined : () => {
                            const note = notes.get(p)!;
                            const arrows = note.annotations.map((a) => ({ orig: a.orig, dest: a.dest, color: a.color }));
                            setShowing({ fen: m.fen_before, line: note.better_uci, step: 0, shapes: [arrows], notes: [note.text] });
                          }}
                        />
                      )}
                      {open && review.ask_reasons && yours(m) && (
                        <ReasonChips
                          prompt={gamePrompt(m.suggested_reason as ReasonKey | null)}
                          chosen={m.reason as ReasonKey | null}
                          busy={busy}
                          note={note}
                          onNote={setNote}
                          onChoose={(r) => {
                            setBusy(true);
                            api.setGameReason(gameId, p, r, note.trim() || null).then(load, (e: Error) => setError(e.message)).finally(() => setBusy(false));
                          }}
                          onSkip={() => go(p + 2)}
                        />
                      )}
                    </Paper>
                  );
                })}
                {saved && <Text size="xs" c="dimmed" data-testid="saved-note">{saved}</Text>}
              </Stack>
            )}
            <Paper withBorder p="xs" data-testid="move-list">
              <Group gap={2}>
                {moves.map((m) => (
                  <Button
                    key={m.ply}
                    size="compact-xs"
                    variant={cursor === m.ply + 1 ? "filled" : "subtle"}
                    color={m.classification && CLASS_COLOR[m.classification] ? CLASS_COLOR[m.classification] : "gray"}
                    fw={yours(m) ? 700 : 400}
                    onClick={() => go(m.ply + 1)}
                    data-testid={`move-${m.ply}`}
                  >
                    {m.ply % 2 === 0 ? `${m.ply / 2 + 1}. ` : ""}
                    {m.san}
                    {m.symbol ?? ""}
                    {notedPlies.has(m.ply) ? <span data-testid={`move-note-${m.ply}`}> ✎</span> : null}
                  </Button>
                ))}
              </Group>
            </Paper>
            <GameNotes
              gameId={gameId}
              notes={gameNotes}
              ply={cursor >= 1 ? cursor - 1 : null}
              moveLabel={cursor >= 1 && moves[cursor - 1] ? `${moveLabel(cursor - 1)} ${moves[cursor - 1].san}` : null}
              onChanged={loadNotes}
              onGo={(ply) => go(ply + 1)}
            />
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
