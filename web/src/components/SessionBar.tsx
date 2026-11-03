import { Badge, Group, Paper, Text } from "@mantine/core";
import type { SessionStats } from "../api/types";
import { signedRating } from "../state/lichess";
import { modeLabel } from "../state/modes";

// The session bar: solved / failed / accuracy for this session, the Lichess rating change summed
// from what Lichess returned (FR-6.11c), plus all-time totals from user.db. v0.5: the session's
// mode (§6) and, for a depth-ladder order, the level and its window (FR-4.5).
export function SessionBar({ stats }: { stats: SessionStats | null }) {
  const accuracy = stats?.accuracy == null ? "–" : `${Math.round(stats.accuracy * 100)}%`;
  const progress = stats ? `${stats.played}${stats.queue_size ? ` / ${stats.queue_size}` : ""}` : "0";
  return (
    <Paper withBorder p="xs" radius="md" data-testid="session-bar">
      <Group justify="space-between" gap="lg">
        <Group gap="lg">
          {stats && (
            <Badge variant="light" color="gray" style={{ textTransform: "none" }} data-testid="session-mode">
              {modeLabel(stats.mode)}
            </Badge>
          )}
          {stats?.ladder && (
            <Text size="sm" data-testid="session-ladder">
              Ladder <b>{stats.ladder.label}</b> ({stats.ladder.step}/{stats.ladder.steps})
              {!stats.ladder.top && ` · ${stats.ladder.played} of ${stats.ladder.window}`}
              {!stats.ladder.top && stats.ladder.played > 0 && ` · ${Math.round((stats.ladder.wins / stats.ladder.played) * 100)}%`}
            </Text>
          )}
          <Text size="sm">
            Solved <b data-testid="stat-solved">{stats?.solved ?? 0}</b>
          </Text>
          <Text size="sm">
            Failed <b data-testid="stat-failed">{stats?.failed ?? 0}</b>
          </Text>
          <Text size="sm">
            Accuracy <b data-testid="stat-accuracy">{accuracy}</b>
          </Text>
          {stats != null && stats.misclicks > 0 && (
            <Text size="sm" c="dimmed" title="Misses you tagged Misclick: left out of your accuracy here" data-testid="stat-misclicks">
              {stats.misclicks} {stats.misclicks === 1 ? "misclick" : "misclicks"}
            </Text>
          )}
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
