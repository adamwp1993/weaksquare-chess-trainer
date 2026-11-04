import { Alert, Group, Loader, Modal, Paper, SimpleGrid, Stack, Table, Tabs, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { RatingHistory, StatRow, StatsReport } from "../api/types";
import { GameStatsCard } from "../components/GameStatsCard";
import { RatingTrend } from "../components/RatingTrend";
import { ModeDetailsTable, ReasonStatsPanel } from "../components/ReasonStatsPanel";

const pct = (x: number | null) => (x === null ? "–" : `${Math.round(x * 100)}%`);

function Summary({ label, value, hint, testId }: { label: string; value: string; hint: string; testId: string }) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={700} size="xl" data-testid={testId}>
        {value}
      </Text>
      <Text size="xs" c="dimmed">
        {hint}
      </Text>
    </Paper>
  );
}

function StatTable({ rows, first, testId }: { rows: StatRow[]; first: string; testId: string }) {
  if (rows.length === 0) return <Text c="dimmed">Nothing here yet: solve some puzzles first.</Text>;
  return (
    <Table striped highlightOnHover stickyHeader data-testid={testId}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{first}</Table.Th>
          <Table.Th ta="right">Played</Table.Th>
          <Table.Th ta="right">Solved</Table.Th>
          <Table.Th ta="right">Accuracy</Table.Th>
          <Table.Th ta="right" title="Of the puzzles where your first move was right, how often the rest of the line went wrong">
            First move right, line wrong
          </Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r) => (
          <Table.Tr key={r.key}>
            <Table.Td>{r.label}</Table.Td>
            <Table.Td ta="right">{r.attempts.toLocaleString("en-US")}</Table.Td>
            <Table.Td ta="right">{r.solved.toLocaleString("en-US")}</Table.Td>
            <Table.Td ta="right">{pct(r.accuracy)}</Table.Td>
            <Table.Td ta="right">
              {pct(r.line_wrong_rate)}
              {r.first_right > 0 && (
                <Text span size="xs" c="dimmed">
                  {" "}
                  of {r.first_right}
                </Text>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

// FR-9.1, FR-9.2: accuracy per theme, length and rating band, and the "first move right, line
// wrong" rate, from every attempt you've made in this app; FR-9.4: the Lichess rating trend.
export function StatsView({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const [report, setReport] = useState<StatsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ratings, setRatings] = useState<RatingHistory | null>(null);

  useEffect(() => {
    if (!opened) return;
    api.getRatingHistory().then(setRatings, () => setRatings(null));
    api.getStats().then(
      (r) => {
        setReport(r);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [opened]);

  const o = report?.overall;
  return (
    <Modal opened={opened} onClose={onClose} title="Your stats" size="xl">
      {error && <Alert color="red">{error}</Alert>}
      {!report && !error && (
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      )}
      {report && o && (
        <Stack gap="md" data-testid="stats-view">
          <SimpleGrid cols={3}>
            <Summary label="Puzzles played" value={o.attempts.toLocaleString("en-US")} hint={`${o.solved.toLocaleString("en-US")} solved`} testId="stats-played" />
            <Summary label="Accuracy" value={pct(o.accuracy)} hint="Solved with no wrong move and no help" testId="stats-accuracy" />
            <Summary
              label="First move right, line wrong"
              value={pct(o.line_wrong_rate)}
              hint="Of the puzzles where your first move was right. Lower is better: it tracks your calculation."
              testId="stats-line-wrong"
            />
          </SimpleGrid>
          <Tabs defaultValue="theme" keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="theme">By theme</Tabs.Tab>
              <Tabs.Tab value="length">By length</Tabs.Tab>
              <Tabs.Tab value="rating">By rating</Tabs.Tab>
              <Tabs.Tab value="mode" data-testid="stats-mode-tab">By mode</Tabs.Tab>
              <Tabs.Tab value="reasons" data-testid="stats-reasons-tab">Why you missed</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="theme" pt="sm">
              <StatTable rows={report.by_theme} first="Theme" testId="stats-by-theme" />
            </Tabs.Panel>
            <Tabs.Panel value="length" pt="sm">
              <StatTable rows={report.by_length} first="Your moves" testId="stats-by-length" />
            </Tabs.Panel>
            <Tabs.Panel value="rating" pt="sm">
              <StatTable rows={report.by_rating} first="Puzzle rating" testId="stats-by-rating" />
            </Tabs.Panel>
            <Tabs.Panel value="mode" pt="sm">
              <Stack gap="sm">
                <StatTable rows={report.by_mode} first="Mode" testId="stats-by-mode" />
                <ModeDetailsTable d={report.details} />
                <Text size="xs" c="dimmed">
                  Danger-spotting results count only here: spotting a blunder isn't solving the puzzle, so they're left
                  out of the totals and the other tabs.
                </Text>
              </Stack>
            </Tabs.Panel>
            <Tabs.Panel value="reasons" pt="sm">
              <ReasonStatsPanel themes={report.by_theme} />
            </Tabs.Panel>
          </Tabs>
          <RatingTrend history={ratings} />
          <GameStatsCard />
          {report.misclicks > 0 && (
            <Text size="xs" c="dimmed" data-testid="stats-misclicks">
              {report.misclicks} {report.misclicks === 1 ? "miss" : "misses"} tagged Misclick {report.misclicks === 1 ? "is" : "are"} left
              out of these numbers.
            </Text>
          )}
          {report.missing > 0 && (
            <Text size="xs" c="dimmed" data-testid="stats-missing">
              {report.missing} of your attempts are on puzzles no longer in the puzzle database. They count in the totals
              and by rating, but not by theme or length.
            </Text>
          )}
        </Stack>
      )}
    </Modal>
  );
}
