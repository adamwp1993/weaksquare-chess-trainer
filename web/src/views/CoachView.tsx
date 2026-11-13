// v0.10 The Coach (REQUIREMENTS §10.1–10.6): run settings, a run with progress and cancel, the free
// report (Missed / Allowed themes, habits, mistake reasons, examples, puzzle history, the gap table,
// the trend and the preset), saved reports, and optional AI coaching behind the estimate and Confirm.
// v0.11 (§10.11): the whole-game measures and weaknesses, and the whole-game AI diagnosis (CoachAiPanel).
// Every text from the backend (and the AI) is plain React text, never HTML.
import {
  Alert,
  Button,
  Chip,
  Grid,
  Group,
  Paper,
  Progress,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { CoachParams, TrainingMode } from "../api/ApiClient";
import type { CoachReport, CoachReportSummary, CoachWeakness, FilterSpec, PlanTask } from "../api/types";
import { CoachAiPanel } from "../components/CoachAiPanel";
import { PresetBox } from "../components/CoachPresetBox";
import { JournalTab, type JournalDraft } from "../components/JournalTab";
import { Labeled, OptionInfo } from "../components/OptionInfo";

import { PlanTab } from "../components/PlanTab";
import { SinceLastReport } from "../components/SinceLastReport";
import { WholeGameMeasures } from "../components/WholeGameMeasures";
import { useJob } from "../state/useJob";
import { reasonMix } from "../text/reasons";
import { ProgressTab } from "../components/ProgressTab";

export type CoachTab = "report" | "plan" | "journal" | "progress";

const SOURCES = [
  { value: "puzzles", label: "Puzzle history", note: "No engine time, the fewest AI tokens: the themes you fail when you know it's a puzzle." },
  { value: "games", label: "Games", note: "Minutes of engine time on your PC: what actually costs you games, including tactics you allowed." },
  { value: "both", label: "Both", note: "Minutes of engine time: the gaps between puzzles and games, like forks you solve as puzzles but walk into in games." },
] as const;
const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "daily"];
/** FR-10.73: better or worse only where the guards allow it. */
function trendText(w: CoachWeakness): string {
  const t = w.trend;
  switch (w.change) {
    case "new":
      return "New";
    case "gone":
      return "Gone";
    case "not_enough":
      return "not enough new games yet";
    case "same":
      return "no change";
    case "better":
      return `▼ ${Math.abs(t ?? 0)} (better)`;
    case "worse":
      return `▲ ${t ?? 0} (worse)`;
    default:
      return "";
  }
}

