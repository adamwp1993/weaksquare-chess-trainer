// AI coaching on a Coach report. v0.10: behind the estimate and Confirm, the Coach's own model.
// v0.11 (REQUIREMENTS §10.11): the whole-game diagnosis with evidence that opens Game Review, Advanced
// analysis and Include my notes (per run, off every time, never saved), every answer kept with a picker,
// and lesson pointers whose links only the backend builds. All text is plain React text, never HTML.
import { Alert, Anchor, Badge, Button, Checkbox, Group, Modal, NumberInput, Paper, Select, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { CoachAiOptions, TrainingMode } from "../api/ApiClient";
import type { CoachAiQuote, CoachAiRun, CoachAiRunSummary, CoachFinding, CoachNote, CoachReport, FilterSpec } from "../api/types";
import { dollars, useLlmSettings } from "../state/llm";
import { useJob } from "../state/useJob";
import { PresetBox } from "./CoachPresetBox";
import { FeatureModelPicker } from "./FeatureModelPicker";
import { EstimateLines } from "./GameAiPanel";

const BLOCKED = new Set(["not_configured", "no_model", "no_price", "over_budget", "over_cap"]);
const CATEGORY: Record<string, string> = {
  tactical: "Tactics",
  strategic: "Strategy",
  opening: "Opening",
  endgame: "Endgame",
  time: "Time",
  other: "Other",
};
const SITE: Record<string, string> = { youtube: "Search YouTube", chesscom: "Search chess.com", custom: "Search my site" };
const OFF: CoachAiOptions = { advanced: false, game_cap: 30, include_notes: false };

function runLabel(r: CoachAiRunSummary, i: number): string {
  const kind = r.advanced ? `Advanced (${r.game_cap} games)` : "Standard";
  return `#${i + 1} · ${kind}${r.include_notes ? " + notes" : ""} · ${r.model}`;
}

function sendsText(o: CoachAiOptions, games: number): string {
  const base =
    "It sends this report's numbers, a short digest of each game (opening, key moments as FEN and SAN, castling, pawn structure, endgame type, time as a % of your clock) and a few example positions: no names, usernames, dates, links or clocks.";
  const adv = o.advanced ? ` Advanced also sends the moves (SAN only) of your ${Math.min(o.game_cap, games)} most recent games in this report.` : "";
  const notes = o.include_notes ? " Include my notes also sends the notes listed in the preview, as written (web addresses removed)." : "";
  return base + adv + notes;
}

function Finding({
  f,
  reportId,
  onEvidence,
  onLoad,
  onError,
}: {
  f: CoachFinding;
  reportId: number;
  onEvidence: (gameId: number, ply: number) => void;
  onLoad: (spec: FilterSpec, mode: TrainingMode) => void;
  onError: (m: string) => void;
}) {
  const open = (target: string) => api.openLesson(reportId, f.lesson!.topic, target).catch((e: Error) => onError(e.message));
  return (
    <Paper withBorder p="xs" data-testid="ai-finding">
      <Stack gap={4}>
        <Group gap={6}>
          <Text size="sm" fw={600}>
            {f.title}
          </Text>
          <Badge size="xs" variant="light">
            {CATEGORY[f.category] ?? f.category}
          </Badge>
          {f.observation ? (
            <Badge size="xs" variant="outline" color="gray" data-testid="finding-observation">
              Observation
            </Badge>
          ) : (
            <Badge size="xs" variant="outline" color="indigo" data-testid="finding-tracked">
              Tracked: {f.label}
            </Badge>
          )}
          {f.tentative && (
            <Badge size="xs" color="yellow" variant="light" data-testid="finding-tentative">
              Tentative: fewer than 3 games
            </Badge>
          )}
          {f.observation && f.seen > 1 && (
            <Badge size="xs" color="grape" variant="light" data-testid="finding-seen">
              Seen in {f.seen} reports
            </Badge>
          )}
          {f.new && (
            <Badge size="xs" color="teal" data-testid="finding-new">
              New in this run
            </Badge>
          )}
        </Group>
        <Text size="sm">{f.explanation}</Text>
        <Text size="sm" c="dimmed">
          What to do: {f.advice}
        </Text>
        {f.evidence.length > 0 && (
          <Group gap={4} data-testid="finding-evidence">
            <Text size="xs" c="dimmed">
              In your games:
            </Text>
            {f.evidence.map((e, i) => (
              <Button key={i} size="compact-xs" variant="light" onClick={() => onEvidence(e.game_id, e.ply)} data-testid={`evidence-${e.label}-${e.ply}`}>
                {e.label} · {e.move}
              </Button>
            ))}
          </Group>
        )}
        {f.lesson && (
          <Group gap={6} data-testid="finding-lesson">
            <Text size="xs" c="dimmed">
              Learn {f.lesson.label}:
            </Text>
            {f.lesson.drill && (
              <Button size="compact-xs" onClick={() => onLoad(f.lesson!.drill!.spec as unknown as FilterSpec, "standard")} data-testid="lesson-drill">
                Drill it here (use Explain after each one)
              </Button>
            )}
            {f.lesson.curated.map((title, i) => (
              <Anchor key={i} size="xs" component="button" onClick={() => open(`curated:${i}`)} data-testid={`lesson-curated-${i}`}>
                {title}
              </Anchor>
            ))}
            {f.lesson.sites.map((s) => (
              <Anchor key={s} size="xs" component="button" onClick={() => open(s)} data-testid={`lesson-${s}`}>
                {SITE[s]}
              </Anchor>
            ))}
          </Group>
        )}
      </Stack>
    </Paper>
  );
}

export function CoachAiPanel({
  report,
  onLoad,
  onEvidence,
}: {
  report: CoachReport;
  onLoad: (spec: FilterSpec, mode: TrainingMode) => void;
  onEvidence: (gameId: number, ply: number) => void;
}) {
  const settings = useLlmSettings();
  const feature = settings?.features.find((f) => f.feature === "coach");
  const hasGames = report.source !== "puzzles" && report.games > 0;
  const [opts, setOpts] = useState<CoachAiOptions>(OFF); // off every time the report opens (FR-10.56)
  const [quote, setQuote] = useState<CoachAiQuote | null>(null);
  const [runs, setRuns] = useState<CoachAiRunSummary[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [run, setRun] = useState<CoachAiRun | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [notes, setNotes] = useState<CoachNote[] | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId);

  const loadRuns = (select: number | null) =>
    api.listCoachAiRuns(report.id).then((list) => {
      setRuns(list);
      setRunId(select ?? (list.length ? list[list.length - 1].id : null));
    }, (e: Error) => setError(e.message)); // prettier-ignore

  useEffect(() => {
    void loadRuns(null);
  }, [report.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let alive = true;
    api.getCoachAiQuote(report.id, opts).then((q) => alive && setQuote(q), (e: Error) => alive && setError(e.message)); // prettier-ignore
    return () => {
      alive = false;
    };
  }, [report.id, settings, opts]);
  useEffect(() => {
    if (runId === null) return; // the panel remounts per report (ReportView is keyed by it)
    api.getCoachAiRun(report.id, runId).then(setRun, (e: Error) => setError(e.message));
  }, [report.id, runId]);
  useEffect(() => {
    if (job?.state !== "done") return;
    api.getCoachAiJobRun(job.id).then((id) => loadRuns(id), (e: Error) => setError(e.message));
    api.getCoachAiQuote(report.id, opts).then(setQuote, () => undefined);
  }, [job?.state, job?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const setNotesOption = (on: boolean) => {
    setOpts({ ...opts, include_notes: on });
    if (on) {
      setNotes(null);
      setNotesOpen(true);
      api.getCoachNotesPreview(report.id).then(setNotes, (e: Error) => setError(e.message));
    }
  };
  const start = async () => {
    setConfirm(false);
    setError(null);
    try {
      setJobId(await api.startCoachAi(report.id, opts));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const q = quote?.quote ?? null;
  const blocked = !q || BLOCKED.has(q.state);
  const running = job?.state === "running";
  const c = quote?.compare ?? null;
  return (
    <Paper withBorder p="sm" data-testid="coach-ai">
      <Stack gap="xs">
        <Group justify="space-between">
          <Title order={5}>AI coaching (optional)</Title>
          {feature && (
            <Text size="xs" c="dimmed">
              {feature.effective_model || "no model"}
            </Text>
          )}
        </Group>
        <FeatureModelPicker feature="coach" compact onError={setError} />
        {hasGames && (
          <Group gap="md" align="flex-end">
            <Checkbox
              label="Advanced analysis: also send the games' moves"
              checked={opts.advanced}
              onChange={(e) => setOpts({ ...opts, advanced: e.currentTarget.checked })}
              data-testid="coach-ai-advanced"
            />
            {opts.advanced && (
              <NumberInput
                size="xs"
                w={150}
                label="Games (10–50)"
                min={10}
                max={50}
                value={opts.game_cap}
                onChange={(v) => typeof v === "number" && v >= 10 && v <= 50 && setOpts({ ...opts, game_cap: Math.round(v) })}
                data-testid="coach-ai-cap"
              />
            )}
            {report.is_me && (
              <Checkbox
                label="Include my notes"
                checked={opts.include_notes}
                onChange={(e) => setNotesOption(e.currentTarget.checked)}
                data-testid="coach-ai-notes"
              />
            )}
            {opts.include_notes && (
              <Anchor size="xs" component="button" onClick={() => setNotesOption(true)} data-testid="coach-ai-notes-show">
                See what's sent
              </Anchor>
            )}
          </Group>
        )}
        {opts.advanced && (
          <Text size="xs" c="dimmed">
            Advanced takes longer and uses more AI tokens. You'll see the cost before anything is sent.
          </Text>
        )}
        <Group>
          <Button
            size="xs"
            color="indigo"
            disabled={blocked || running}
            loading={running}
            onClick={() => (q?.state === "cached" ? start() : setConfirm(true))}
            data-testid="coach-ai-start"
          >
            {q?.state === "cached"
              ? "Show the saved answer"
              : runs.length
                ? `Ask ${feature?.effective_model || "the AI"} with these options`
                : "Get AI coaching"}
          </Button>
          {q && blocked && <Text size="xs" c="dimmed">{q.message}</Text>}
        </Group>
        {running && job && <Text size="xs" c="dimmed">{job.message}</Text>}
        {(error ?? (job?.state === "failed" ? job.message : null)) && (
          <Alert color="red" data-testid="coach-ai-error">
            {error ?? job?.message}
          </Alert>
        )}
        {runs.length > 1 && (
          <Select
            size="xs"
            label="Answers for this report"
            value={runId !== null ? String(runId) : null}
            onChange={(v) => v && setRunId(Number(v))}
            data={runs.map((r, i) => ({ value: String(r.id), label: runLabel(r, i) + (r.new ? ` · ${r.new} new` : "") }))}
            allowDeselect={false}
            data-testid="coach-ai-runs"
          />
        )}
        {run && (
          <Stack gap="xs" data-testid="coach-ai-result">
            <Text size="sm">{run.summary}</Text>
            {run.findings.map((f, i) => (
              <Finding key={i} f={f} reportId={report.id} onEvidence={onEvidence} onLoad={onLoad} onError={setError} />
            ))}
            {run.fallback_preset && <Text size="xs" c="dimmed">The AI's presets weren't usable, so this is the report's own mix.</Text>}
            {run.presets.map((p, i) => (
              <PresetBox key={i} p={p} testid={`coach-ai-preset-${i}`} onLoad={onLoad} />
            ))}
            <Text size="xs" c="dimmed">
              {run.advanced ? `Advanced (${run.game_cap} games)` : "Standard"}
              {run.include_notes ? " with your notes" : ""} · {run.model} · {dollars(run.cost_usd)}
              {run.discarded > 0 ? ` · ${run.discarded} unchecked claim${run.discarded === 1 ? "" : "s"} left out` : ""}
            </Text>
          </Stack>
        )}
      </Stack>
      <Modal opened={notesOpen} onClose={() => setNotesOpen(false)} title="Your notes that will be sent" data-testid="coach-notes-preview">
        <Stack gap="xs">
          {notes === null ? (
            <Text size="sm" c="dimmed">
              Loading…
            </Text>
          ) : notes.length === 0 ? (
            <Text size="sm">You have no notes for these games or this period, so nothing extra is sent.</Text>
          ) : (
            notes.map((n, i) => (
              <Paper key={i} withBorder p="xs" data-testid="coach-note">
                <Text size="xs" c="dimmed">
                  {n.game ? `${n.game} · ${n.move ?? `ply ${n.ply}`}` : "A puzzle"}
                  {n.reason ? ` · ${n.reason}` : ""}
                </Text>
                <Text size="sm">{n.text}</Text>
              </Paper>
            ))
          )}
          <Text size="xs" c="dimmed">
            Exactly these words go to the AI with the rest of the prompt. Web addresses are removed. Games are labelled G1, G2… and
            never named.
          </Text>
          <Group justify="flex-end">
            <Button size="xs" variant="default" onClick={() => {
                setNotesOption(false);
                setNotesOpen(false);
              }} data-testid="coach-notes-remove">
              Don't include them
            </Button>
            <Button size="xs" onClick={() => setNotesOpen(false)} data-testid="coach-notes-ok">
              Include them
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal opened={confirm && !!q && q.state === "ok"} onClose={() => setConfirm(false)} title="Get AI coaching?" data-testid="coach-ai-confirm">
        {q && (
          <Stack>
            {c && (
              <Alert color="yellow" data-testid="coach-ai-compare">
                Advanced: about {c.token_ratio ?? "?"}× the tokens of a standard run (a standard run is about {dollars(c.standard_usd ?? 0)}),
                ~{dollars(q.typical_usd ?? 0)}
                {c.budget_share !== null ? ` (${Math.round(c.budget_share * 1000) / 10}% of this month's budget)` : ""}, about {c.minutes}{" "}
                minute{c.minutes === 1 ? "" : "s"}. It sends the moves of {c.games_with_moves} game{c.games_with_moves === 1 ? "" : "s"}. It
                takes longer and uses more API tokens.
              </Alert>
            )}
            <EstimateLines q={q} sends={sendsText(opts, report.games)} />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setConfirm(false)}>
                Cancel
              </Button>
              <Button color="indigo" onClick={start} data-testid="coach-ai-confirm-button">
                Confirm
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
