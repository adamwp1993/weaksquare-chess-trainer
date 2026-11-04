// Game Review AI (v0.9, §11.4): Explain this move and Explain my game. Both are built from the stored
// analysis, use Game Review's own model (FR-1.15) and the shared guardrails (§9.3). Every word from the
// AI is rendered as plain text (React escapes it), never as HTML (FR-8.7).
import { Alert, Badge, Button, Group, List, Modal, Paper, Select, Stack, Text } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Explanation, GameAiQuote, GameMoment, GameNarrative, SuggestedPreset } from "../api/types";
import { moveLabel } from "../state/games";
import { dollars, useLlmSettings } from "../state/llm";
import { useJob } from "../state/useJob";
import { ExplanationView } from "./ExplainPanel";
import { FeatureModelPicker } from "./FeatureModelPicker";

const BLOCKED = new Set(["not_configured", "no_model", "no_price", "over_budget", "over_cap"]);

function useGameReviewReady() {
  const settings = useLlmSettings();
  const f = settings?.features.find((x) => x.feature === "game_review");
  return { settings, configured: !!f && f.provider !== "none" && (settings?.providers.some((p) => p.key_stored) ?? false) };
}

/** The job's error, or null. */
function jobError(job: ReturnType<typeof useJob>): string | null {
  return job?.state === "failed" || job?.state === "cancelled" ? job.message : null;
}

// ---- Explain this move (FR-11.17) -------------------------------------------------------------------