function WeaknessTable({
  title,
  items,
  testid,
  onExample,
  onOpening,
}: {
  title: string;
  items: CoachWeakness[];
  testid: string;
  onExample: (gameId: number, ply: number) => void;
  /** FR-10.58: an opening weakness links to the opening trainer. */
  onOpening?: (name: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <Stack gap={4} data-testid={testid}>
      <Title order={5}>{title}</Title>
      <Table withTableBorder striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Weakness</Table.Th>
            <Table.Th ta="right">Times</Table.Th>
            <Table.Th ta="right">Per 10 games</Table.Th>
            <Table.Th ta="right">Avg. loss</Table.Th>
            <Table.Th>Since last report</Table.Th>
            <Table.Th>Why you missed it</Table.Th>
            <Table.Th>Examples</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((w) => (
            <Table.Tr key={w.key} data-testid={`weakness-${w.key}`}>
              <Table.Td>{w.label}</Table.Td>
              <Table.Td ta="right">{w.count}</Table.Td>
              <Table.Td ta="right">{w.per10}</Table.Td>
              <Table.Td ta="right">{w.severity ? `${(w.severity / 100).toFixed(1)}` : "—"}</Table.Td>
              <Table.Td>
                <Text size="xs">{trendText(w)}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs">{reasonMix(w.reasons)}</Text>
              </Table.Td>
              <Table.Td>
                <Group gap={2}>
                  {w.examples.map((e, i) => (
                    <Button key={i} size="compact-xs" variant="subtle" onClick={() => onExample(e.game_id, e.ply)} data-testid={`example-${w.key}-${i}`}>
                      {i + 1}
                    </Button>
                  ))}
                  {w.kind === "opening" && onOpening && (
                    <Button size="compact-xs" variant="light" onClick={() => onOpening(w.name)} data-testid={`weakness-opening-${w.key}`}>
                      Study this opening
                    </Button>
                  )}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function ReportView({
  report,
  onExample,
  onLoad,
  onPlanChanged,
  onOpening,
}: {
  report: CoachReport;
  onOpening: (name: string) => void;
  onExample: (gameId: number, ply: number) => void;
  onLoad: (spec: FilterSpec, mode: TrainingMode) => void;
  onPlanChanged: () => void;
}) {
  const r = report;
  const period = r.first_played && r.last_played ? `${r.first_played.slice(0, 10)} to ${r.last_played.slice(0, 10)}` : null;
  return (
    <Stack gap="md" data-testid="coach-report">
      <Stack gap={2}>
        <Title order={4}>{r.checkpoint !== null ? `Checkpoint #${r.checkpoint}` : r.subject_label}</Title>
        <Text size="sm" c="dimmed">
          {r.source === "puzzles" ? "Puzzle history" : `${r.games} game${r.games === 1 ? "" : "s"}`}
          {period ? ` · ${period}` : ""} · {r.created_at.slice(0, 16).replace("T", " ")}
        </Text>
        {!r.is_me && (
          <Text size="xs" c="dimmed">
            Another player's report: it never changes your puzzles or your Suggested mix.
          </Text>
        )}
      </Stack>
      {r.notes.map((n, i) => (
        <Alert key={i} color="yellow">
          {n}
        </Alert>
      ))}
      {r.games > 0 && (
        <Group gap="lg" data-testid="coach-overall">
          <Text size="sm">
            Per 10 games: <b>{r.per10.blunders ?? 0}</b> blunders, <b>{r.per10.mistakes ?? 0}</b> mistakes,{" "}
            <b>{r.per10.inaccuracies ?? 0}</b> inaccuracies
          </Text>
          {r.low_clock_errors > 0 && <Text size="sm">{r.low_clock_errors} on a low clock</Text>}
          {Object.keys(r.reasons).length > 0 && <Text size="sm">Why: {reasonMix(r.reasons)}</Text>}
        </Group>
      )}
      {r.comparison && <SinceLastReport c={r.comparison} />}
      <WeaknessTable title="Tactics you allowed" items={r.allowed} testid="coach-allowed" onExample={onExample} />
      <WeaknessTable title="Tactics you missed" items={r.missed} testid="coach-missed" onExample={onExample} />
      <WeaknessTable title="Habits" items={r.habits} testid="coach-habits" onExample={onExample} />
      <WeaknessTable title="Whole-game weaknesses" items={r.whole_game} testid="coach-whole-game" onExample={onExample} onOpening={onOpening} />
      {r.measures && <WholeGameMeasures m={r.measures} />}
      {r.puzzles.length > 0 && (
        <Stack gap={4} data-testid="coach-puzzles">
          <Title order={5}>Puzzle themes you fail most</Title>
          {r.puzzles.map((w) => (
            <Text key={w.key} size="sm">
              {w.label}: {w.puzzle_accuracy !== null ? `${Math.round(w.puzzle_accuracy * 100)}% first try` : "—"}
            </Text>
          ))}
        </Stack>
      )}
      {r.gap.length > 0 && (
        <Stack gap={4} data-testid="coach-gap">
          <Title order={5}>Puzzles vs. games</Title>
          <Table withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Theme</Table.Th>
                <Table.Th ta="right">Puzzles solved first try</Table.Th>
                <Table.Th ta="right">Missed per 10 games</Table.Th>
                <Table.Th ta="right">Allowed per 10 games</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {r.gap.map((g) => (
                <Table.Tr key={g.theme}>
                  <Table.Td>{g.label}</Table.Td>
                  <Table.Td ta="right">{g.puzzle_accuracy !== null ? `${Math.round(g.puzzle_accuracy * 100)}% of ${g.puzzle_attempts}` : "—"}</Table.Td>
                  <Table.Td ta="right">{g.missed_per10}</Table.Td>
                  <Table.Td ta="right">{g.allowed_per10}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}
      {r.games > 0 && r.allowed.length + r.missed.length + r.habits.length === 0 && (
        <Text size="sm" c="dimmed">No tagged tactical mistakes in these games. Well played.</Text>
      )}
      {r.preset && <PresetBox p={r.preset} testid="coach-preset" onLoad={onLoad} />}
      <CoachAiPanel report={r} onLoad={onLoad} onEvidence={onExample} onPlanChanged={onPlanChanged} />
    </Stack>
  );
}

export function CoachView({
  sendIds,
  onClearSend,
  onReview,
  onOpening,
  onLoad,
  onRunDone,
  tab,
  onTab,
  planVersion,
  onPlanChanged,
  onStartTask,
  journalDraft,
  onClearDraft,
  onCloseQuestion,
}: {
  tab: CoachTab;
  onTab: (t: CoachTab) => void;
  planVersion: number;
  onPlanChanged: () => void;
  onStartTask: (t: PlanTask) => void;
  journalDraft: JournalDraft | null;
  onClearDraft: () => void;
  onCloseQuestion: () => void;
  /** Send to Coach (FR-11.30): exactly these games. */
  sendIds: number[];
  onClearSend: () => void;
  onReview: (gameId: number, ply: number) => void;
  onOpening: (name: string) => void;
  onLoad: (spec: FilterSpec, mode: TrainingMode) => void;
  /** A run of yours finished: the Suggested mix may have changed. */
  onRunDone: () => void;
}) {
  const [params, setParams] = useState<CoachParams | null>(null);
  const [whose, setWhose] = useState<"me" | "other">("me");
  const [usernames, setUsernames] = useState<string[]>([]);
  const [reports, setReports] = useState<CoachReportSummary[]>([]);
  const [report, setReport] = useState<CoachReport | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId);

  const loadReports = useCallback(() => {
    api.listCoachReports().then((list) => {
      setReports(list);
      return list;
    }).then((list) => {
      if (list.length > 0) api.getCoachReport(list[0].id).then(setReport, () => undefined);
    }, (e: Error) => setError(e.message)); // prettier-ignore
  }, []);
  useEffect(() => {
    api.getCoachDefaults().then((d) => {
      setParams(d.params as unknown as CoachParams);
      setUsernames(d.usernames);
      if (d.params.player) setWhose("other");
      if (d.running_job) setJobId(d.running_job);
    }, (e: Error) => setError(e.message)); // prettier-ignore
    loadReports();
  }, [loadReports]);
  useEffect(() => {
    if (!job || job.state === "running") return;
    if (job.state === "done") {
      api.getCoachRunResult(job.id).then((id) => {
        if (id !== null) api.getCoachReport(id).then((r) => {
          setReport(r);
          if (r.is_me) onRunDone();
        });
        api.listCoachReports().then(setReports);
      }, () => undefined); // prettier-ignore
    }
  }, [job?.state, job?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!params) return <Text c="dimmed">Loading…</Text>;
  const set = (patch: Partial<CoachParams>) => setParams({ ...params, ...patch });
  const running = job?.state === "running";
  const runIt = async () => {
    setError(null);
    try {
      const p: CoachParams = {
        ...params,
        player: whose === "other" ? (params.player ?? "") : null,
        game_ids: sendIds,
      };
      setJobId(await api.startCoachRun(p));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const mine = report?.is_me ? report : null;
  const weaknesses = mine
    ? [...mine.allowed, ...mine.missed, ...mine.habits, ...mine.whole_game].map((w) => ({ value: w.key, label: w.label }))
    : [];
  return (
    <Tabs value={tab} onChange={(v) => onTab((v as CoachTab) ?? "report")} data-testid="coach-tabs">
      <Tabs.List mb="md">
        <Tabs.Tab value="report" data-testid="coach-tab-report">
          Report
        </Tabs.Tab>
        <Tabs.Tab value="plan" data-testid="coach-tab-plan">
          Plan
        </Tabs.Tab>
        <Tabs.Tab value="journal" data-testid="coach-tab-journal">
          Journal
        </Tabs.Tab>
        <Tabs.Tab value="progress" data-testid="coach-tab-progress">
          Progress
        </Tabs.Tab>
      </Tabs.List>
      {/* The Report tab stays mounted so a Coach run or an AI answer carries on while you look at the others. */}
      <Tabs.Panel value="report">
    <Grid gap="lg" data-testid="coach-page">
      <Grid.Col span={{ base: 12, md: 4 }}>
        <Stack gap="md">
          <Paper withBorder p="md">
            <Stack gap="sm">
              <Title order={4}>The Coach</Title>
              <Text size="sm" c="dimmed">
                Finds what costs you points, on your PC and for free. The AI part is optional.
              </Text>
              <Text size="sm" fw={500}>
                What to read
                <OptionInfo id="coach.source" />
              </Text>
              <SegmentedControl
                data-option-for="coach.source"
                fullWidth
                value={params.source}
                onChange={(v) => set({ source: v as CoachParams["source"] })}
                data={SOURCES.map((s) => ({ value: s.value, label: s.label }))}
                data-testid="coach-source"
              />
              <Text size="xs" c="dimmed">
                {SOURCES.find((s) => s.value === params.source)?.note}
              </Text>
              {sendIds.length > 0 ? (
                <Alert color="blue" data-testid="coach-sent">
                  <Group justify="space-between">
                    <Text size="sm">
                      {sendIds.length} game{sendIds.length === 1 ? "" : "s"} sent from My games.
                    </Text>
                    <Button size="compact-xs" variant="subtle" onClick={onClearSend}>
                      Use my latest games
                    </Button>
                  </Group>
                </Alert>
              ) : (
                params.source !== "puzzles" && (
                  <>
                    <Text size="sm" fw={500}>
                      Whose games
                      <OptionInfo id="coach.whose" />
                    </Text>
                    <SegmentedControl
                      data-option-for="coach.whose"
                      fullWidth
                      value={whose}
                      onChange={(v) => setWhose(v as "me" | "other")}
                      data={[
                        { value: "me", label: usernames.length ? `You (${usernames.join(", ")})` : "You" },
                        { value: "other", label: "Another player" },
                      ]}
                      data-testid="coach-whose"
                    />
                    {whose === "me" && (
                      <Text size="sm" fw={500}>
                        Which of your games
                        <OptionInfo id="coach.platforms" />
                      </Text>
                    )}
                    {whose === "me" && (
                      <SegmentedControl
                        data-option-for="coach.platforms"
                        fullWidth
                        size="xs"
                        value={params.platforms.length === 1 ? params.platforms[0] : "all"}
                        onChange={(v) => set({ platforms: v === "all" ? [] : [v as "lichess" | "chesscom"] })}
                        data={[
                          { value: "all", label: "All my games" },
                          { value: "lichess", label: "Lichess" },
                          { value: "chesscom", label: "chess.com" },
                        ]}
                        data-testid="coach-platforms"
                      />
                    )}
                    {whose === "other" && (
                      <Group grow align="flex-end">
                        <TextInput
                          data-no-tip="a name or link you type"
                          label="Username or profile link"
                          placeholder="lichess.org/@/name"
                          value={params.player ?? ""}
                          onChange={(e) => set({ player: e.currentTarget.value })}
                          data-testid="coach-player"
                        />
                        <Select
                          label={<Labeled id="coach.platform">On</Labeled>}
                          value={params.platform}
                          onChange={(v) => set({ platform: (v as CoachParams["platform"]) ?? "lichess" })}
                          data={[
                            { value: "lichess", label: "Lichess" },
                            { value: "chesscom", label: "chess.com" },
                          ]}
                          allowDeselect={false}
                        />
                      </Group>
                    )}
                    <Select
                      label={<Labeled id="coach.count">Games</Labeled>}
                      value={String(params.count)}
                      onChange={(v) => set({ count: Number(v) as CoachParams["count"] })}
                      data={["25", "50", "100", "200"].map((v) => ({ value: v, label: `Last ${v}` }))}
                      allowDeselect={false}
                      data-testid="coach-count"
                    />
                    <Chip.Group multiple value={params.time_classes} onChange={(v) => set({ time_classes: v })}>
                      <Group gap={4} data-option-group>
                        <Text size="sm" fw={500}>
                          Time controls
                          <OptionInfo id="coach.timeClasses" />
                        </Text>
                        {TIME_CLASSES.map((t) => (
                          <Chip key={t} value={t} size="xs">
                            {t}
                          </Chip>
                        ))}
                      </Group>
                    </Chip.Group>
                    <Group grow>
                      <Switch label={<Labeled id="coach.ratedOnly">Rated only</Labeled>} checked={params.rated_only} onChange={(e) => set({ rated_only: e.currentTarget.checked })} />
                      <Select
                        label={<Labeled id="coach.color">Color</Labeled>}
                        value={params.color}
                        onChange={(v) => set({ color: (v as CoachParams["color"]) ?? "both" })}
                        data={[
                          { value: "both", label: "Both colors" },
                          { value: "white", label: "White" },
                          { value: "black", label: "Black" },
                        ]}
                        allowDeselect={false}
                      />
                    </Group>
                  </>
                )
              )}
              <Select
                label={<Labeled id="coach.detail">AI detail level</Labeled>}
                description="Only matters if you ask for AI coaching: Summary sends 3 key moments per game, Detailed 5 and more examples."
                value={params.detail}
                onChange={(v) => set({ detail: (v as CoachParams["detail"]) ?? "summary" })}
                data={[
                  { value: "summary", label: "Summary" },
                  { value: "detailed", label: "Detailed" },
                ]}
                allowDeselect={false}
              />
              {running && job ? (
                <Stack gap={6} data-testid="coach-progress">
                  <Text size="sm">{job.message}</Text>
                  <Progress value={(job.progress ?? 0) * 100} animated />
                  <Button size="xs" variant="subtle" color="red" onClick={() => api.cancelJob(job.id)} data-testid="coach-cancel">
                    Cancel
                  </Button>
                </Stack>
              ) : (
                <Button onClick={runIt} data-testid="coach-run">
                  Run the Coach
                </Button>
              )}
              {job?.state === "failed" && <Alert color="red" data-testid="coach-failed">{job.message}</Alert>}
              {error && <Alert color="red" data-testid="coach-error">{error}</Alert>}
            </Stack>
          </Paper>
          {reports.length > 0 && (
            <Paper withBorder p="sm" data-testid="coach-history">
              <Stack gap={4}>
                <Title order={5}>Saved reports</Title>
                {reports.map((s) => (
                  <Button
                    key={s.id}
                    variant={report?.id === s.id ? "light" : "subtle"}
                    size="compact-sm"
                    justify="flex-start"
                    onClick={() => api.getCoachReport(s.id).then(setReport, (e: Error) => setError(e.message))}
                    data-testid={`coach-history-${s.id}`}
                  >
                    {s.created_at.slice(0, 10)} · {s.checkpoint !== null ? `Checkpoint #${s.checkpoint}` : s.subject_label} ·{" "}
                    {s.source === "puzzles" ? "puzzles" : `${s.games} game${s.games === 1 ? "" : "s"}`}
                  </Button>
                ))}
              </Stack>
            </Paper>
          )}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 8 }}>
        {report ? (
          <ReportView key={report.id} report={report} onExample={onReview} onLoad={onLoad} onPlanChanged={onPlanChanged} onOpening={onOpening} />
        ) : (
          <Text c="dimmed" data-testid="coach-empty">
            Run the Coach to get your first report.
          </Text>
        )}
      </Grid.Col>
    </Grid>
      </Tabs.Panel>
      <Tabs.Panel value="plan">{tab === "plan" && <PlanTab version={planVersion} onChanged={onPlanChanged} onStart={onStartTask} />}</Tabs.Panel>
      <Tabs.Panel value="progress">
        {tab === "progress" && (
          <ProgressTab
            onOpenReport={(id) =>
              api.getCoachReport(id).then((r) => {
                setReport(r);
                onTab("report");
              }, (e: Error) => setError(e.message)) // prettier-ignore
            }
            onReview={onReview}
          />
        )}
      </Tabs.Panel>
      <Tabs.Panel value="journal">
        {tab === "journal" && (
          <JournalTab
            weaknesses={weaknesses}
            draft={journalDraft}
            onClearDraft={onClearDraft}
            onCloseQuestion={onCloseQuestion}
            onOpen={onReview}
            onChanged={onPlanChanged}
          />
        )}
      </Tabs.Panel>
    </Tabs>
  );
}
