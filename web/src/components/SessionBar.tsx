import { Group, Paper, Text } from "@mantine/core";
import type { SessionStats } from "../api/types";
import { signedRating } from "../state/lichess";

// The session bar: solved / failed / accuracy for this session, the Lichess rating change summed
// from what Lichess returned (FR-6.11c), plus all-time totals from user.db.
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
          {stats?.rating_change != null && (
            <Text size="sm" fw={600} c={stats.rating_change > 0 ? "green" : stats.rating_change < 0 ? "red" : undefined}
                  data-testid="session-rating">
              {stats.rating_change === 0 ? "±0" : signedRating(stats.rating_change)} this session
            </Text>
          )}
        </Group>
        <Text size="xs" c="dimmed" data-testid="stat-all-time">
          All time: {stats?.all_time_solved ?? 0} solved, {stats?.all_time_failed ?? 0} failed
        </Text>
      </Group>
    </Paper>
  );
}