export function MoveExplain({ gameId, ply, onShowMe }: { gameId: number; ply: number; onShowMe: (x: Explanation) => void }) {
  const { settings, configured } = useGameReviewReady();
  const [quote, setQuote] = useState<GameAiQuote | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [x, setX] = useState<Explanation | null>(null);
  const job = useJob(jobId);

  useEffect(() => {
    if (!configured) return;
    let alive = true;
    api.getGameMoveQuote(gameId, ply).then(
      (q) => {
        if (!alive) return;
        setQuote(q);
        setError(null);
      },
      (e: Error) => alive && setError(e.message),
    );
    api.getGameMoveExplanation(gameId, ply).then((r) => alive && setX(r), () => undefined);
    return () => {
      alive = false;
    };
  }, [gameId, ply, configured, settings]);

  const showMeRef = useRef(onShowMe);
  useEffect(() => {
    showMeRef.current = onShowMe;
  }, [onShowMe]);
  const doneJob = job?.state === "done" ? job.id : null;
  useEffect(() => {
    if (!doneJob) return;
    api.getGameMoveExplanation(gameId, ply).then((r) => {
      setX(r);
      if (r) showMeRef.current(r);
    }, () => undefined);
  }, [doneJob, gameId, ply]);

  if (!configured) return null;
  const running = jobId !== null && (job === null || job.state === "running");
  let label = "Explain this move";
  if (running) label = "Explaining…";
  else if (quote?.state === "cached") label = "Explain this move (saved)";
  else if (quote?.state === "ok" && quote.typical_usd !== null) label = `Explain this move (≈ ${dollars(quote.typical_usd)})`;
  const why = quote && BLOCKED.has(quote.state) ? quote.message : null;
  const start = async () => {
    setError(null);
    try {
      setJobId(await api.startGameMoveExplain(gameId, ply));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Stack gap={6} mt={6} data-testid="move-explain">
      {!x && (
        <Button size="xs" variant="light" color="indigo" disabled={running || !quote || !!why} onClick={start} data-testid="move-explain-button">
          {label}
        </Button>
      )}
      {why && <Text size="xs" c="dimmed" data-testid="move-explain-why">{why}</Text>}
      {running && job && <Text size="xs" c="dimmed">{job.message}</Text>}
      {(error ?? jobError(job)) && (
        <Alert color="red" withCloseButton onClose={() => { setError(null); setJobId(null); }} data-testid="move-explain-error">
          {error ?? jobError(job)}
        </Alert>
      )}
      {x && <ExplanationView x={x} onShowMe={() => onShowMe(x)} />}
    </Stack>
  );
}

// ---- Explain my game (FR-11.18) ----------------------------------------------------------------------

const N_OPTIONS = Array.from({ length: 10 }, (_, i) => ({ value: String(i + 1), label: `${i + 1} key moment${i ? "s" : ""}` }));

/** The Confirm dialog's numbers (FR-8.11): tokens, cost, the share of what's left of the budget, the cap. */
export function EstimateLines({ q }: { q: GameAiQuote }) {
  const left = Math.max(0, q.budget_usd - q.spent_usd);
  const share = left > 0 && q.typical_usd !== null ? Math.round((q.typical_usd / left) * 1000) / 10 : null;
  return (
    <Stack gap={4} data-testid="narrative-estimate">
      <Text size="sm">
        About {q.input_tokens?.toLocaleString("en-US")} input tokens and up to {q.max_output_tokens?.toLocaleString("en-US")} output
        tokens on {q.model}.
      </Text>
      <Text size="sm" fw={600}>
        About {dollars(q.typical_usd ?? 0)}, at most {dollars(q.worst_usd ?? 0)}
        {share !== null ? ` (${share}% of the ${dollars(left)} left in this month's budget)` : ""}.
      </Text>
      <Text size="xs" c="dimmed">
        It fits under your per-run cap of {dollars(q.run_cap_usd)}. It sends this game's moves (SAN only) and Stockfish's
        analysis of your key moments: no names, ratings, dates, links or clocks.
      </Text>
    </Stack>
  );
}

export function GameNarrativePanel({
  gameId,
  analyzed,
  autoConfirm,
  onNarrative,
  onJump,
  onTrain,
}: {
  gameId: number;
  analyzed: boolean;
  /** Review + Explain my game (FR-11.29): open the Confirm dialog as soon as the analysis is there. */
  autoConfirm: boolean;
  onNarrative: (n: GameNarrative | null) => void;
  onJump: (ply: number) => void;
  onTrain: (p: SuggestedPreset) => void;
}) {
  const { settings, configured } = useGameReviewReady();
  const [n, setN] = useState<number | null>(null); // null: the Key moments setting
  const [quote, setQuote] = useState<GameAiQuote | null>(null);
  const [narrative, setNarrative] = useState<GameNarrative | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [train, setTrain] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId);
  const autoDone = useRef(false);

  const publish = useCallback(
    (x: GameNarrative | null) => {
      setNarrative(x);
      onNarrative(x);
    },
    [onNarrative],
  );

  useEffect(() => {
    if (!configured || !analyzed) return;
    let alive = true;
    api.getGameNarrativeQuote(gameId, n).then(
      (q) => {
        if (!alive) return;
        setQuote(q);
        if (autoConfirm && !autoDone.current) {
          autoDone.current = true;
          setConfirm(true);
        }
      },
      (e: Error) => alive && setError(e.message),
    );
    api.getGameNarrative(gameId, n).then((x) => alive && publish(x), () => undefined);
    return () => {
      alive = false;
    };
  }, [gameId, n, configured, analyzed, settings, autoConfirm, publish]);

  const doneJob = job?.state === "done" ? job.id : null;
  useEffect(() => {
    if (doneJob) api.getGameNarrative(gameId, n).then(publish, () => undefined);
  }, [doneJob, gameId, n, publish]);

  if (!configured || !analyzed) return null;
  const running = jobId !== null && (job === null || job.state === "running");
  const why = quote && BLOCKED.has(quote.state) ? quote.message : null;
  let label = "Explain my game";
  if (running) label = "Explaining your game…";
  else if (quote?.state === "cached") label = "Explain my game (saved)";
  else if (quote?.state === "ok" && quote.typical_usd !== null) label = `Explain my game (≈ ${dollars(quote.typical_usd)})`;
  const run = async () => {
    setConfirm(false);
    setError(null);
    try {
      setJobId(await api.startGameNarrative(gameId, n));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const ask = () => (quote?.state === "cached" ? run() : setConfirm(true)); // a saved one is free: no Confirm

  return (
    <Paper withBorder p="sm" data-testid="narrative-panel">
      <Stack gap="xs">
        <Group gap="xs" align="flex-end">
          <Select
            size="xs"
            w={170}
            aria-label="Key moments to explain"
            data={N_OPTIONS}
            value={n === null ? null : String(n)}
            placeholder="Moments: default"
            onChange={(v) => setN(v ? Number(v) : null)}
            clearable
            data-testid="narrative-n"
          />
          <FeatureModelPicker compact onError={setError} />
          <Button size="xs" color="indigo" disabled={running || !quote || !!why} onClick={ask} data-testid="narrative-button">
            {label}
          </Button>
        </Group>
        {why && <Text size="xs" c="dimmed" data-testid="narrative-why">{why}</Text>}
        {running && job && <Text size="xs" c="dimmed" data-testid="narrative-progress">{job.message}</Text>}
        {(error ?? jobError(job)) && (
          <Alert color="red" withCloseButton onClose={() => { setError(null); setJobId(null); }} data-testid="narrative-error">
            {error ?? jobError(job)}
          </Alert>
        )}
        {narrative && <NarrativeView x={narrative} onJump={onJump} onTrain={() => setTrain(true)} />}
      </Stack>
      <Modal opened={confirm && !!quote && quote.state === "ok"} onClose={() => setConfirm(false)} title="Explain my game?" data-testid="narrative-confirm">
        {quote && (
          <Stack>
            <EstimateLines q={quote} />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setConfirm(false)} data-testid="narrative-cancel">
                Cancel
              </Button>
              <Button color="indigo" onClick={run} data-testid="narrative-confirm-button">
                Confirm
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
      <Modal opened={train && !!narrative?.preset} onClose={() => setTrain(false)} title="Train these?" data-testid="train-confirm">
        {narrative?.preset && (
          <Stack>
            <Text size="sm">
              This sets the Mixer's themes to <b>{narrative.preset.names.join(", ")}</b>
              {narrative.preset.rating_min !== null || narrative.preset.rating_max !== null
                ? ` and the rating range to ${narrative.preset.rating_min ?? "any"}–${narrative.preset.rating_max ?? "any"}`
                : ""}
              , replacing the themes and rating you have now. Themes apply only to Lichess puzzles without a mix by
              ratio, so if you were training My puzzles only, or mixing by ratio, it switches those off too. Your other
              filters and your saved presets don't change.
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setTrain(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setTrain(false);
                  if (narrative.preset) onTrain(narrative.preset);
                }}
                data-testid="train-apply"
              >
                Apply and go to puzzles
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}

function NarrativeView({ x, onJump, onTrain }: { x: GameNarrative; onJump: (ply: number) => void; onTrain: () => void }) {
  return (
    <Stack gap={6} data-testid="narrative">
      <Text size="sm" data-testid="narrative-opening">
        <b>Opening.</b> {x.opening_summary}
      </Text>
      {x.turning_point !== null && (
        <Group gap={6}>
          <Text size="sm" fw={600}>
            Turning point:
          </Text>
          <Button size="compact-xs" variant="light" onClick={() => onJump(x.turning_point!)} data-testid="narrative-turning-point">
            {moveLabel(x.turning_point)} {x.moments.find((m) => m.ply === x.turning_point)?.played_san ?? ""}
          </Button>
        </Group>
      )}
      {x.themes.length > 0 && (
        <Group gap={4}>
          {x.themes.map((t) => (
            <Badge key={t} variant="light" color="indigo" style={{ textTransform: "none" }}>
              {t}
            </Badge>
          ))}
        </Group>
      )}
      {x.takeaways.length > 0 && (
        <List size="sm" spacing={2} data-testid="narrative-takeaways">
          {x.takeaways.map((t, i) => (
            <List.Item key={i}>{t}</List.Item>
          ))}
        </List>
      )}
      {x.preset && (
        <Group gap="xs">
          <Text size="sm">
            Practise: {x.preset.names.join(", ")}
            {x.preset.rating_min !== null || x.preset.rating_max !== null ? ` (${x.preset.rating_min ?? "any"}–${x.preset.rating_max ?? "any"})` : ""}
          </Text>
          <Button size="compact-xs" variant="light" onClick={onTrain} data-testid="narrative-train">
            Train these
          </Button>
        </Group>
      )}
      {x.discarded > 0 && (
        <Text size="xs" c="orange" data-testid="narrative-discarded">
          Some annotations were discarded because they didn't fit the game.
        </Text>
      )}
      <Text size="xs" c="dimmed" data-testid="narrative-cost">
        {x.model} · {x.cached ? "saved, free" : dollars(x.cost_usd)} · the key moments below have the AI's notes
      </Text>
    </Stack>
  );
}

/** A key moment's note from Explain my game, under its entry in the key-moments list. */
export function MomentNote({ m, onShow }: { m: GameMoment; onShow: () => void }) {
  return (
    <Stack gap={2} mt={4} data-testid={`moment-note-${m.ply}`}>
      <Text size="xs">{m.text}</Text>
      {(m.annotations.length > 0 || m.better_uci.length > 0) && (
        <Button size="compact-xs" variant="subtle" w="fit-content" onClick={onShow} data-testid={`moment-show-${m.ply}`}>
          Show on the board{m.better_line.length ? ` (${m.better_line.join(" ")})` : ""}
        </Button>
      )}
    </Stack>
  );
}
