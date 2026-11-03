import { Badge, Button, Group, MultiSelect, Paper, Stack, Text } from "@mantine/core";
import { useState } from "react";
import type { IdeaResult as IdeaResultData } from "../api/types";
import { IDEA_PAYOFF, IDEA_SETUP, MAX_TAGS_PER_SLOT } from "../state/ideas";

// Name the idea first (FR-4.3): tag the idea before you move, then see how your tags compared.

const options = (list: [string, string][]) => list.map(([value, label]) => ({ value, label }));

export function IdeaTags({ busy, onStart }: { busy: boolean; onStart: (setup: string[], payoff: string[]) => void }) {
  const [setup, setSetup] = useState<string[]>([]);
  const [payoff, setPayoff] = useState<string[]>([]);
  const none = setup.length + payoff.length === 0;
  return (
    <Paper withBorder p="sm" radius="md" data-testid="idea-tags">
      <Stack gap={8}>
        <Text size="sm" fw={600}>
          Name the idea
        </Text>
        <MultiSelect
          label="Setup"
          description="How you get there: deflect, attract, clear a line…"
          placeholder={setup.length ? undefined : "Pick up to 3"}
          data={options(IDEA_SETUP)}
          value={setup}
          onChange={setSetup}
          maxValues={MAX_TAGS_PER_SLOT}
          searchable
          clearable
          comboboxProps={{ withinPortal: true }}
          data-testid="idea-setup"
        />
        <MultiSelect
          label="Payoff"
          description="What it wins: a fork, a pin, a mate pattern…"
          placeholder={payoff.length ? undefined : "Pick up to 3"}
          data={options(IDEA_PAYOFF)}
          value={payoff}
          onChange={setPayoff}
          maxValues={MAX_TAGS_PER_SLOT}
          searchable
          clearable
          comboboxProps={{ withinPortal: true }}
          data-testid="idea-payoff"
        />
        <Button size="sm" disabled={none || busy} onClick={() => onStart(setup, payoff)} data-testid="idea-start">
          Start solving
        </Button>
        <Text size="xs" c="dimmed">
          A tag counts whichever box it's in. Your tags are checked against the puzzle's themes after it ends.
        </Text>
      </Stack>
    </Paper>
  );
}

export function IdeaResult({ idea }: { idea: IdeaResultData }) {
  if (idea.total === 0) {
    return (
      <Text size="sm" c="dimmed" data-testid="idea-result">
        This puzzle has no motif themes, so your tags weren't scored.
      </Text>
    );
  }
  return (
    <Stack gap={4} data-testid="idea-result">
      <Text size="sm" fw={600}>
        Ideas found {idea.found} of {idea.total}
        {idea.extra > 0 ? ` · ${idea.extra} extra` : ""}
      </Text>
      <Group gap={4}>
        {idea.correct.map((t) => (
          <Badge key={t.key} color="green" variant="light" style={{ textTransform: "none" }}>
            ✓ {t.name}
          </Badge>
        ))}
        {idea.wrong.map((t) => (
          <Badge key={t.key} color="red" variant="light" style={{ textTransform: "none" }}>
            ✗ {t.name}
          </Badge>
        ))}
      </Group>
      {idea.missed.length > 0 && (
        <Text size="xs" c="dimmed" data-testid="idea-missed">
          Missed: {idea.missed.map((t) => t.name).join(", ")}
        </Text>
      )}
    </Stack>
  );
}
