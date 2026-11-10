// v1.0 (FR-10.38): the Coach's Progress tab. One card per weakness with its status and trend, the overall game health,
// the checkpoint history (which doubles as the charts' table view), and the checkpoint settings.
//
// Charts follow the dataviz rules: one y-axis per chart, so game rate (per 10 games) and puzzle accuracy (%) are two
// small charts sharing the time axis rather than one chart with two scales; 2px lines, 8px markers, hollow markers for
// "not enough data yet" (FR-10.34); the rebuilt (backfilled) stretch shaded and labelled, never color alone; every
// rate is per 10 games and every title says which way is better. Colors are the reference palette's first three
// categorical slots, validated with validate_palette.js against Mantine's surfaces (#ffffff light, #242424 dark): all
// checks pass; light aqua is under 3:1, so the checkpoint table carries the same numbers (the relief rule).
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Collapse,
  Group,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  useComputedColorScheme,
} from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import type { CheckpointRow, CheckpointSettings, ProgressView, WeaknessCard } from "../api/types";
import { moveLabel } from "../state/games";
import { useJob } from "../state/useJob";
import { reasonMix } from "../text/reasons";
import { Labeled } from "./OptionInfo";

const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a"],
  dark: ["#3987e5", "#d95926", "#199e70"],
};
const INK = { light: "#495057", dark: "#ced4da" }; // axes, baseline, labels (text tokens, never a series color)
const GRID = { light: "#e9ecef", dark: "#373a40" };
const SURFACE = { light: "#ffffff", dark: "#242424" };

export const STATUS: Record<WeaknessCard["status"], { label: string; color: string; hint: string }> = {
  regressed: { label: "Regressed", color: "red", hint: "back to 90% or more of where it started: top priority again" },
  training: { label: "Training", color: "blue", hint: "in your current Suggested mix" },
  new: { label: "New", color: "gray", hint: "found, not in your mix yet" },
  improving: { label: "Improving", color: "teal", hint: "at 75% or less of where it started" },
  fixed: { label: "Fixed", color: "green", hint: "at half or less for two checkpoints, with your puzzles passing too" },
};
const TRIGGER: Record<CheckpointRow["trigger"], string> = {
  count: "after new games",
  schedule: "on schedule",
  manual: "you ran it",
  backfill: "rebuilt from past games",
};
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "daily"];

