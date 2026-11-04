// v0.10 The Suggested mix on the main page (FR-10.28–10.31): its label and "Why this mix" while your
// filters are the suggestion, and the Apply / Compare / Dismiss banner when a new one waits because you
// changed your filters by hand. Nothing here replaces your filters unless you click Apply.
import { Alert, Button, Collapse, Grid, Group, Modal, Paper, Stack, Text } from "@mantine/core";
import { useState } from "react";
import type { TrainingMode } from "../api/ApiClient";
import type { FilterSpec, SuggestionView, ThemeGroup } from "../api/types";
import { filtersSummary } from "../views/MixerView";

function describe(spec: Record<string, unknown> | null, mode: TrainingMode, catalog: ThemeGroup[]): string {
  if (!spec) return "The default mix";
  return filtersSummary(spec as unknown as FilterSpec, mode, null, null, catalog);
}

export function SuggestionBanner({
  suggestion,
  currentMode,
  catalog,
  onApply,
  onDismiss,
}: {
  suggestion: SuggestionView | null;
  currentMode: TrainingMode;
  catalog: ThemeGroup[];
  onApply: () => void;
  onDismiss: () => void;
}) {
  const [why, setWhy] = useState(false);
  const [compare, setCompare] = useState(false);
  if (!suggestion) return null;
  const s = suggestion;
  const whyLines = (
    <Stack gap={2} data-testid="suggestion-why">
      {s.why.map((line, i) => (
        <Text key={i} size="xs">
          {line}
        </Text>
      ))}
    </Stack>
  );
  if (s.pending) {
    return (
      <>
        <Alert color="indigo" data-testid="suggestion-banner">
          <Group justify="space-between">
            <Text size="sm">New suggested mix from Coach run #{s.number}.</Text>
            <Group gap="xs">
              <Button size="xs" onClick={onApply} data-testid="suggestion-apply">
                Apply
              </Button>
              <Button size="xs" variant="default" onClick={() => setCompare(true)} data-testid="suggestion-compare">
                Compare
              </Button>
              <Button size="xs" variant="subtle" onClick={onDismiss} data-testid="suggestion-dismiss">
                Dismiss
              </Button>
            </Group>
          </Group>
        </Alert>
        <Modal opened={compare} onClose={() => setCompare(false)} title="Your filters and the suggested mix" size="lg" data-testid="suggestion-compare-modal">
          <Grid>
            <Grid.Col span={6}>
              <Paper withBorder p="sm" h="100%">
                <Text fw={600} size="sm" mb={4}>
                  Yours now
                </Text>
                <Text size="sm" data-testid="compare-current">
                  {describe(s.previous, currentMode, catalog)}
                </Text>
              </Paper>
            </Grid.Col>
            <Grid.Col span={6}>
              <Paper withBorder p="sm" h="100%">
                <Text fw={600} size="sm" mb={4}>
                  Suggested
                </Text>
                <Text size="sm" mb="xs" data-testid="compare-suggested">
                  {describe(s.spec, s.mode as TrainingMode, catalog)}
                </Text>
                {whyLines}
              </Paper>
            </Grid.Col>
          </Grid>
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={() => setCompare(false)}>
              Keep mine
            </Button>
            <Button
              onClick={() => {
                setCompare(false);
                onApply();
              }}
            >
              Apply the suggestion
            </Button>
          </Group>
        </Modal>
      </>
    );
  }
  if (!s.active) return null;
  return (
    <Paper withBorder p="xs" data-testid="suggestion-label">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" fw={600}>
          {s.label}
        </Text>
        <Button size="compact-xs" variant="subtle" onClick={() => setWhy((v) => !v)} data-testid="suggestion-why-toggle">
          Why this mix
        </Button>
      </Group>
      <Collapse expanded={why}>{whyLines}</Collapse>
    </Paper>
  );
}
