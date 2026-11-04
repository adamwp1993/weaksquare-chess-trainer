// v0.8 (FR-3.15): the puzzle source (Lichess DB / My puzzles / Both) and the My-puzzles filters.
import { MultiSelect, SegmentedControl, Stack, Text, Tooltip } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { TrainingMode } from "../api/ApiClient";
import type { FilterSpec, PuzzleSet } from "../api/types";
import { TIME_CLASSES, cap } from "../state/games";

const LICHESS_ONLY_MODES: TrainingMode[] = ["name_idea", "danger_spotting"];

export function SourceSelect({ spec, mode, onChange }: { spec: FilterSpec; mode: TrainingMode; onChange: (patch: Partial<FilterSpec>) => void }) {
  const locked = LICHESS_ONLY_MODES.includes(mode);
  const control = (
    <SegmentedControl
      size="xs"
      fullWidth
      disabled={locked}
      value={locked ? "lichess" : spec.source}
      onChange={(v) => {
        const source = v as FilterSpec["source"];
        // Ratios and the other orders need Lichess's ratings and themes (FR-3.15).
        onChange(source === "lichess" ? { source } : { source, ratios: [], order: "random" });
      }}
      data={[
        { value: "lichess", label: "Lichess DB" },
        { value: "my", label: "My puzzles" },
        { value: "both", label: "Both" },
      ]}
      aria-label="Puzzle source"
      data-testid="source-select"
    />
  );
  return (
    <Stack gap={2}>
      <Text size="sm" fw={500}>
        Puzzles from
      </Text>
      {locked ? (
        <Tooltip label="My puzzles work in Standard, Commit the line and Spaced repetition.">
          <div>{control}</div>
        </Tooltip>
      ) : (
        control
      )}
    </Stack>
  );
}

export function MyPuzzlesFilters({ spec, onChange, version }: { spec: FilterSpec; onChange: (patch: Partial<FilterSpec>) => void; version: number }) {
  const [sets, setSets] = useState<PuzzleSet[]>([]);
  useEffect(() => {
    api.listPuzzleSets().then(setSets, () => setSets([]));
  }, [version]);
  return (
    <Stack gap="xs" data-testid="my-puzzles-filters">
      <Text size="sm" fw={500}>
        My puzzles
      </Text>
      <MultiSelect
        size="xs"
        label="Origin"
        placeholder="All"
        data={[
          { value: "manual", label: "Saved from my games" },
          { value: "import", label: "Imported from a file" },
        ]}
        value={spec.my_origins}
        onChange={(my_origins) => onChange({ my_origins })}
      />
      <MultiSelect
        size="xs"
        label="Set"
        placeholder={sets.length ? "All sets" : "No imported sets yet"}
        data={sets.map((s) => ({ value: s.label, label: `${s.label} (${s.count})` }))}
        value={spec.my_sets}
        onChange={(my_sets) => onChange({ my_sets })}
        data-testid="my-sets"
      />
      <MultiSelect
        size="xs"
        label="Missed / Allowed"
        placeholder="Both"
        data={[
          { value: "missed", label: "Missed: you had a tactic" },
          { value: "allowed", label: "Allowed: you let them in" },
        ]}
        value={spec.my_kinds}
        onChange={(my_kinds) => onChange({ my_kinds })}
      />
      <MultiSelect
        size="xs"
        label="Phase"
        placeholder="Any"
        data={["opening", "middlegame", "endgame"].map((p) => ({ value: p, label: cap(p) }))}
        value={spec.my_phases}
        onChange={(my_phases) => onChange({ my_phases })}
      />
      <MultiSelect
        size="xs"
        label="Time control"
        placeholder="Any"
        data={TIME_CLASSES.map((t) => ({ value: t, label: cap(t) }))}
        value={spec.my_time_classes}
        onChange={(my_time_classes) => onChange({ my_time_classes })}
      />
      <Text size="xs" c="dimmed">
        Your puzzles have no rating or themes yet, so those filters apply to Lichess puzzles only.
      </Text>
    </Stack>
  );
}
