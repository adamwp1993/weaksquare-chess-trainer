// A Coach preset to Load or Save (FR-10.24): the report's mix, an AI preset or a lesson's drill (v0.11).
import { Badge, Button, Group, Paper, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";
import { api } from "../api";
import { ApiCallError, type TrainingMode } from "../api/ApiClient";
import type { CoachPresetView, FilterSpec } from "../api/types";
import { modeLabel } from "../state/modes";

export function PresetBox({
  p,
  testid,
  onLoad,
}: {
  p: CoachPresetView;
  testid: string;
  onLoad: (spec: FilterSpec, mode: TrainingMode) => void;
}) {
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clash, setClash] = useState(false); // Adam, 2026-11-04: a name you already use: replace it or pick another
  const [name, setName] = useState(p.name);
  const spec = p.spec as unknown as FilterSpec;
  const save = (as: string, overwrite: boolean) => {
    setError(null);
    api.savePreset(as, spec, overwrite).then(
      () => {
        setClash(false);
        setSaved(`Saved as “${as.trim()}”.`);
      },
      (e: Error) => {
        setClash(e instanceof ApiCallError && e.code === "conflict");
        setError(e.message);
      },
    );
  };
  return (
    <Paper withBorder p="sm" data-testid={testid}>
      <Stack gap={6}>
        <Group justify="space-between">
          <Text fw={600} size="sm">
            {p.name}
          </Text>
          <Badge variant="light">{modeLabel(p.mode as TrainingMode)}</Badge>
        </Group>
        {p.why.length > 0 && (
          <Stack gap={2} data-testid={`${testid}-why`}>
            {p.why.map((line, i) => (
              <Text key={i} size="xs">
                {line}
              </Text>
            ))}
          </Stack>
        )}
        <Group gap="xs">
          <Button size="xs" onClick={() => onLoad(spec, p.mode as TrainingMode)} data-testid={`${testid}-load`}>
            Load preset
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={() => save(name, false)}
            data-testid={`${testid}-save`}
          >
            Save as preset
          </Button>
        </Group>
        {saved && <Text size="xs" c="dimmed">{saved}</Text>}
        {error && <Text size="xs" c={clash ? "yellow.8" : "red"}>{error}</Text>}
        {clash && (
          <Group gap="xs" align="end" data-testid={`${testid}-clash`}>
            <Button size="xs" color="yellow" onClick={() => save(name, true)} data-testid={`${testid}-replace`}>
              Replace it
            </Button>
            <TextInput size="xs" label="Or save as" value={name} maxLength={60} onChange={(e) => setName(e.currentTarget.value)} data-testid={`${testid}-name`} />
            <Button size="xs" variant="default" onClick={() => save(name, false)} data-testid={`${testid}-save-as`}>
              Save
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
