import { Checkbox, Group, NumberInput, RangeSlider, SegmentedControl, Stack, Switch, Text } from "@mantine/core";
import { LENGTH_OPTIONS } from "../state/filters";

// FR-3.3: two-handle slider plus numeric min/max. `null` means "the dataset's bound".
export function RatingSlider({
  bounds,
  min,
  max,
  onChange,
}: {
  bounds: [number, number];
  min: number | null;
  max: number | null;
  onChange: (min: number | null, max: number | null) => void;
}) {
  const [lo, hi] = bounds;
  const vmin = min ?? lo;
  const vmax = max ?? hi;
  const emit = (a: number, b: number) => onChange(a <= lo ? null : a, b >= hi ? null : b);
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Rating
      </Text>
      <RangeSlider
        min={lo}
        max={hi}
        step={25}
        minRange={0}
        value={[vmin, vmax]}
        onChange={([a, b]) => emit(a, b)}
        label={null}
        aria-label="Rating range"
      />
      <Group grow gap="xs">
        <NumberInput
          aria-label="Minimum rating"
          size="xs"
          min={lo}
          max={vmax}
          value={vmin}
          onChange={(v) => typeof v === "number" && emit(Math.min(Math.max(v, lo), vmax), vmax)}
        />
        <NumberInput
          aria-label="Maximum rating"
          size="xs"
          min={vmin}
          max={hi}
          value={vmax}
          onChange={(v) => typeof v === "number" && emit(vmin, Math.max(Math.min(v, hi), vmin))}
        />
      </Group>
    </Stack>
  );
}

// FR-3.4: 1 / 2 / 3 / 4+ and All (an empty list means All).
export function MoveCountSelect({ value, onChange }: { value: number[]; onChange: (lengths: number[]) => void }) {
  const all = value.length === 0 || value.length === LENGTH_OPTIONS.length;
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Number of moves
      </Text>
      <Group gap="sm">
        <Checkbox label="All" checked={all} onChange={() => onChange([])} aria-label="All lengths" />
        {LENGTH_OPTIONS.map((o) => (
          <Checkbox
            key={o.value}
            label={o.label}
            aria-label={`${o.label} moves`}
            checked={!all && value.includes(o.value)}
            onChange={(e) => {
              const base = all ? [] : value;
              const next = e.currentTarget.checked ? [...base, o.value] : base.filter((x) => x !== o.value);
              onChange(next.length === LENGTH_OPTIONS.length ? [] : next.sort());
            }}
          />
        ))}
      </Group>
    </Stack>
  );
}

// FR-3.5
export function SideSelect({
  value,
  onChange,
}: {
  value: "either" | "white" | "black";
  onChange: (side: "either" | "white" | "black") => void;
}) {
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        You play
      </Text>
      <SegmentedControl
        size="xs"
        value={value}
        onChange={(v) => onChange(v as "either" | "white" | "black")}
        data={[
          { value: "either", label: "Either" },
          { value: "white", label: "White" },
          { value: "black", label: "Black" },
        ]}
      />
    </Stack>
  );
}

// FR-3.12: a fixed number of puzzles, or endless.
export function QueueControls({ value, onChange }: { value: number | null; onChange: (size: number | null) => void }) {
  const endless = value === null;
  return (
    <Group align="end" gap="sm">
      <NumberInput
        label="Puzzles"
        size="xs"
        w={100}
        min={1}
        max={500}
        disabled={endless}
        value={value ?? 20}
        onChange={(v) => typeof v === "number" && v >= 1 && v <= 500 && onChange(v)}
      />
      <Switch label="Endless" checked={endless} onChange={(e) => onChange(e.currentTarget.checked ? null : 20)} mb={6} />
    </Group>
  );
}