const day = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(1));
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(100 * v)}%`);

interface Series {
  key: string;
  label: string;
}
type Row = Record<string, number | string | boolean | null>;

/** One line chart: one y-scale, an optional flat baseline, the rebuilt stretch shaded, hollow guarded markers. */
function TrendChart({
  title,
  data,
  series,
  baseline,
  percent = false,
  height = 150,
  caption = true,
  testId,
}: {
  title: string;
  data: Row[];
  series: Series[];
  baseline?: number;
  percent?: boolean;
  height?: number;
  /** "Shaded: rebuilt from past games" under the chart; a card says it once, under its last chart. */
  caption?: boolean;
  testId: string;
}) {
  const scheme = useComputedColorScheme("light");
  const colors = SERIES[scheme];
  const rebuilt = data.filter((d) => d.reconstructed);
  const last = data.length - 1;
  // Whole-number headroom above the highest value and the baseline, so the baseline's label never sits on the edge.
  const values = data.flatMap((d) => series.map((s) => d[s.key])).filter((v): v is number => typeof v === "number");
  const raw = Math.max(1, Math.max(...values, baseline ?? 0) * 1.2);
  const step = raw <= 6 ? 1 : raw <= 12 ? 2 : raw <= 30 ? 5 : 10;
  const top = Math.ceil(raw / step) * step;
  const ticks = Array.from({ length: top / step + 1 }, (_, i) => i * step).filter((_, i, all) => all.length <= 7 || i % 2 === 0);
  const dot = (color: string, key: string) =>
    function Dot(props: { cx?: number; cy?: number; index?: number; payload?: Row }) {
      const { cx, cy, payload, index } = props;
      if (cx === undefined || cy === undefined || payload?.[key] === null || payload?.[key] === undefined) return <g key={`${key}-${index}`} />;
      const hollow = Boolean(payload[`${key}_guarded`]);
      return (
        <circle
          key={`${key}-${index}`}
          cx={cx}
          cy={cy}
          r={4}
          stroke={hollow ? color : SURFACE[scheme]}
          strokeWidth={2}
          fill={hollow ? SURFACE[scheme] : color}
          data-guarded={hollow ? "true" : undefined}
        />
      );
    };
  return (
    <Stack gap={2} data-testid={testId}>
      <Text size="xs" fw={600}>
        {title}
      </Text>
      <div style={{ width: "100%", height }} aria-label={title}>
        <ResponsiveContainer>
          {/* The same right margin with or without the baseline's label, so a card's two charts put each checkpoint
              at the same x (v1.0-B4). */}
          <LineChart data={data} margin={{ top: 8, right: series.length > 1 ? 72 : 56, bottom: 0, left: -4 }}>
            <CartesianGrid vertical={false} stroke={GRID[scheme]} />
            <XAxis dataKey="when" tick={{ fontSize: 11, fill: INK[scheme] }} tickLine={false} axisLine={{ stroke: GRID[scheme] }} minTickGap={16} />
            <YAxis
              tick={{ fontSize: 11, fill: INK[scheme] }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              domain={percent ? [0, 1] : [0, top]}
              ticks={percent ? [0, 0.5, 1] : ticks}
              interval={0}
              tickFormatter={(v: number) => (percent ? `${Math.round(v * 100)}%` : String(v))}
              width={44}
            />
            {rebuilt.length > 0 && (
              <ReferenceArea
                x1={String(rebuilt[0].when)}
                x2={String(rebuilt[rebuilt.length - 1].when)}
                fill={INK[scheme]}
                fillOpacity={0.07}
                stroke="none"
              />
            )}
            {baseline !== undefined && (
              <ReferenceLine
                y={baseline}
                stroke={INK[scheme]}
                strokeDasharray="4 3"
                label={{ value: `Start ${baseline.toFixed(1)}`, position: "right", fontSize: 10, fill: INK[scheme] }}
              />
            )}
            <Tooltip
              isAnimationActive={false}
              formatter={(v, name, item) => {
                const key = String(item.dataKey);
                const guarded = Boolean((item.payload as Row)[`${key}_guarded`]);
                const text = typeof v === "number" ? (percent ? pct(v) : v.toFixed(1)) : "—";
                return [guarded ? `${text} (not enough data yet)` : text, name];
              }}
              labelFormatter={(_l, items) => {
                const p = items?.[0]?.payload as Row | undefined;
                return p ? `Checkpoint #${p.number} · ${p.when}${p.reconstructed ? " · rebuilt" : ""}` : "";
              }}
            />
            {series.length > 1 && (
              <Legend verticalAlign="top" height={24} iconType="plainline" wrapperStyle={{ fontSize: 11 }} itemSorter={null} />
            )}
            {series.map((s, i) => (
              <Line
                key={s.key}
                type="linear"
                dataKey={s.key}
                name={s.label}
                stroke={colors[i]}
                strokeWidth={2}
                dot={dot(colors[i], s.key)}
                activeDot={{ r: 6 }}
                isAnimationActive={false}
                connectNulls
                label={
                  series.length > 1
                    ? (p: { x?: number | string; y?: number | string; index?: number }) =>
                        p.index === last && p.x !== undefined && p.y !== undefined ? (
                          <text key={`l-${s.key}`} x={Number(p.x) + 8} y={Number(p.y) + 4} fontSize={11} fill={INK[scheme]}>
                            {s.label}
                          </text>
                        ) : (
                          <g key={`l-${s.key}-${p.index}`} />
                        )
                    : undefined
                }
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {caption && rebuilt.length > 0 && (
        <Text size="xs" c="dimmed">
          Shaded: rebuilt from past games
        </Text>
      )}
    </Stack>
  );
}

function WeaknessCardView({ card, onReview }: { card: WeaknessCard; onReview: (gameId: number, ply: number) => void }) {
  const st = STATUS[card.status];
  const rate: Row[] = card.points.map((p) => ({
    number: p.checkpoint, when: day(p.created_at), reconstructed: p.reconstructed, per10: p.per10, per10_guarded: p.guarded,
  })); // prettier-ignore
  const acc: Row[] = card.points.map((p) => ({
    number: p.checkpoint, when: day(p.created_at), reconstructed: p.reconstructed, accuracy: p.puzzle_accuracy,
  })); // prettier-ignore
  const hasAccuracy = card.points.some((p) => p.puzzle_accuracy !== null);
  return (
    <Paper withBorder p="sm" data-testid={`progress-card-${card.key}`}>
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Title order={5}>{card.label}</Title>
          <Badge color={st.color} variant="light" title={st.hint} data-testid="progress-status">
            {st.label}
          </Badge>
        </Group>
        <Text size="sm">
          Started at {fmt(card.baseline_per10)} per 10 games · now {fmt(card.current_per10)}
          {card.current_guarded && (
            <Text span size="sm" c="dimmed" data-testid="progress-guarded">
              {" "}
              (not enough data yet)
            </Text>
          )}
        </Text>
        <TrendChart title="Per 10 games (lower is better)" data={rate} series={[{ key: "per10", label: "Per 10 games" }]}
          baseline={card.baseline_per10} caption={!hasAccuracy} testId="progress-rate-chart" /> {/* prettier-ignore */}
        {hasAccuracy && (
          <TrendChart title="Puzzle accuracy on its themes (higher is better)" data={acc}
            series={[{ key: "accuracy", label: "Puzzle accuracy" }]} percent height={110} testId="progress-accuracy-chart" />
        )} {/* prettier-ignore */}
        <Text size="xs" c="dimmed">
          {!card.puzzle_themes
            ? "No puzzles train this one: its game rate alone decides its status"
            : card.puzzle_attempts === 0
              ? "Puzzles: no tries on its themes yet"
              : `Puzzles: ${pct(card.puzzle_accuracy)} first try over ${card.puzzle_attempts} tries`}{" "}
          · Why you missed it: {reasonMix(card.reasons)}
        </Text>
        {card.examples.length > 0 && (
          <Group gap={4}>
            <Text size="xs" c="dimmed">
              Latest examples:
            </Text>
            {card.examples.map((e) => (
              <Button key={`${e.game_id}-${e.ply}`} size="compact-xs" variant="subtle" onClick={() => onReview(e.game_id, e.ply)}
                data-testid="progress-example"> {/* prettier-ignore */}
                Move {moveLabel(e.ply)}
              </Button>
            ))}
          </Group>
        )}
      </Stack>
    </Paper>
  );
}

function SettingsPanel({ initial, onSaved }: { initial: CheckpointSettings; onSaved: (s: CheckpointSettings) => void }) {
  const [s, setS] = useState<CheckpointSettings>(initial);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const set = (patch: Partial<CheckpointSettings>) => {
    setSaved(false);
    setS({ ...s, ...patch });
  };
  const th = (patch: Partial<CheckpointSettings["thresholds"]>) => set({ thresholds: { ...s.thresholds, ...patch } });
  const percentInput = (label: ReactNode, value: number, onChange: (v: number) => void, testId: string): ReactNode => (
    <NumberInput label={label} value={Math.round(value * 100)} min={1} max={100} suffix="%"
      onChange={(v) => onChange(Number(v) / 100)} data-testid={testId} w={150} />
  ); // prettier-ignore
  const save = async () => {
    setError(null);
    try {
      const out = await api.setCheckpointSettings(s);
      setS(out);
      setSaved(true);
      onSaved(out);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Stack gap="sm" data-testid="checkpoint-settings">
      <Group align="flex-end">
        <NumberInput label={<Labeled id="checkpoints.everyGames">Every N new games</Labeled>} value={s.every_games} min={5} max={200}
          onChange={(v) => set({ every_games: Number(v) })} data-testid="checkpoint-every" w={170} /> {/* prettier-ignore */}
        <NumberInput label={<Labeled id="checkpoints.window">Rolling window (games)</Labeled>} value={s.window} min={10} max={100}
          onChange={(v) => set({ window: Number(v) })} data-testid="checkpoint-window" w={190} /> {/* prettier-ignore */}
      </Group>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          <Labeled id="checkpoints.schedule">Schedule</Labeled>
        </Text>
        <Group align="flex-end">
          <SegmentedControl
            value={s.schedule.kind}
            onChange={(v) => set({ schedule: { ...s.schedule, kind: v as CheckpointSettings["schedule"]["kind"] } })}
            data={[
              { value: "off", label: "Off" },
              { value: "days", label: "Every N days" },
              { value: "weekday", label: "On a weekday" },
            ]}
            data-testid="checkpoint-schedule"
            data-option-for="checkpoints.schedule"
          />
          {s.schedule.kind === "days" && (
            <NumberInput label={<Labeled id="checkpoints.days">Days</Labeled>} value={s.schedule.days} min={1} max={60} w={110}
              onChange={(v) => set({ schedule: { ...s.schedule, days: Number(v) } })} data-testid="checkpoint-days" />
          )} {/* prettier-ignore */}
          {s.schedule.kind === "weekday" && (
            <Select label={<Labeled id="checkpoints.weekday">Day</Labeled>} value={String(s.schedule.weekday)} w={150}
              data={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))} allowDeselect={false}
              onChange={(v) => set({ schedule: { ...s.schedule, weekday: Number(v) } })} data-testid="checkpoint-weekday" />
          )} {/* prettier-ignore */}
        </Group>
      </Stack>
      <Group align="flex-end">
        <Checkbox label={<Labeled id="checkpoints.rated">Rated games only</Labeled>} checked={s.rated_only}
          onChange={(e) => set({ rated_only: e.currentTarget.checked })} data-testid="checkpoint-rated" /> {/* prettier-ignore */}
        <Select label={<Labeled id="checkpoints.color">Color</Labeled>} value={s.color} w={130} allowDeselect={false}
          data={[{ value: "both", label: "Both" }, { value: "white", label: "White" }, { value: "black", label: "Black" }]}
          onChange={(v) => set({ color: (v ?? "both") as CheckpointSettings["color"] })} data-testid="checkpoint-color" /> {/* prettier-ignore */}
      </Group>
      <Checkbox.Group label={<Labeled id="checkpoints.timeClasses">Time controls</Labeled>} value={s.time_classes}
        onChange={(v) => set({ time_classes: v })} data-testid="checkpoint-time-classes" data-option-group> {/* prettier-ignore */}
        <Group mt={4}>
          {TIME_CLASSES.map((t) => (
            <Checkbox key={t} value={t} label={t[0].toUpperCase() + t.slice(1)} />
          ))}
        </Group>
      </Checkbox.Group>
      <Text size="sm" fw={500}>
        Statuses, as a share of where each weakness started
      </Text>
      <Group align="flex-end">
        {percentInput(<Labeled id="checkpoints.improving">Improving at</Labeled>, s.thresholds.improving, (v) => th({ improving: v }), "checkpoint-improving")}
        {percentInput(<Labeled id="checkpoints.fixed">Fixed at</Labeled>, s.thresholds.fixed, (v) => th({ fixed: v }), "checkpoint-fixed")}
        {percentInput(<Labeled id="checkpoints.regressed">Regressed at</Labeled>, s.thresholds.regressed, (v) => th({ regressed: v }), "checkpoint-regressed")}
      </Group>
      <Group align="flex-end">
        <NumberInput label={<Labeled id="checkpoints.streak">Checkpoints in a row</Labeled>} value={s.thresholds.fixed_streak} min={1}
          max={5} w={180} onChange={(v) => th({ fixed_streak: Number(v) })} data-testid="checkpoint-streak" /> {/* prettier-ignore */}
        {percentInput(<Labeled id="checkpoints.puzzleAccuracy">Puzzle accuracy</Labeled>, s.thresholds.puzzle_accuracy, (v) => th({ puzzle_accuracy: v }), "checkpoint-puzzle-accuracy")}
        <NumberInput label={<Labeled id="checkpoints.puzzleAttempts">Over at least (tries)</Labeled>} value={s.thresholds.puzzle_attempts}
          min={5} max={200} w={180} onChange={(v) => th({ puzzle_attempts: Number(v) })} data-testid="checkpoint-puzzle-attempts" /> {/* prettier-ignore */}
      </Group>
      <Switch label={<Labeled id="checkpoints.autoAi">Auto AI checkpoint summary</Labeled>} checked={s.auto_ai}
        onChange={(e) => set({ auto_ai: e.currentTarget.checked })} data-testid="checkpoint-auto-ai" /> {/* prettier-ignore */}
      <Switch label={<Labeled id="checkpoints.notices">Tell me when a status changes</Labeled>} checked={s.notices}
        onChange={(e) => set({ notices: e.currentTarget.checked })} data-testid="checkpoint-notices" /> {/* prettier-ignore */}
      <Group>
        <Button size="xs" onClick={save} data-testid="checkpoint-save">
          Save checkpoint settings
        </Button>
        {saved && (
          <Text size="xs" c="dimmed" data-testid="checkpoint-saved">
            Saved.
          </Text>
        )}
      </Group>
      {error && (
        <Alert color="red" data-testid="checkpoint-settings-error">
          {error}
        </Alert>
      )}
    </Stack>
  );
}

