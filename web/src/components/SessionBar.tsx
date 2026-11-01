import { Group, Paper, Text } from "@mantine/core";
import type { SessionStats } from "../api/types";

// The session bar: solved / failed / accuracy for this session, plus all-time totals from user.db.
export function SessionBar({ stats }: { stats: SessionStats | null }) {
  const accuracy = stats?.accuracy == null ? "–" : `${Math.round(stats.accuracy * 100)}%`;
  const progress = stats ? `${stats.played}${stats.queue_size ? ` / ${stats.queue_size}` : ""}` : "0";
  return (
    <Paper withBorder p="xs" radius="md" data-testid="session-bar">
      <Group justify="space-between" gap="lg">
        <Group gap="lg">
          <Text size="sm">
            Solved <b data-testid="stat-solved">{stats?.solved ?? 0}</b>
          </Text>
          <Text size="sm">
            Failed <b data-testid="stat-failed">{stats?.failed ?? 0}</b>
          </Text>
          <Text size="sm">
            Accuracy <b data-testid="stat-accuracy">{accuracy}</b>
          </Text>
          <Text size="sm">
            Played <b>{progress}</b>
          </Text>
        </Group>
        <Text size="xs" c="dimmed" data-testid="stat-all-time">
          All time: {stats?.all_time_solved ?? 0} solved, {stats?.all_time_failed ?? 0} failed
        </Text>
      </Group>
    </Paper>
  );
}
