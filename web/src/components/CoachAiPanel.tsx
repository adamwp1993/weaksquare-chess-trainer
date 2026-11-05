// AI coaching on a Coach report. v0.10: behind the estimate and Confirm, the Coach's own model.
// v0.11 (REQUIREMENTS §10.11): the whole-game diagnosis with evidence that opens Game Review, Advanced
// analysis and Include my notes (per run, off every time, never saved), every answer kept with a picker,
// and lesson pointers whose links only the backend builds. All text is plain React text, never HTML.
import { Alert, Anchor, Badge, Button, Checkbox, Grid, Group, Modal, NumberInput, Paper, Select, Stack, Text, Title } from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { CoachAiOptions, TrainingMode } from "../api/ApiClient";
import type { CoachAiQuote, CoachAiRun, CoachAiRunSummary, CoachFinding, CoachJournalLine, CoachNote, CoachReport, FilterSpec, PlanPreview, PlanSettings } from "../api/types";
import { dollars, useLlmSettings } from "../state/llm";
import { useJob } from "../state/useJob";
import { PresetBox } from "./CoachPresetBox";
import { FeatureModelPicker } from "./FeatureModelPicker";
import { EstimateLines } from "./GameAiPanel";
import { Labeled } from "./OptionInfo";
import { PlanPreviewList } from "./PlanTab";

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
const OFF: CoachAiOptions = { advanced: false, game_cap: 30, include_notes: false, include_journal: false };
const TREND: Record<string, { text: string; color: string }> = {
  improved: { text: "Improved", color: "green" },
  worse: { text: "Worse", color: "red" },
  same: { text: "No change", color: "gray" },
};

function runLabel(r: CoachAiRunSummary, i: number): string {
  const kind = r.advanced ? `Advanced (${r.game_cap} games)` : "Standard";
  return `#${i + 1} · ${kind}${r.include_notes ? " + notes" : ""}${r.include_journal ? " + journal" : ""} · ${r.model}`;
}

