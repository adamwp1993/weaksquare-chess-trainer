import {
  Checkbox,
  Group,
  MultiSelect,
  NumberInput,
  RangeSlider,
  SegmentedControl,
  Stack,
  Switch,
  Text,
} from "@mantine/core";
import { useMemo, useState } from "react";
import type { OpeningFamily } from "../api/types";
import { LENGTH_OPTIONS } from "../state/filters";

// A number box that only commits on blur or Enter, so typing "1600" isn't clamped keystroke by
// keystroke (v0.1-B3). Re-mounted (via `key`) whenever the committed value changes elsewhere.
function CommitNumberInput({
  label,
  value,
  min,
  max,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState<string | number>(value);
  const commit = () => {
    const n = typeof draft === "number" ? draft : Number.parseInt(draft, 10);
    if (Number.isFinite(n)) onCommit(Math.min(Math.max(Math.round(n), min), max));
    else setDraft(value);
  };
  return (
    <NumberInput
      aria-label={label}
      size="xs"
      value={draft}
      allowDecimal={false}
      allowNegative={false}
      onChange={setDraft}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
    />
  );
}

// FR-3.3: two-handle slider plus numeric min/max. `null` means "the dataset's bound".
// Typed values commit on blur or Enter and are clamped to the bounds then.
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
        <CommitNumberInput
          key={`min-${vmin}`}
          label="Minimum rating"
          value={vmin}
          min={lo}
          max={hi}
          onCommit={(a) => emit(a, Math.max(a, vmax))}
        />
        <CommitNumberInput
          key={`max-${vmax}`}
          label="Maximum rating"
          value={vmax}
          min={lo}
          max={hi}
          onCommit={(b) => emit(Math.min(vmin, b), b)}
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

// A number box for an optional threshold: commits on blur or Enter; an empty box means "off".
function OptionalNumberInput({
  label,
  value,
  min,
  max,
  placeholder,
  testId,
  onCommit,
}: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  placeholder: string;
  testId: string;
  onCommit: (v: number | null) => void;
}) {
  const [draft, setDraft] = useState<string | number>(value ?? "");
  const commit = () => {
    if (draft === "" || draft === "-") {
      onCommit(null);
      return;
    }
    const n = typeof draft === "number" ? draft : Number.parseInt(draft, 10);
    if (Number.isFinite(n)) onCommit(Math.min(Math.max(Math.round(n), min), max));
    else setDraft(value ?? "");
  };
  return (
    <NumberInput
      label={label}
      size="xs"
      value={draft}
      min={min}
      max={max}
      allowDecimal={false}
      allowNegative={min < 0}
      placeholder={placeholder}
      onChange={setDraft}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      data-testid={testId}
    />
  );
}

// FR-3.8: on by default (popularity >= 50, >= 100 plays); clear a box to turn that threshold off.
export function QualityControls({
  minPopularity,
  minPlays,
  onChange,
}: {
  minPopularity: number | null;
  minPlays: number | null;
  onChange: (minPopularity: number | null, minPlays: number | null) => void;
}) {
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Quality
      </Text>
      <Group grow gap="xs" align="start">
        <OptionalNumberInput
          key={`pop-${minPopularity}`}
          label="Min popularity"
          value={minPopularity}
          min={-100}
          max={100}
          placeholder="Off"
          testId="min-popularity"
          onCommit={(v) => onChange(v, minPlays)}
        />
        <OptionalNumberInput
          key={`plays-${minPlays}`}
          label="Min plays"
          value={minPlays}
          min={0}
          max={10_000_000}
          placeholder="Off"
          testId="min-plays"
          onCommit={(v) => onChange(minPopularity, v)}
        />
      </Group>
      <Text size="xs" c="dimmed">
        Popularity is Lichess players' votes, from -100 to 100. Leave a box empty to turn it off.
      </Text>
    </Stack>
  );
}

// FR-3.9 (Exclude played on Lichess arrives with the Lichess sign-in in v0.3).
export function HistoryControls({
  excludeSolved,
  onlyMisses,
  onChange,
}: {
  excludeSolved: boolean;
  onlyMisses: boolean;
  onChange: (excludeSolved: boolean, onlyMisses: boolean) => void;
}) {
  return (
    <Stack gap={6}>
      <Text size="sm" fw={500}>
        Your history
      </Text>
      <Checkbox
        size="xs"
        label="Exclude solved here"
        description={onlyMisses ? "Not needed while Only my misses is on." : "Puzzles you only failed can still come up."}
        checked={excludeSolved && !onlyMisses}
        disabled={onlyMisses}
        onChange={(e) => onChange(e.currentTarget.checked, onlyMisses)}
        data-testid="exclude-solved"
      />
      <Checkbox
        size="xs"
        label="Only my misses"
        description="Puzzles whose last attempt here was a fail."
        checked={onlyMisses}
        onChange={(e) => onChange(excludeSolved, e.currentTarget.checked)}
        data-testid="only-misses"
      />
    </Stack>
  );
}

// FR-3.7: openings from OpeningTags, grouped by family, searchable.
export function OpeningSelect({
  catalog,
  value,
  onChange,
}: {
  catalog: OpeningFamily[];
  value: string[];
  onChange: (openings: string[]) => void;
}) {
  const { data, counts } = useMemo(() => {
    const counts = new Map<string, number>();
    const data = catalog.map((f) => {
      counts.set(f.family.tag, f.family.count);
      f.variations.forEach((v) => counts.set(v.tag, v.count));
      return {
        group: f.family.name,
        items: [
          { value: f.family.tag, label: `${f.family.name} (any variation)` },
          ...f.variations.map((v) => ({ value: v.tag, label: `${f.family.name}: ${v.name}` })),
        ],
      };
    });
    return { data, counts };
  }, [catalog]);
  return (
    <MultiSelect
      label="Openings"
      size="xs"
      placeholder={value.length === 0 ? "Any opening" : undefined}
      data={data}
      value={value}
      onChange={onChange}
      searchable
      clearable
      limit={200}
      maxDropdownHeight={300}
      nothingFoundMessage="No opening matches"
      renderOption={({ option }) => (
        <Group gap={6} wrap="nowrap" justify="space-between" w="100%">
          <span>{option.label}</span>
          <Text span size="xs" c="dimmed">
            {(counts.get(option.value) ?? 0).toLocaleString("en-US")}
          </Text>
        </Group>
      )}
      description="Only puzzles from the first 20 moves have an opening."
      data-testid="openings-select"
    />
  );
}

export type Order = "random" | "easy_to_hard" | "by_theme";

// FR-3.11
export function OrderSelect({ value, endless, onChange }: { value: Order; endless: boolean; onChange: (o: Order) => void }) {
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Order
      </Text>
      <SegmentedControl
        size="xs"
        value={value}
        onChange={(v) => onChange(v as Order)}
        data={[
          { value: "random", label: "Random" },
          { value: "easy_to_hard", label: "Easy → hard" },
          { value: "by_theme", label: "By theme" },
        ]}
        aria-label="Order"
      />
      {endless && value !== "random" && (
        <Text size="xs" c="dimmed" data-testid="order-endless-note">
          With Endless, each block of 50 puzzles is sorted.
        </Text>
      )}
    </Stack>
  );
}
