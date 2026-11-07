// v0.13: AI notes in the opening trainer (FR-12.5-12.7, 12.15). A note is plain text about a move that already exists.
// Shapes were validated by the backend. Any link here was built by the app from a page title.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Modal,
  NumberInput,
  Paper,
  Progress,
  SegmentedControl,
  Stack,
  Text,
} from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Job, OpeningNote, OpeningNoteQuote, OpeningPrefetchPlan, OpeningScope } from "../api/types";
import { dollars } from "../state/llm";
import { useJob } from "../state/useJob";
import { OptionInfo } from "./OptionInfo";

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const BLOCKED = new Set(["not_configured", "no_model", "no_price", "over_budget", "over_cap"]);

function jobFailed(job: Job | null): string | null {
  return job?.state === "failed" ? job.message : null;
}

export function NoteView({ note }: { note: OpeningNote }) {
  return (
    <Stack gap={6} data-testid="opening-note">
      {note.sections.map((s) => (
        <Text size="sm" key={s.heading}>
          <Text span fw={600}>
            {s.heading}:
          </Text>{" "}
          {s.text}
        </Text>
      ))}
      {note.other_model && (
        <Badge size="xs" variant="light" color="gray" style={{ textTransform: "none", alignSelf: "flex-start" }} data-testid="opening-note-other-model">
          Saved from {note.model}
        </Badge>
      )}
      {note.sources.length > 0 && (
        <Text size="xs" c="dimmed" data-testid="opening-note-credit">
          Based in part on Wikibooks:{" "}
          {note.sources.map((s, i) => (
            <span key={s.url}>
              {i > 0 && ", "}
              <Anchor size="xs" href={s.url} target="_blank" rel="noreferrer">
                {s.label}
              </Anchor>
            </span>
          ))}
          , <Anchor size="xs" href={note.licence_url} target="_blank" rel="noreferrer">{note.licence}</Anchor>, may be adapted.
        </Text>
      )}
      {note.sources.length === 0 && (
        <Text size="xs" c="dimmed" data-testid="opening-note-engine-only">
          Based on Stockfish's figures only: no Wikibooks page was used.
        </Text>
      )}
    </Stack>
  );
}

/** One note: its button with the cost, then the note, then Regenerate (FR-12.5-12.7). */
export function NoteBlock({
  family,
  lineIndex,
  ply,
  positionKey,
  moveUci,
  label,
  onNote,
  testId,
  moves,
}: {
  family: string;
  lineIndex: number;
  ply: number | null;
  /** FR-12.8: a line outside the book: the note is about its last move, and `family` isn't used. */
  moves?: string[];
  positionKey: string | null;
  moveUci: string;
  label: string;
  onNote?: (note: OpeningNote | null) => void;
  testId: string;
}) {
  const [note, setNote] = useState<OpeningNote | null>(null);
  const [quote, setQuote] = useState<OpeningNoteQuote | null>(null);
  const [regen, setRegen] = useState<OpeningNoteQuote | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId);
  const kind = ply === null ? "overview" : "move";

  const load = useCallback(() => {
    if (positionKey === null) return;
    api.getOpeningNote(positionKey, moveUci, kind).then(
      (n) => {
        setNote(n);
        onNote?.(n);
      },
      (e: unknown) => setError(message(e)),
    );
    (moves ? api.getOpeningMovesNoteQuote(moves, false) : api.getOpeningNoteQuote(family, lineIndex, ply, false)).then(
      setQuote,
      (e: unknown) => setError(message(e)),
    );
  }, [positionKey, moveUci, kind, family, lineIndex, ply, onNote, moves]);

  useEffect(load, [load]);

  const state = job?.state;
  useEffect(() => {
    if (state === "done") load();
  }, [state, load]);

  const run = (regenerate: boolean) => {
    setError(null);
    setRegen(null);
    (moves ? api.startOpeningMovesNote(moves, regenerate) : api.startOpeningNote(family, lineIndex, ply, regenerate)).then(
      (id) => (id ? setJobId(id) : load()),
      (e: unknown) => setError(message(e)),
    );
  };

  const running = jobId !== null && (job === null || job.state === "running");
  const why = quote && BLOCKED.has(quote.state) ? quote.message : null;
  const shown = error ?? jobFailed(job);
  return (
    <Stack gap={6} data-testid={testId}>
      {note && <NoteView note={note} />}
      {!note && (
        <Button
          size="xs"
          variant="light"
          color="indigo"
          disabled={running || !quote || !!why}
          onClick={() => run(false)}
          style={{ alignSelf: "flex-start" }}
          data-testid={`${testId}-button`}
        >
          {running ? "Asking the AI…" : quote?.typical_usd ? `${label} (≈ ${dollars(quote.typical_usd)})` : label}
        </Button>
      )}
      {!note && why && (
        <Text size="xs" c="dimmed" data-testid={`${testId}-why`}>
          {why}
        </Text>
      )}
      {note && !regen && (
        <Button
          size="compact-xs"
          variant="subtle"
          disabled={running}
          style={{ alignSelf: "flex-start" }}
          onClick={() =>
            (moves ? api.getOpeningMovesNoteQuote(moves, true) : api.getOpeningNoteQuote(family, lineIndex, ply, true)).then(setRegen, (e: unknown) =>
              setError(message(e)),
            )
          }
          data-testid={`${testId}-regenerate`}
        >
          {running ? "Asking the AI…" : "Regenerate"}
        </Button>
      )}
      {regen &&
        (BLOCKED.has(regen.state) ? (
          <Text size="xs" c="dimmed" data-testid={`${testId}-regen-why`}>
            {regen.message}
          </Text>
        ) : (
          <Group gap="xs" data-testid={`${testId}-regen-confirm`}>
            <Text size="xs">Replace this note for about {dollars(regen.typical_usd ?? 0)}?</Text>
            <Button size="compact-xs" onClick={() => run(true)} data-testid={`${testId}-regen-yes`}>
              Replace
            </Button>
            <Button size="compact-xs" variant="default" onClick={() => setRegen(null)}>
              Keep
            </Button>
          </Group>
        ))}
      {shown && (
        <Alert color="red" data-testid={`${testId}-error`}>
          {shown}
        </Alert>
      )}
    </Stack>
  );
}

