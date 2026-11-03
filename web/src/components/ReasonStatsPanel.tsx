import { BarChart } from "@mantine/charts";
import { Alert, Group, Select, Stack, Table, Text, Title, useComputedColorScheme } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { TrainingMode } from "../api/ApiClient";
import type { ModeDetails, ReasonStats, StatRow } from "../api/types";
import { MODES } from "../state/modes";

const pct = (x: number | null) => (x === null ? "–" : `${Math.round(x * 100)}%`);
const share = (n: number, d: number) => (d ? n / d : null);

// The five reasons other than misclick, in FR-5.6 order: categorical slots 1–5, validated with the dataviz
// validator against Mantine's light (#ffffff) and dark (#242424) surfaces. Three light steps sit below 3:1, so
// the trend always ships with its legend and a table view.
const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
};
const SHORT: Record<string, string> = {
  didntLook: "Didn't look",
  missedResource: "Missed their reply",
  miscalculated: "Miscalculated",
  unknownPattern: "Didn't know the pattern",
  rushed: "Rushed",
};

const weekLabel = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
};

/** FR-9.3: each mode's own measure. */
export function ModeDetailsTable({ d }: { d: ModeDetails }) {
  const rows: [string, string, string, string][] = [
    ["Commit the line", "Calculation accuracy (replies predicted)", pct(share(d.replies_correct, d.replies_total)),
      `${d.replies_correct} of ${d.replies_total}`],
    ["Name the idea first", "Ideas found", pct(share(d.ideas_found, d.ideas_total)), `${d.ideas_found} of ${d.ideas_total}`],
    ["Name the idea first", "Tags right", pct(share(d.ideas_found, d.tags_named)), `${d.ideas_found} of ${d.tags_named}`],
    ["Danger spotting", "Safe moves called Safe", pct(share(d.danger_safe_right, d.danger_safe)), `${d.danger_safe_right} of ${d.danger_safe}`],
    ["Danger spotting", "Blunders spotted and punished", pct(share(d.danger_blunder_right, d.danger_blunder)),
      `${d.danger_blunder_right} of ${d.danger_blunder}`],
  ]; // prettier-ignore
  return (
    <Table striped data-testid="stats-mode-details">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Mode</Table.Th>
          <Table.Th>Measure</Table.Th>
          <Table.Th ta="right">Score</Table.Th>
          <Table.Th ta="right">Count</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map(([mode, what, score, count]) => (
          <Table.Tr key={`${mode}-${what}`}>
            <Table.Td>{mode}</Table.Td>
            <Table.Td>{what}</Table.Td>
            <Table.Td ta="right">{score}</Table.Td>
            <Table.Td ta="right">{count}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

/** FR-9.7: why you missed puzzles, for all of them or one theme and/or mode, with a weekly trend. */
export function ReasonStatsPanel({ themes }: { themes: StatRow[] }) {
  const scheme = useComputedColorScheme("light");
  const [theme, setTheme] = useState<string | null>(null);
  const [mode, setMode] = useState<TrainingMode | null>(null);
  const [stats, setStats] = useState<ReasonStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getReasonStats(theme, mode).then(
      (r) => {
        setStats(r);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [theme, mode]);

  const colors = SERIES[scheme === "dark" ? "dark" : "light"];
  const keys = stats?.reasons.map((r) => r.key) ?? [];
  const data = (stats?.trend ?? []).map((w) => ({
    week: weekLabel(w.week),
    ...Object.fromEntries(keys.map((k, i) => [k, w.counts[i] ?? 0])),
  }));
  return (
    <Stack gap="sm" data-testid="stats-reasons">
      <Group gap="sm" align="end">
        <Select
          label="Theme"
          placeholder="All themes"
          data={themes.map((t) => ({ value: t.key, label: t.label }))}
          value={theme}
          onChange={setTheme}
          clearable
          searchable
          size="xs"
          data-testid="reasons-theme"
        />
        <Select
          label="Mode"
          placeholder="All modes"
          data={MODES.map((m) => ({ value: m.value, label: m.label }))}
          value={mode}
          onChange={(v) => setMode(v as TrainingMode | null)}
          clearable
          size="xs"
          data-testid="reasons-mode"
        />
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {stats && stats.tagged === 0 && stats.misclicks === 0 ? (
        <Text c="dimmed" size="sm" data-testid="reasons-empty">
          Nothing tagged yet{theme || mode ? " for this selection" : ""}. After a missed puzzle, pick a reason (keys 1–6)
          and it shows up here.
        </Text>
      ) : (
        stats && (
          <>
            <Table striped data-testid="reasons-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Why you missed it</Table.Th>
                  <Table.Th>Gap</Table.Th>
                  <Table.Th ta="right">Misses</Table.Th>
                  <Table.Th ta="right">Share</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {stats.reasons.map((r) => (
                  <Table.Tr key={r.key}>
                    <Table.Td>{r.label}</Table.Td>
                    <Table.Td>{r.gap}</Table.Td>
                    <Table.Td ta="right">{r.count}</Table.Td>
                    <Table.Td ta="right">{pct(r.share)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <Text size="xs" c="dimmed" data-testid="reasons-misclicks">
              {stats.tagged} tagged · {stats.untagged} not tagged · Misclicks: {stats.misclicks} (left out of your accuracy;
              they still count as losses on Lichess)
            </Text>
            {stats.misclick_warning && (
              <Alert color="yellow" data-testid="reasons-misclick-warning">
                A lot of your misses are tagged Misclick. If the board is hard to use, try turning on the coordinates or
                making the window larger; otherwise, a miss is usually worth a real reason.
              </Alert>
            )}
            {data.length > 0 && (
              <Stack gap={4}>
                <Title order={6}>By week</Title>
                <BarChart
                  h={200}
                  data={data}
                  dataKey="week"
                  type="stacked"
                  withLegend
                  legendProps={{ verticalAlign: "bottom", itemSorter: null }} // the legend follows the stack order, not A–Z
                  gridAxis="y"
                  barProps={{ radius: 2, stroke: "var(--mantine-color-body)", strokeWidth: 2 }}
                  series={keys.map((k, i) => ({ name: k, label: SHORT[k] ?? k, color: colors[i] }))}
                  data-testid="reasons-trend"
                />
                <Table fz="xs" data-testid="reasons-trend-table">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Week of</Table.Th>
                      {keys.map((k) => (
                        <Table.Th key={k} ta="right">
                          {SHORT[k] ?? k}
                        </Table.Th>
                      ))}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {(stats.trend ?? []).map((w) => (
                      <Table.Tr key={w.week}>
                        <Table.Td>{weekLabel(w.week)}</Table.Td>
                        {w.counts.map((n, i) => (
                          <Table.Td key={keys[i]} ta="right">
                            {n}
                          </Table.Td>
                        ))}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Stack>
            )}
          </>
        )
      )}
    </Stack>
  );
}