function sendsText(o: CoachAiOptions, games: number): string {
  const base =
    "It sends this report's numbers, a short digest of each game (opening, key moments as FEN and SAN, castling, pawn structure, endgame type, time as a % of your clock) and a few example positions: no names, usernames, dates, links or clocks.";
  const adv = o.advanced ? ` Advanced also sends the moves (SAN only) of your ${Math.min(o.game_cap, games)} most recent games in this report.` : "";
  const notes = o.include_notes ? " Include my notes also sends the notes listed in the preview, as written (web addresses removed)." : "";
  const journal = o.include_journal ? " Include my journal also sends the entries listed in the preview, as written (web addresses removed)." : "";
  return base + adv + notes + journal;
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
  onPlanChanged = () => undefined,
}: {
  report: CoachReport;
  onLoad: (spec: FilterSpec, mode: TrainingMode) => void;
  onEvidence: (gameId: number, ply: number) => void;
  onPlanChanged?: () => void;
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
  const [journal, setJournal] = useState<CoachJournalLine[] | null>(null); // v0.12 (FR-10.71)
  const [freePlan, setFreePlan] = useState<PlanPreview | null>(null); // FR-10.66: to compare with the AI's
  const [useConfirm, setUseConfirm] = useState(false);
  const [planUsed, setPlanUsed] = useState(false);
  const [planShape, setPlanShape] = useState<PlanSettings | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false); // QA v0.11-B5: one click, one paid run
  const startingRef = useRef(false); // the second click of a double-click comes before a re-render
  const job = useJob(jobId);

  const loadRuns = (select: number | null) =>
    api.listCoachAiRuns(report.id).then((list) => {
      setRuns(list);
      setRunId(select ?? (list.length ? list[list.length - 1].id : null));
    }, (e: Error) => setError(e.message)); // prettier-ignore

  useEffect(() => {
    void loadRuns(null);
    if (report.is_me) api.getPlanSettings().then(setPlanShape, () => undefined);
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
    if (job && job.state !== "running") {
      startingRef.current = false;
      setStarting(false); // eslint-disable-line react-hooks/set-state-in-effect
    }
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
  const setJournalOption = (on: boolean) => {
    setOpts({ ...opts, include_journal: on });
    if (on) {
      setJournal(null);
      setNotesOpen(true);
      api.getCoachJournalPreview(report.id).then(setJournal, (e: Error) => setError(e.message));
    }
  };
  const removeFromPreview = () => {
    setOpts({ ...opts, include_notes: false, include_journal: false });
    setNotesOpen(false);
  };
  const adoptPlan = (confirmed: boolean) => {
    if (!run) return;
    setUseConfirm(false);
    api.useAiPlan(run.id, confirmed).then(() => {
      setPlanUsed(true);
      onPlanChanged();
    }, (e: Error) => setError(e.message)); // prettier-ignore
  };
  const start = async () => {
    if (startingRef.current) return;
    startingRef.current = true;
    setStarting(true);
    setConfirm(false);
    setError(null);
    try {
      setJobId(await api.startCoachAi(report.id, opts)); // the guard stays until this job ends (below)
    } catch (e) {
      setError((e as Error).message);
      startingRef.current = false;
      setStarting(false);
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
              label={<Labeled id="coach.advanced">Advanced analysis: also send the games' moves</Labeled>}
              checked={opts.advanced}
              onChange={(e) => setOpts({ ...opts, advanced: e.currentTarget.checked })}
              data-testid="coach-ai-advanced"
            />
            {opts.advanced && (
              <NumberInput
                size="xs"
                w={150}
                label={<Labeled id="coach.gameCap">Games (10–50)</Labeled>}
                min={10}
                max={50}
                value={opts.game_cap}
                onChange={(v) => typeof v === "number" && v >= 10 && v <= 50 && setOpts({ ...opts, game_cap: Math.round(v) })}
                data-testid="coach-ai-cap"
              />
            )}
            {report.is_me && (
              <Checkbox
                label={<Labeled id="coach.includeNotes">Include my notes</Labeled>}
                checked={opts.include_notes}
                onChange={(e) => setNotesOption(e.currentTarget.checked)}
                data-testid="coach-ai-notes"
              />
            )}
            {report.is_me && (
              <Checkbox
                label={<Labeled id="coach.includeJournal">Include my journal</Labeled>}
                checked={opts.include_journal}
                onChange={(e) => setJournalOption(e.currentTarget.checked)}
                data-testid="coach-ai-journal"
              />
            )}
            {opts.include_notes && (
              <Anchor size="xs" component="button" onClick={() => setNotesOption(true)} data-testid="coach-ai-notes-show">
                See what's sent
              </Anchor>
            )}
            {!opts.include_notes && opts.include_journal && (
              <Anchor size="xs" component="button" onClick={() => setJournalOption(true)} data-testid="coach-ai-journal-show">
                See what's sent
              </Anchor>
            )}
          </Group>
        )}
        {planShape && (
          <Text size="xs" c="dimmed" data-testid="coach-ai-plan-shape">
            The answer includes a training plan: {planShape.weeks} week{planShape.weeks === 1 ? "" : "s"}, {planShape.weekdays.length} day
            {planShape.weekdays.length === 1 ? "" : "s"} a week, {planShape.minutes} minutes a day. Change that in the Plan tab.
          </Text>
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
            disabled={blocked || running || starting}
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
            label={<Labeled id="coach.answers">Answers for this report</Labeled>}
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
            {run.trend.length > 0 && (
              <Paper withBorder p="xs" data-testid="ai-trend">
                <Stack gap={4}>
                  <Text size="sm" fw={600}>
                    Since last report
                  </Text>
                  {run.trend.map((t) => (
                    <Group key={t.key} gap={6} wrap="nowrap" align="flex-start" data-testid={`ai-trend-${t.key}`}>
                      <Badge size="xs" variant="light" color={TREND[t.change]?.color}>
                        {TREND[t.change]?.text}
                      </Badge>
                      <Text size="sm">
                        {t.label}: {t.comment}
                      </Text>
                    </Group>
                  ))}
                </Stack>
              </Paper>
            )}
            {run.findings.map((f, i) => (
              <Finding key={i} f={f} reportId={report.id} onEvidence={onEvidence} onLoad={onLoad} onError={setError} />
            ))}
            {run.fallback_preset && <Text size="xs" c="dimmed">The AI's presets weren't usable, so this is the report's own mix.</Text>}
            {run.presets.map((p, i) => (
              <PresetBox key={i} p={p} testid={`coach-ai-preset-${i}`} onLoad={onLoad} />
            ))}
            <Text size="xs" c="dimmed">
              {run.advanced ? `Advanced (${run.game_cap} games)` : "Standard"}
              {run.include_notes ? " with your notes" : ""}
              {run.include_journal ? " with your journal" : ""} · {run.model} · {dollars(run.cost_usd)}
              {run.discarded > 0 ? ` · ${run.discarded} unchecked claim${run.discarded === 1 ? "" : "s"} left out` : ""}
            </Text>
            {run.plan && (
              <Paper withBorder p="xs" data-testid="ai-plan">
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text size="sm" fw={600}>
                      The AI's training plan
                    </Text>
                    <Group gap="xs">
                      <Button size="compact-xs" variant="default" onClick={() => api.previewPlan(null).then(setFreePlan, (e: Error) => setError(e.message))} data-testid="ai-plan-compare">
                        Compare with the free plan
                      </Button>
                      <Button size="compact-xs" onClick={() => (run.plan?.replaces ? setUseConfirm(true) : adoptPlan(false))} data-testid="ai-plan-use">
                        Use this plan
                      </Button>
                    </Group>
                  </Group>
                  <Text size="xs" c="dimmed" data-testid="ai-plan-check">
                    {run.plan_check?.fallback
                      ? "The AI's plan wasn't usable, so this is the free plan."
                      : `${run.plan.weeks} week${run.plan.weeks === 1 ? "" : "s"}, ${run.plan.weekdays.length} days a week, ${run.plan.minutes} minutes a day. ${run.plan_check?.ai_tasks ?? 0} tasks from the AI, ${run.plan_check?.filled ?? 0} filled in from the free plan, ${run.plan_check?.dropped ?? 0} left out because they couldn't be checked.`}
                  </Text>
                  {planUsed && (
                    <Text size="xs" c="teal" data-testid="ai-plan-used">
                      This is now your plan: see the Plan tab.
                    </Text>
                  )}
                  <Grid gap="sm">
                    <Grid.Col span={freePlan ? 6 : 12}>
                      <PlanPreviewList plan={run.plan} testid="ai-plan-list" />
                    </Grid.Col>
                    {freePlan && (
                      <Grid.Col span={6}>
                        <Text size="xs" c="dimmed" mb={4}>
                          The free plan
                        </Text>
                        <PlanPreviewList plan={freePlan} testid="ai-plan-free" />
                      </Grid.Col>
                    )}
                  </Grid>
                </Stack>
              </Paper>
            )}
          </Stack>
        )}
      </Stack>
      <Modal
        opened={notesOpen}
        onClose={() => setNotesOpen(false)}
        title={opts.include_journal ? "What will be sent" : "Your notes that will be sent"}
        data-testid="coach-notes-preview"
      >
        <Stack gap="xs">
          {opts.include_notes && opts.include_journal && (
            <Text size="sm" fw={600}>
              Your notes
            </Text>
          )}
          {opts.include_notes &&
            (notes === null ? (
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
            ))}
          {opts.include_journal && (
            <Text size="sm" fw={600}>
              Your journal
            </Text>
          )}
          {opts.include_journal &&
            (journal === null ? (
              <Text size="sm" c="dimmed">
                Loading…
              </Text>
            ) : journal.length === 0 ? (
              <Text size="sm" data-testid="coach-journal-empty">
                You have no journal entries for these games or this period, so nothing extra is sent.
              </Text>
            ) : (
              journal.map((n, i) => (
                <Paper key={i} withBorder p="xs" data-testid="coach-journal-line">
                  <Text size="xs" c="dimmed">
                    {n.kind === "reflection" ? "Game reflection" : "Note"}
                    {n.game ? ` · ${n.game}${n.move ? ` · ${n.move}` : ""}` : ""}
                    {n.weakness ? ` · ${n.weakness}` : ""}
                  </Text>
                  <Text size="sm">{n.text}</Text>
                </Paper>
              ))
            ))}
          <Text size="xs" c="dimmed">
            Exactly these words go to the AI with the rest of the prompt. Web addresses are removed. Games are labelled G1, G2… and
            never named.
          </Text>
          {opts.include_journal && (
            <Text size="xs" c="orange" data-testid="coach-journal-warning">
              Your entries are sent as written, so a name you typed yourself goes too. Edit the entry first if you'd rather it didn't.
              At most the newest 30 entries are sent, each up to 1,000 characters.
            </Text>
          )}
          <Group justify="flex-end">
            <Button size="xs" variant="default" onClick={removeFromPreview} data-testid="coach-notes-remove">
              Don't include them
            </Button>
            <Button size="xs" onClick={() => setNotesOpen(false)} data-testid="coach-notes-ok">
              Include them
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal opened={useConfirm} onClose={() => setUseConfirm(false)} title="Replace your current plan?" data-testid="ai-plan-confirm">
        <Stack>
          <Text size="sm">This makes the AI's plan your plan, starting on your next training day. Your current plan stays under Earlier plans with what you've done so far.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setUseConfirm(false)}>
              Cancel
            </Button>
            <Button onClick={() => adoptPlan(true)} data-testid="ai-plan-confirm-button">
              Replace it
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
              <Button color="indigo" onClick={start} disabled={starting} data-testid="coach-ai-confirm-button">
                Confirm
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
