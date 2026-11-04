// v0.8 Game Review (FR-11.8–11.16): the board and move list with ?! ? ?? symbols, the eval graph, the
// summary per side, key moments with mistake reasons and Save as puzzle, the engine's lines and the
// refutation at any move (all from the stored analysis), and Retry mode on your mistakes.
import { Alert, Badge, Button, Grid, Group, Paper, Progress, Radio, Stack, Table, Text, Title } from "@mantine/core";
import { Chess } from "chess.js";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ReasonKey } from "../api/ApiClient";
import type { GameReview, RetryResult, ReviewMove } from "../api/types";
import { answerPositions, AnswerPlayer } from "../components/AnswerPlayer";
import { Board, type BoardShape } from "../components/Board";
import { EvalGraph } from "../components/EvalGraph";
import { ReasonChips } from "../components/ReasonChips";
import { CLASS_COLOR, PLATFORM_LABEL, cap, gameDate, gamePrompt, moveLabel, resultLabel } from "../state/games";
import { useShortcuts } from "../state/shortcuts";
import { useJob } from "../state/useJob";

const sq = (uci: string): [string, string] => [uci.slice(0, 2), uci.slice(2, 4)];

function finalFen(start: string, moves: ReviewMove[]): string {
  const c = new Chess(start);
  for (const m of moves) c.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
  return c.fen();
}

export function ReviewView({ gameId, onBack, coordinates }: { gameId: number; onBack: () => void; coordinates: boolean }) {
  const [review, setReview] = useState<GameReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0); // moves played on the board
  const [showing, setShowing] = useState<{ fen: string; line: string[]; step: number } | null>(null);
  const [job, setJob] = useState<string | null>(null);
  const analysis = useJob(job);
  const [color, setColor] = useState<"white" | "black" | "both">("white");
  const [retry, setRetry] = useState<number | null>(null); // index into retry_plies
  const [result, setResult] = useState<RetryResult | null>(null);
  const [shownAt, setShownAt] = useState(0);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(() => {
    api.getReview(gameId).then(setReview, (e: Error) => setError(e.message));
  }, [gameId]);
  useEffect(load, [load]);
  useEffect(() => {
    if (analysis && analysis.state !== "running") load();
  }, [analysis, load]);

  const moves = useMemo(() => review?.moves ?? [], [review]);
  const end = useMemo(() => (review ? finalFen(review.start_fen, moves) : ""), [review, moves]);
  const n = moves.length;
  const go = (c: number) => {
    setShowing(null);
    setCursor(Math.max(0, Math.min(n, c)));
  };
  const retrying = retry !== null && review !== null;
  useShortcuts(
    {
      ArrowLeft: () => (showing ? setShowing({ ...showing, step: Math.max(0, showing.step - 1) }) : go(cursor - 1)),
      ArrowRight: () =>
        showing ? setShowing({ ...showing, step: Math.min(showing.line.length, showing.step + 1) }) : go(cursor + 1),
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
      setNote("");
      setShownAt(Date.now());
      setRetry(i);
    };
    const shapes: BoardShape[] = result ? result.best_line.slice(0, 1).map((u) => ({ orig: u.slice(0, 2), dest: u.slice(2, 4), color: "green" })) : [];
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
            <Board fen={m.fen_before} orientation={m.mover} movable={result || busy ? null : m.mover} onMove={tryMove} coordinates={coordinates} shapes={shapes} maxWidth={560} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Stack>
              <Text size="sm">
                In the game you played <b>{moveLabel(ply)} {m.san}</b>
                {m.symbol}. Find a better move: anything within the tolerance of the best counts.
              </Text>
              {result && (
                <Alert color={result.found ? "green" : "red"} data-testid="retry-result">
                  <Text size="sm" fw={600}>
                    {result.found ? `Found: ${result.played_san} (${result.played_score})` : `Not quite: ${result.played_san} (${result.played_score})`}
                  </Text>
                  <Text size="sm">
                    Best was {result.best_san ?? "?"}
                    {result.best_line.length > 1 ? `, then ${answerPositions(m.fen_before, result.best_line).slice(2).map((p) => p.san).join(" ")}` : ""}.
                  </Text>
                  {!result.engine_checked && <Text size="xs">Install Stockfish to have other moves checked.</Text>}
                </Alert>
              )}
              {result && !result.found && review.ask_reasons && (
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
  const fen = showing ? answerPositions(showing.fen, showing.line)[showing.step].fen : cursor < n ? moves[cursor].fen_before : end;
  const here = cursor < n ? moves[cursor] : null; // the next move: its position's engine lines
  const last = cursor > 0 ? moves[cursor - 1] : null; // the move just played
  const yours = (m: ReviewMove) => g.user_color === "both" || g.user_color === m.mover;
  const isError = (m: ReviewMove | null) => !!m && !!m.classification && m.classification in CLASS_COLOR;
  const shapes: BoardShape[] = [];
  if (!showing && here?.best_move) shapes.push({ orig: here.best_move.slice(0, 2), dest: here.best_move.slice(2, 4), color: "green" });
  const lastMove = showing
    ? answerPositions(showing.fen, showing.line)[showing.step].lastMove
    : last
      ? sq(last.uci)
      : null;

  return (
    <Stack gap="md" data-testid="review-view">
      <Group justify="space-between">
        <Group gap="sm">
          <Button variant="default" onClick={onBack} data-testid="review-back">
            ← My games
          </Button>
          <Title order={4}>
            {g.white ?? "?"} – {g.black ?? "?"}
          </Title>
          <Text size="sm" c="dimmed">
            {PLATFORM_LABEL[g.source]} · {gameDate(g.played_at)} · {resultLabel(g)}
          </Text>
        </Group>
        <Group gap="xs">
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
          <Group>
            <Text size="sm">Which side did you play?</Text>
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
            <Board fen={fen} orientation={orientation} movable={null} lastMove={lastMove} coordinates={coordinates} shapes={shapes} maxWidth={560} />
            {showing ? (
              <Stack gap={4}>
                <AnswerPlayer positions={answerPositions(showing.fen, showing.line)} step={showing.step} onStep={(s) => setShowing({ ...showing, step: s })} />
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
                {isError(last) && last.best_san && (
                  <Text size="sm">
                    Better was {last.best_san}
                    {last.cp_loss ? ` (it cost about ${(last.cp_loss / 100).toFixed(1)})` : ""}.
                  </Text>
                )}
                {isError(last) && last.refutation.length > 0 && (
                  <Button size="compact-xs" variant="light" mt={4} onClick={() => setShowing({ fen: cursor < n ? moves[cursor].fen_before : end, line: last.refutation, step: 0 })} data-testid="review-refutation">
                    Why {last.san} fails: show me
                  </Button>
                )}
              </Paper>
            )}
            {review.analyzed && !showing && here && here.lines.length > 0 && (
              <Paper withBorder p="sm" data-testid="review-lines">
                <Text size="xs" c="dimmed" mb={4}>
                  Engine lines here ({here.mover} to move)
                </Text>
                {here.lines.map((l, i) => (
                  <Group key={i} gap={6} wrap="nowrap">
                    <Text size="sm" w={56} fw={600}>
                      {l.score}
                    </Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => setShowing({ fen: here.fen_before, line: l.pv, step: 1 })}>
                      {l.sans.join(" ")}
                    </Button>
                  </Group>
                ))}
              </Paper>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Stack gap="md">
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
                          {m.symbol}, better was {m.best_san ?? "?"}
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
                  </Button>
                ))}
              </Group>
            </Paper>
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
