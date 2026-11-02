import { LineChart } from "@mantine/charts";
import { Stack, Table, Text, Title, useComputedColorScheme } from "@mantine/core";
import type { RatingHistory } from "../api/types";
import { signedRating } from "../state/lichess";

// The line color per scheme, checked with the dataviz validator against each surface:
// teal-9 on white (light) and teal-8 on #242424 (dark) both sit in the lightness band with >= 3:1.
const LINE = { light: "#087f5b", dark: "#0ca678" };

const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

// FR-9.4: your Lichess puzzle rating over time, only as Lichess returned it with synced solves
// (FR-6.11d), and the change per session (the table doubles as the chart's table view).
export function RatingTrend({ history }: { history: RatingHistory | null }) {
  const scheme = useComputedColorScheme("light");
  if (!history) return null;
  if (history.points.length === 0) {
    return (
      <Stack gap={4} data-testid="rating-trend">
        <Title order={5}>Lichess puzzle rating</Title>
        <Text size="sm" c="dimmed" data-testid="rating-trend-empty">
          Nothing yet: sign in with Lichess and solve rated puzzles, and your rating appears here as Lichess reports it.
        </Text>
      </Stack>
    );
  }
  const data = history.points.map((p, i) => ({ i, when: day(p.at), rating: p.rating }));
  const ratings = history.points.map((p) => p.rating);
  const pad = 20;
  return (
    <Stack gap="sm" data-testid="rating-trend">
      <Title order={5}>Lichess puzzle rating</Title>
      <LineChart
        h={220}
        data={data}
        dataKey="when"
        series={[{ name: "rating", label: "Puzzle rating", color: LINE[scheme] }]}
        curveType="linear"
        strokeWidth={2}
        dotProps={{ r: 4 }}
        activeDotProps={{ r: 6 }}
        withLegend={false}
        gridAxis="x"
        xAxisProps={{ minTickGap: 24 }}
        yAxisProps={{ domain: [Math.min(...ratings) - pad, Math.max(...ratings) + pad], allowDecimals: false }}
        tooltipAnimationDuration={0}
        data-testid="rating-chart"
      />
      <Table striped data-testid="rating-sessions">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Session</Table.Th>
            <Table.Th ta="right">Rated solves</Table.Th>
            <Table.Th ta="right">Change</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {[...history.sessions].reverse().map((s) => (
            <Table.Tr key={s.session_id}>
              <Table.Td>{day(s.started_at)}</Table.Td>
              <Table.Td ta="right">{s.solves}</Table.Td>
              <Table.Td ta="right">{s.change === 0 ? "±0" : signedRating(s.change)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
