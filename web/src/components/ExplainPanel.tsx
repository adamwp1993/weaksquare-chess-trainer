import { Alert, Badge, Button, Group, Paper, Stack, Text, Tooltip } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ApiCallError } from "../api/ApiClient";
import type { ExplainQuote, Explanation } from "../api/types";
import { dollars, useLlmSettings } from "../state/llm";
import { useJob } from "../state/useJob";
import { answerPositions, type AnswerPosition } from "./AnswerPlayer";
import type { BoardShape } from "./Board";

export interface ExplainShowMe {
  positions: AnswerPosition[];
  shapes: BoardShape[][]; // per position: the annotations for the move played from it
  notes: string[]; // per position: what the explanation says about that move
}

/** Show me (FR-8.5): the solution from its start, each step's arrows and circles drawn before its move. */
export function showMeFor(x: Explanation): ExplainShowMe {
  const positions = answerPositions(x.start_fen, x.solution);
  const byPly = new Map(x.steps.map((s) => [s.ply, s]));
  const shapes = positions.map((_, i) => (byPly.get(i)?.annotations ?? []).map((a) => ({ orig: a.orig, dest: a.dest, color: a.color })));
  const notes = positions.map((_, i) => byPly.get(i)?.text ?? (i === positions.length - 1 ? x.summary : ""));
  return { positions, shapes, notes };
}

// Explain, step 3 of the stuck ladder (§7.2, FR-8.1–8.8). Shown only when an AI provider has a key, and
// usable once the puzzle is over (FR-7.3) with Stockfish installed. The button shows about what it costs,
// or "(saved)" for a cached result, which is free. Every word from the AI is rendered as plain text
// (React escapes it), never as HTML (FR-8.7).
export function ExplainPanel({
  sessionId,
  over,
  engineReady,
  onShowMe,
}: {
  sessionId: number;
  /** The puzzle is over: the line is complete or Show answer was used. */
  over: boolean;
  engineReady: boolean;
  onShowMe: (show: ExplainShowMe) => void;
}) {
  const settings = useLlmSettings();
  const [quote, setQuote] = useState<ExplainQuote | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const job = useJob(jobId);
  const configured = settings?.spend.configured ?? false;

  const refreshQuote = useCallback(() => {
    if (!over || !engineReady) return;
    api.getExplainQuote(sessionId).then(
      (q) => {
        setQuote(q);
        setQuoteError(null);
      },
      (e: Error) => setQuoteError(e instanceof ApiCallError && e.code === "engine_not_installed" ? "Explain needs Stockfish." : e.message),
    );
  }, [sessionId, over, engineReady]);

  // Re-quote when the puzzle ends and whenever the settings change (model, budget, cap, spend).
  useEffect(() => refreshQuote(), [refreshQuote, settings]);

  // The latest Show me handler, kept in a ref (updated after render) so a finished job shows once.
  const showMeRef = useRef(onShowMe);
  useEffect(() => {
    showMeRef.current = onShowMe;
  }, [onShowMe]);

  // A finished job: fetch the explanation and put it on the board (Show me).
  const doneJob = job?.state === "done" ? job.id : null;
  useEffect(() => {
    if (!doneJob) return;
    let alive = true;
    api.getExplanation(sessionId).then((x) => {
      if (!alive) return;
      setExplanation(x);
      if (x) showMeRef.current(showMeFor(x));
    }, () => undefined);
    return () => {
      alive = false;
    };
  }, [doneJob, sessionId]);

  if (!configured) return null;

  const running = jobId !== null && (job === null || job.state === "running");
  const jobError = job?.state === "failed" || job?.state === "cancelled" ? job.message : null;
  const can = over && engineReady && !running && (quote?.state === "ok" || quote?.state === "cached");
  let label = "Explain";
  if (running) label = "Explaining…";
  else if (quote?.state === "cached") label = "Explain (saved)";
  else if (quote?.state === "ok" && quote.typical_usd !== null) label = `Explain (≈ ${dollars(quote.typical_usd)})`;
  const why = !over
    ? "Explain unlocks once the puzzle is over."
    : !engineReady
      ? "Explain needs Stockfish. Install it from the engine panel or Settings → Engine."
      : (quoteError ?? (quote && quote.state !== "ok" && quote.state !== "cached" ? quote.message : null));

  const start = async () => {
    setError(null);
    setJobId(null);
    try {
      setJobId(await api.startExplain(sessionId));
    } catch (e) {
      setError((e as Error).message);
      refreshQuote();
    }
  };

  return (
    <Stack gap={6} data-testid="explain">
      <Tooltip label={why ?? ""} disabled={!why} multiline w={260}>
        <div>
          <Button fullWidth variant="light" color="indigo" disabled={!can} onClick={start} data-testid="explain-button">
            {label}
          </Button>
        </div>
      </Tooltip>
      {why && over && (
        <Text size="xs" c="dimmed" data-testid="explain-why">
          {why}
        </Text>
      )}
      {running && job && (
        <Text size="xs" c="dimmed" data-testid="explain-progress">
          {job.message}
        </Text>
      )}
      {(error ?? jobError) && (
        <Alert color="red" withCloseButton onClose={() => { setError(null); setJobId(null); }} data-testid="explain-error">
          {error ?? jobError}
        </Alert>
      )}
      {explanation && <ExplanationView x={explanation} onShowMe={() => onShowMe(showMeFor(explanation))} />}
    </Stack>
  );
}

function ExplanationView({ x, onShowMe }: { x: Explanation; onShowMe: () => void }) {
  return (
    <Paper withBorder p="sm" radius="md" data-testid="explanation">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap">
          <Text fw={600} size="sm">
            Explanation
          </Text>
          <Button size="compact-xs" variant="subtle" onClick={onShowMe} data-testid="explain-show-me">
            Show me
          </Button>
        </Group>
        <Text size="sm" data-testid="explanation-summary">
          {x.summary}
        </Text>
        {x.key_ideas.length > 0 && (
          <Group gap={4}>
            {x.key_ideas.map((k) => (
              <Badge key={k} variant="light" color="indigo" style={{ textTransform: "none" }}>
                {k}
              </Badge>
            ))}
          </Group>
        )}
        <Stack gap={4} data-testid="explanation-steps">
          {x.steps.map((s) => (
            <Text size="xs" key={s.ply}>
              <b>
                {s.side === "you" ? "You" : "Opponent"}: {s.san}
              </b>{" "}
              {s.text}
              {s.variation.length > 0 && <i> (for example {s.variation.join(" ")})</i>}
            </Text>
          ))}
        </Stack>
        {x.discarded > 0 && (
          <Text size="xs" c="orange" data-testid="explanation-discarded">
            Some annotations were discarded because they didn't fit the position.
          </Text>
        )}
        <Text size="xs" c="dimmed" data-testid="explanation-cost">
          {x.model} · {x.cached ? "saved, free" : dollars(x.cost_usd)}
        </Text>
      </Stack>
    </Paper>
  );
}