export function ProgressTab({
  onOpenReport,
  onReview,
}: {
  /** A checkpoint's report, in the Report tab (Since last report and Get AI coaching are there). */
  onOpenReport: (reportId: number) => void;
  onReview: (gameId: number, ply: number) => void;
}) {
  const [view, setView] = useState<ProgressView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const job = useJob(jobId);

  const load = useCallback(() => {
    api.getProgress().then((v) => {
      setView(v);
      if (v.running_job) setJobId(v.running_job);
    }, (e: Error) => setError(e.message)); // prettier-ignore
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (job && job.state !== "running") load();
  }, [job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <Alert color="red">{error}</Alert>;
  if (!view) return <Text c="dimmed">Loading…</Text>;
  const s = view.settings;
  const running = job?.state === "running";
  const runNow = async () => {
    setError(null);
    try {
      setJobId(await api.runCheckpointNow());
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const left = Math.max(0, s.every_games - view.new_games);
  const health: Row[] = view.checkpoints.map((c) => {
    const per10 = (c.health.per10 ?? {}) as Record<string, number>;
    return {
      number: c.number, when: day(c.created_at), reconstructed: c.reconstructed,
      blunders: per10.blunders ?? null, mistakes: per10.mistakes ?? null, inaccuracies: per10.inaccuracies ?? null,
      acpl: (c.health.acpl as number | null | undefined) ?? null,
    }; // prettier-ignore
  });

  return (
    <Stack gap="md" data-testid="progress-tab">
      <Paper withBorder p="md">
        <Stack gap="xs">
          <Group justify="space-between">
            <Title order={4}>Progress</Title>
            <Group gap="xs">
              <Button size="xs" variant="default" onClick={() => setShowSettings((v) => !v)} data-testid="checkpoint-settings-toggle">
                {showSettings ? "Hide settings" : "Checkpoint settings"}
              </Button>
              <Button size="xs" onClick={runNow} loading={running} data-testid="checkpoint-run-now">
                Run checkpoint now
              </Button>
            </Group>
          </Group>
          <Text size="sm" c="dimmed" data-testid="checkpoint-next">
            {left === 0
              ? "Enough new games for a checkpoint: it runs shortly, or press Run checkpoint now."
              : `The next checkpoint runs after ${left} more eligible game${left === 1 ? "" : "s"} (every ${s.every_games}).`}
            {s.schedule.kind !== "off" && ` Also ${s.schedule.kind === "days" ? `every ${s.schedule.days} days` : `on ${WEEKDAYS[s.schedule.weekday]}s`}.`}
          </Text>
          {running && job && (
            <Text size="sm" data-testid="checkpoint-running">
              {job.message}
            </Text>
          )}
          {job?.state === "done" && (
            <Text size="sm" c="dimmed" data-testid="checkpoint-done">
              {job.message}
            </Text>
          )}
          {job?.state === "failed" && <Alert color="red">{job.message}</Alert>}
          <Collapse expanded={showSettings}>
            {showSettings && <SettingsPanel initial={s} onSaved={() => load()} />}
          </Collapse>
        </Stack>
      </Paper>

      {view.checkpoints.length === 0 ? (
        <Paper withBorder p="md" data-testid="progress-empty">
          <Stack gap={4}>
            <Title order={5}>No checkpoints yet</Title>
            <Text size="sm">
              A checkpoint looks at your last {s.window} rated {s.time_classes.join(" and ")} games from your linked accounts, measures each
              weakness per 10 games against where it started, and saves a Coach report. It runs on its own after every {s.every_games} new games,
              or when you press Run checkpoint now. Your charts appear here.
            </Text>
          </Stack>
        </Paper>
      ) : (
        <>
          <Paper withBorder p="md" data-testid="progress-health">
            <Stack gap="sm">
              <Title order={5}>Game health</Title>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TrendChart
                  title="Blunders, mistakes and inaccuracies per 10 games (lower is better)"
                  data={health}
                  series={[
                    { key: "blunders", label: "Blunders" },
                    { key: "mistakes", label: "Mistakes" },
                    { key: "inaccuracies", label: "Inaccuracies" },
                  ]}
                  height={200}
                  testId="progress-errors-chart"
                />
                <TrendChart title="Average centipawn loss (lower is better)" data={health}
                  series={[{ key: "acpl", label: "Average centipawn loss" }]} height={200} testId="progress-acpl-chart" />
              </SimpleGrid> {/* prettier-ignore */}
            </Stack>
          </Paper>

          {view.weaknesses.length > 0 && (
            <SimpleGrid cols={{ base: 1, lg: 2 }} data-testid="progress-cards">
              {view.weaknesses.map((c) => (
                <WeaknessCardView key={c.key} card={c} onReview={onReview} />
              ))}
            </SimpleGrid>
          )}

          <Paper withBorder p="md" data-testid="progress-history">
            <Stack gap="xs">
              <Title order={5}>Checkpoints</Title>
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>#</Table.Th>
                    <Table.Th>Date</Table.Th>
                    <Table.Th>How</Table.Th>
                    <Table.Th ta="right">Blunders</Table.Th>
                    <Table.Th ta="right">Mistakes</Table.Th>
                    <Table.Th ta="right">Inaccuracies</Table.Th>
                    <Table.Th ta="right">Avg. loss</Table.Th>
                    <Table.Th>Status changes</Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {[...view.checkpoints].reverse().map((c) => {
                    const per10 = (c.health.per10 ?? {}) as Record<string, number>;
                    const moved = c.changes.filter((x) => x.old !== null);
                    return (
                      <Table.Tr key={c.number} data-testid={`progress-checkpoint-${c.number}`}>
                        <Table.Td>{c.number}</Table.Td>
                        <Table.Td>{day(c.created_at)}</Table.Td>
                        <Table.Td>{TRIGGER[c.trigger]}</Table.Td>
                        <Table.Td ta="right">{fmt(per10.blunders)}</Table.Td>
                        <Table.Td ta="right">{fmt(per10.mistakes)}</Table.Td>
                        <Table.Td ta="right">{fmt(per10.inaccuracies)}</Table.Td>
                        <Table.Td ta="right">{fmt(c.health.acpl as number | null | undefined)}</Table.Td>
                        <Table.Td>
                          <Text size="xs">
                            {moved.length === 0
                              ? "—"
                              : moved.map((x) => `${x.label}: ${STATUS[x.old ?? "new"].label} → ${STATUS[x.new].label}`).join("; ")}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          {c.report_id !== null && (
                            <Group gap={4} wrap="nowrap">
                              <Button size="compact-xs" variant="subtle" onClick={() => onOpenReport(c.report_id as number)}
                                data-testid="progress-open-report"> {/* prettier-ignore */}
                                Report
                              </Button>
                              <Button size="compact-xs" variant="subtle" onClick={() => onOpenReport(c.report_id as number)}
                                data-testid={c.ai_run_id !== null ? "progress-ai-summary" : "progress-get-ai-take"}> {/* prettier-ignore */}
                                {c.ai_run_id !== null ? "AI summary" : "Get AI take"}
                              </Button>
                            </Group>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Stack>
          </Paper>
        </>
      )}
    </Stack>
  );
}
