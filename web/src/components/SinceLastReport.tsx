// FR-10.73: how this report compares with your earlier ones. It only ever says "better" or "worse" where the backend's
// guards allow it (5 games in the group, 5 new games); otherwise it says there aren't enough new games yet.
import { Alert, Badge, Stack, Table, Text, Title } from "@mantine/core";
import type { CoachComparison, CoachMeasureChange, CoachWeaknessChange } from "../api/types";

const VERDICT: Record<string, { text: string; color: string }> = {
  better: { text: "better", color: "green" },
  worse: { text: "worse", color: "red" },
  same: { text: "no change", color: "gray" },
  not_enough: { text: "not enough new games yet", color: "gray" },
};

function Verdict({ v, attempts }: { v: string; attempts?: boolean }) {
  const shown = VERDICT[v] ?? VERDICT.same;
  const text = v === "not_enough" && attempts ? "not enough attempts yet" : shown.text;
  return (
    <Text size="xs" c={shown.color === "gray" ? "dimmed" : shown.color} data-verdict={v}>
      {text}
    </Text>
  );
}

function num(x: number | null | undefined, unit: string): string {
  if (x === null || x === undefined) return "—";
  return unit === "pct" ? `${x}%` : String(x);
}

function WeaknessRow({ w, unit, trend }: { w: CoachWeaknessChange; unit: string; trend: boolean }) {
  const series = w.series.map((x) => num(x, unit)).join(" → ");
  return (
    <Table.Tr data-testid={`since-${w.key}`}>
      <Table.Td>
        <Text size="sm" span>
          {w.label}
        </Text>{" "}
        {w.flag === "new" && (
          <Badge size="xs" color="orange" variant="light" data-testid={`since-new-${w.key}`}>
            New
          </Badge>
        )}
        {w.flag === "gone" && (
          <Badge size="xs" color="teal" variant="light" data-testid={`since-gone-${w.key}`}>
            Gone
          </Badge>
        )}
      </Table.Td>
      <Table.Td ta="right">{num(w.then, unit)}</Table.Td>
      <Table.Td ta="right">{num(w.now, unit)}</Table.Td>
      <Table.Td>
        {w.flag === "new" ? (
          <Text size="xs" c="dimmed">
            new in this report
          </Text>
        ) : w.flag === "gone" && w.now === null ? (
          <Text size="xs" c="dimmed" data-testid={`since-out-${w.key}`}>
            no longer in the top list
          </Text>
        ) : (
          <Verdict v={w.verdict} />
        )}
      </Table.Td>
      {trend && (
        <Table.Td>
          <Text size="xs" c="dimmed">
            {series}
          </Text>
        </Table.Td>
      )}
      <Table.Td>
        {w.puzzle ? (
          <Stack gap={0}>
            <Text size="xs">
              {num(w.puzzle.then, "pct")} → {num(w.puzzle.now, "pct")}
            </Text>
            <Verdict v={w.puzzle.verdict} attempts />
          </Stack>
        ) : (
          <Text size="xs" c="dimmed">
            —
          </Text>
        )}
      </Table.Td>
    </Table.Tr>
  );
}

function MeasureRows({ rows }: { rows: CoachMeasureChange[] }) {
  return (
    <>
      {rows.map((m) => (
        <Table.Tr key={m.key} data-testid={`since-${m.key}`}>
          <Table.Td>
            <Text size="sm">{m.label}</Text>
          </Table.Td>
          <Table.Td ta="right">{num(m.then, m.unit)}</Table.Td>
          <Table.Td ta="right">{num(m.now, m.unit)}</Table.Td>
          <Table.Td>
            <Verdict v={m.verdict} />
          </Table.Td>
        </Table.Tr>
      ))}
    </>
  );
}

export function SinceLastReport({ c }: { c: CoachComparison }) {
  const unit = c.puzzle_history ? "pct" : "per10";
  const when = c.days_between === 0 ? "earlier today" : `${c.days_between} day${c.days_between === 1 ? "" : "s"} ago`;
  return (
    <Stack gap="xs" data-testid="since-last-report">
      <Title order={5}>Since last report</Title>
      <Text size="sm" c="dimmed">
        Compared with your report from {when}
        {c.puzzle_history
          ? "."
          : `: ${c.new_games} new game${c.new_games === 1 ? "" : "s"}${c.shared_games ? `, ${c.shared_games} game${c.shared_games === 1 ? "" : "s"} in both` : ""}.`}
      </Text>
      {!c.puzzle_history && !c.enough_new_games && (
        <Alert color="gray" p="xs" data-testid="since-not-enough">
          Not enough new games yet: a change is called better or worse once 5 of this report's games weren't in the last one.
        </Alert>
      )}
      {c.settings === "different" && (
        <Alert color="yellow" p="xs" data-testid="since-settings">
          These two reports used different analysis settings (think time or thresholds), so their rates aren't directly comparable.
        </Alert>
      )}
      {c.settings === "unknown" && (
        <Text size="xs" c="dimmed" data-testid="since-settings-unknown">
          The earlier report didn't record its analysis settings, so we can't tell whether they match.
        </Text>
      )}
      <Table withTableBorder striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Weakness</Table.Th>
            <Table.Th ta="right">{c.puzzle_history ? "First try, then" : "Per 10 games, then"}</Table.Th>
            <Table.Th ta="right">Now</Table.Th>
            <Table.Th>Change</Table.Th>
            {c.reports > 2 && <Table.Th>Last {c.reports} reports</Table.Th>}
            <Table.Th>Puzzles on its themes</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {c.weaknesses.map((w) => (
            <WeaknessRow key={w.key} w={w} unit={unit} trend={c.reports > 2} />
          ))}
        </Table.Tbody>
      </Table>
      {c.health.length + c.measures.length > 0 && (
        <Table withTableBorder data-testid="since-measures">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Overall</Table.Th>
              <Table.Th ta="right">Then</Table.Th>
              <Table.Th ta="right">Now</Table.Th>
              <Table.Th>Change</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            <MeasureRows rows={c.health} />
            <MeasureRows rows={c.measures} />
          </Table.Tbody>
        </Table>
      )}
      <Text size="xs" c="dimmed">
        This describes the change. It doesn't decide whether a weakness is fixed.
      </Text>
    </Stack>
  );
}
