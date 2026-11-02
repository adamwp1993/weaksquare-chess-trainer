import { ActionIcon, Button, Group, NumberInput, Paper, Stack, Text } from "@mantine/core";
import type { RatioBucket, ThemeGroup } from "../api/types";
import { ThemePicker } from "./ThemePicker";

const MAX_GROUPS = 10;

// Split weights as evenly as whole percentages allow, e.g. 3 groups -> 34/33/33.
export function evenSplit(n: number): number[] {
  return Array.from({ length: n }, (_, i) => Math.floor(100 / n) + (i < 100 % n ? 1 : 0));
}

// FR-3.10: weighted groups of themes, e.g. 50% fork, 30% pin or skewer, 20% one-move.
// Each group's live count comes from `counts` (same order); a group with no puzzles is left out.
export function RatioEditor({
  catalog,
  ratios,
  counts,
  onChange,
}: {
  catalog: ThemeGroup[];
  ratios: RatioBucket[];
  counts: number[] | null;
  onChange: (ratios: RatioBucket[]) => void;
}) {
  const total = ratios.reduce((a, b) => a + b.weight, 0);
  const update = (i: number, patch: Partial<RatioBucket>) =>
    onChange(ratios.map((b, j) => (j === i ? { ...b, ...patch } : b)));

  return (
    <Stack gap="xs" data-testid="ratio-editor">
      {ratios.map((b, i) => {
        const n = counts?.[i];
        return (
          <Paper key={i} withBorder p="xs" radius="sm" data-testid={`ratio-group-${i}`}>
            <Stack gap={6}>
              <Group justify="space-between" align="end" wrap="nowrap">
                <NumberInput
                  label={`Group ${i + 1} share`}
                  size="xs"
                  w={110}
                  min={1}
                  max={100}
                  suffix="%"
                  allowDecimal={false}
                  allowNegative={false}
                  value={b.weight}
                  onChange={(v) => typeof v === "number" && update(i, { weight: v })}
                  data-testid={`ratio-weight-${i}`}
                />
                <Text size="xs" c={n === 0 ? "red" : "dimmed"} mb={6} data-testid={`ratio-count-${i}`}>
                  {n == null ? "…" : n === 0 ? "No puzzles: left out" : `${n.toLocaleString("en-US")} puzzles`}
                </Text>
                {ratios.length > 2 && (
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    mb={4}
                    aria-label={`Remove group ${i + 1}`}
                    onClick={() => onChange(ratios.filter((_, j) => j !== i))}
                  >
                    ✕
                  </ActionIcon>
                )}
              </Group>
              <ThemePicker
                label={`Group ${i + 1} themes (any of)`}
                catalog={catalog}
                value={b.themes}
                onChange={(themes) => update(i, { themes })}
                emptyLabel="Choose themes"
                testId={`ratio-themes-${i}`}
              />
            </Stack>
          </Paper>
        );
      })}
      <Group justify="space-between">
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="light"
            disabled={ratios.length >= MAX_GROUPS}
            onClick={() => {
              const weights = evenSplit(ratios.length + 1);
              onChange([...ratios.map((b, i) => ({ ...b, weight: weights[i] })), { themes: [], weight: weights[ratios.length] }]);
            }}
          >
            Add group
          </Button>
          <Button
            size="compact-xs"
            variant="subtle"
            onClick={() => {
              const weights = evenSplit(ratios.length);
              onChange(ratios.map((b, i) => ({ ...b, weight: weights[i] })));
            }}
          >
            Even split
          </Button>
        </Group>
        <Text size="xs" fw={600} c={total === 100 ? undefined : "red"} data-testid="ratio-total">
          Total {total}%
        </Text>
      </Group>
    </Stack>
  );
}