function minutes(seconds: number): string {
  return seconds < 90 ? `${Math.max(1, Math.round(seconds))} seconds` : `${Math.round(seconds / 60)} minutes`;
}

/** FR-12.7a, 12.7b: choose a scope, see what it costs and how long it takes, then Confirm. */
export function PrefetchDialog({
  family,
  scope: initial,
  extend: initialExtend,
  onClose,
  onFinished,
}: {
  family: string;
  scope: OpeningScope;
  extend: boolean;
  onClose: () => void;
  onFinished: () => void;
}) {
  const [scope, setScope] = useState(initial);
  const [extend, setExtend] = useState(initialExtend);
  const [plan, setPlan] = useState<OpeningPrefetchPlan | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId);

  const custom = scope.preset === "custom";
  // FR-12.7b: only the latest choice's plan is shown, and Confirm waits for it, so the figures are always what it sends.
  const asked = useRef(0);
  const [answered, setAnswered] = useState<string | null>(null);
  const wanted = JSON.stringify([family, scope.preset, custom ? scope.sub_lines : null, custom ? scope.max_moves : null, extend]);
  const pending = answered !== wanted;
  const reload = useCallback(() => {
    const mine = ++asked.current;
    api.getOpeningPrefetchPlan(family, scope.preset, custom ? scope.sub_lines : null, custom ? scope.max_moves : null, extend).then(
      (next) => {
        if (mine !== asked.current) return;
        setPlan(next);
        setError(null);
        setAnswered(wanted);
      },
      (e: unknown) => {
        if (mine !== asked.current) return;
        setError(message(e));
        setAnswered(wanted);
      },
    );
  }, [family, scope, custom, extend, wanted]);
  useEffect(reload, [reload]);

  // Once per job: `onFinished` re-renders the parent, so it can't be what triggers this.
  const finished = useRef(onFinished);
  useEffect(() => {
    finished.current = onFinished;
  }, [onFinished]);
  const state = job?.state;
  const over = state !== undefined && state !== "running";
  useEffect(() => {
    if (over) {
      reload();
      finished.current();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `reload` changes with the scope; a new scope isn't a new job
  }, [over, jobId]);

  const running = jobId !== null && (job === null || job.state === "running");
  const blocked = plan !== null && plan.llm && !["ok", "split"].includes(plan.state);
  const nothing = plan !== null && plan.llm && plan.requests === 0;
  return (
    <Modal opened onClose={onClose} title="Save the notes for this opening" size="lg" data-testid="prefetch-dialog">
      <Stack gap="sm">
        <div data-option-group>
          <Text size="sm" fw={500}>
            How much <OptionInfo id="openings.scope" />
          </Text>
          <SegmentedControl
            size="xs"
            disabled={running}
            value={scope.preset}
            onChange={(v) => setScope({ ...scope, preset: v as OpeningScope["preset"] })}
            data={[
              { value: "light", label: "Light" },
              { value: "standard", label: "Standard" },
              { value: "deep", label: "Deep" },
              { value: "custom", label: "Custom" },
            ]}
            data-testid="prefetch-preset"
          />
        </div>
        {custom && (
          <Group gap="md">
            <NumberInput
              size="xs"
              w={110}
              min={0}
              max={10}
              label={
                <>
                  Sub-lines <OptionInfo id="openings.subLines" />
                </>
              }
              value={scope.sub_lines}
              onChange={(v) => typeof v === "number" && setScope({ ...scope, sub_lines: v })}
              data-testid="prefetch-sub-lines"
            />
            <NumberInput
              size="xs"
              w={130}
              min={4}
              max={20}
              label={
                <>
                  Moves per line <OptionInfo id="openings.maxMoves" />
                </>
              }
              value={scope.max_moves}
              onChange={(v) => typeof v === "number" && setScope({ ...scope, max_moves: v })}
              data-testid="prefetch-max-moves"
            />
          </Group>
        )}
        <div data-option-group>
          <Text size="sm" fw={500}>
            After the book <OptionInfo id="openings.extend" />
          </Text>
          <SegmentedControl
            size="xs"
            disabled={running}
            value={extend ? "extend" : "stop"}
            onChange={(v) => setExtend(v === "extend")}
            data={[
              { value: "extend", label: "Extend past the book" },
              { value: "stop", label: "Stop at the book's end" },
            ]}
            data-testid="prefetch-extend"
          />
        </div>
        {plan && (
          <Paper withBorder p="sm" radius="md" data-testid="prefetch-plan">
            <Stack gap={4}>
              <Text size="sm" data-testid="prefetch-blurb">
                {plan.blurb}
              </Text>
              <Text size="xs" c="dimmed" data-testid="prefetch-counts">
                {plan.lines} lines, {plan.positions} positions, {plan.requests} requests. {plan.stored} already saved, and so free.
              </Text>
              {plan.llm && (
                <Text size="xs" c="dimmed" data-testid="prefetch-usage">
                  About {plan.input_tokens.toLocaleString()} tokens in and {plan.output_tokens.toLocaleString()} out, about {dollars(plan.typical_usd)}. At most{" "}
                  {dollars(plan.worst_usd)}, against your per-run cap of {dollars(plan.run_cap_usd)}.
                </Text>
              )}
              <Text size="xs" c="dimmed" data-testid="prefetch-time">
                Time: {plan.llm ? `${minutes(plan.llm_seconds)} of AI, ` : ""}
                {minutes(plan.engine_seconds)} of Stockfish.
              </Text>
              {plan.warnings.map((w) => (
                <Text size="sm" c="yellow.8" key={w} data-testid="prefetch-warning">
                  {w}
                </Text>
              ))}
              {plan.state === "split" && (
                <Text size="sm" c="yellow.8" data-testid="prefetch-split">
                  This is over your per-run cap, so it goes in {plan.runs} runs. This run sends {plan.this_run_requests} requests. Open this again for the next one. The cap
                  itself doesn't change.
                </Text>
              )}
              {blocked && (
                <Text size="sm" c="red" data-testid="prefetch-blocked">
                  {plan.message}
                </Text>
              )}
            </Stack>
          </Paper>
        )}
        {running && (
          <Stack gap={4} data-testid="prefetch-running">
            <Progress value={(job?.progress ?? 0) * 100} />
            <Text size="xs" c="dimmed">
              {job?.message ?? "Starting…"} You can keep using the app.
            </Text>
          </Stack>
        )}
        {job?.state === "done" && (
          <Text size="sm" c="teal" data-testid="prefetch-done">
            {job.message}
          </Text>
        )}
        {job?.state === "cancelled" && (
          <Text size="sm" data-testid="prefetch-cancelled">
            Cancelled. What finished stays saved.
          </Text>
        )}
        {(error ?? jobFailed(job)) && (
          <Alert color="red" data-testid="prefetch-error">
            {error ?? jobFailed(job)}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          {running ? (
            <Button variant="default" size="xs" onClick={() => jobId && api.cancelJob(jobId)} data-testid="prefetch-cancel">
              Cancel
            </Button>
          ) : (
            <>
              <Button variant="default" size="xs" onClick={onClose}>
                Close
              </Button>
              <Button
                size="xs"
                disabled={!plan || pending || blocked || nothing}
                data-testid="prefetch-confirm"
                onClick={() => {
                  setError(null);
                  api
                    .startOpeningPrefetch(family, scope.preset, custom ? scope.sub_lines : null, custom ? scope.max_moves : null, extend)
                    .then(setJobId, (e: unknown) => setError(message(e)));
                }}
              >
                {nothing ? "All saved" : "Confirm"}
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
