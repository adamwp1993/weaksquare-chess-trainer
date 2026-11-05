// v0.11 Whole-game measures (FR-10.53): free, from your games' digests. Every group with fewer than 5
// games says "not enough data yet" and never becomes a weakness.
import { Badge, Group, Paper, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import type { CoachMeasures } from "../api/types";

function Thin({ enough }: { enough: boolean }) {
  return enough ? null : (
    <Badge size="xs" variant="light" color="gray" data-testid="not-enough">
      not enough data yet
    </Badge>
  );
}

const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x)}%`);
const pawns = (cp: number | null) => (cp === null ? "—" : `${cp > 0 ? "+" : ""}${(cp / 100).toFixed(1)}`);

export function WholeGameMeasures({ m }: { m: CoachMeasures }) {
  const t = m.time;
  const k = m.king;
  return (
    <Stack gap="xs" data-testid="coach-measures">
      <Title order={5}>Whole-game measures</Title>
      <Text size="xs" c="dimmed">
        From {m.games} games, worked out on your PC. A group needs at least {m.min_games} games before it counts.
      </Text>
      {m.openings.length > 0 && (
        <Table withTableBorder striped data-testid="measures-openings">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Opening</Table.Th>
              <Table.Th ta="right">Games</Table.Th>
              <Table.Th ta="right">Your score</Table.Th>
              <Table.Th ta="right">Eval at move 15</Table.Th>
              <Table.Th ta="right">Mistakes in moves 1–15</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {m.openings.map((o) => (
              <Table.Tr key={o.family}>
                <Table.Td>
                  <Group gap={6}>
                    {o.family}
                    <Thin enough={o.enough} />
                  </Group>
                </Table.Td>
                <Table.Td ta="right">{o.games}</Table.Td>
                <Table.Td ta="right">{pct(o.score)}</Table.Td>
                <Table.Td ta="right">{pawns(o.avg_eval_end)}</Table.Td>
                <Table.Td ta="right">{o.errors_first15}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
        <Paper withBorder p="xs" data-testid="measures-phases">
          <Text size="sm" fw={600}>
            Phases and conversion
          </Text>
          <Text size="sm">
            Mistakes per 10 games: opening {m.errors_per10_by_phase.opening ?? 0}, middlegame {m.errors_per10_by_phase.middlegame ?? 0},
            endgame {m.errors_per10_by_phase.endgame ?? 0}
          </Text>
          <Group gap={6}>
            <Text size="sm">
              Won from +2 or better: {pct(m.conversion.rate)} of {m.conversion.games}
            </Text>
            <Thin enough={m.conversion.enough} />
          </Group>
          <Group gap={6}>
            <Text size="sm">
              Saved from −2 or worse: {pct(m.saves.rate)} of {m.saves.games}
            </Text>
            <Thin enough={m.saves.enough} />
          </Group>
        </Paper>
        <Paper withBorder p="xs" data-testid="measures-time">
          <Group gap={6}>
            <Text size="sm" fw={600}>
              Time use
            </Text>
            <Thin enough={t.enough} />
          </Group>
          {t.games === 0 ? (
            <Text size="sm" c="dimmed">
              No clock data in these games.
            </Text>
          ) : (
            <Text size="sm">
              Under 10% of your clock: {t.low_error_rate ?? "—"} mistakes per 100 moves ({t.low_blunders} blunders). The rest of the
              game: {t.other_error_rate ?? "—"} per 100 moves.
            </Text>
          )}
        </Paper>
        <Paper withBorder p="xs" data-testid="measures-king">
          <Group gap={6}>
            <Text size="sm" fw={600}>
              King safety and development
            </Text>
            <Thin enough={k.enough} />
          </Group>
          <Text size="sm">
            Castled after move 12 or never: {k.late} of {k.games} games. Your score then {pct(k.late_score)}, otherwise{" "}
            {pct(k.on_time_score)}.
          </Text>
        </Paper>
        {m.endgames.length > 0 && (
          <Paper withBorder p="xs" data-testid="measures-endgames">
            <Text size="sm" fw={600}>
              Endgames
            </Text>
            {m.endgames.map((e) => (
              <Group key={e.type} gap={6}>
                <Text size="sm">
                  {e.label}: {e.games} games, +{e.wins} ={e.draws} −{e.losses}, {e.errors} mistakes
                </Text>
                <Thin enough={e.enough} />
              </Group>
            ))}
          </Paper>
        )}
      </SimpleGrid>
    </Stack>
  );
}
