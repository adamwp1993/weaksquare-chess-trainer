// FR-10.65: the Today's plan card on the main page. It appears only when a plan exists, and shrinks to one line while a
// session runs so the board keeps its room.
import { Anchor, Button, Group, Paper, Stack, Text } from "@mantine/core";
import { useState } from "react";
import type { PlanTask, TodayPlan } from "../api/types";
import { PlanChecklist, dayLabel } from "./PlanChecklist";

export function TodayCard({
  today,
  compact,
  onChanged,
  onStart,
  onOpenPlan,
}: {
  today: TodayPlan;
  compact: boolean; // a session is running
  onChanged: () => void;
  onStart: (t: PlanTask) => void;
  onOpenPlan: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { day } = today;
  const tasks = day?.tasks ?? [];
  const done = tasks.filter((t) => t.status === "done").length;
  const counted = tasks.filter((t) => t.status !== "skipped").length;
  const expanded = !compact || open;
  return (
    <Paper withBorder p="sm" data-testid="today-card">
      <Stack gap="xs">
        <Group justify="space-between">
          <Group gap="xs">
            <Text size="sm" fw={600}>
              Today's plan
            </Text>
            {day && (
              <Text size="sm" c="dimmed" data-testid="today-count">
                {done} of {counted} done
              </Text>
            )}
            {!day && !today.finished && today.next_date && (
              <Text size="sm" c="dimmed" data-testid="today-rest">
                Rest day. Next training day: {dayLabel(today.next_date)}
              </Text>
            )}
            {today.finished && (
              <Text size="sm" c="dimmed" data-testid="today-finished">
                Your plan has finished.
              </Text>
            )}
          </Group>
          <Group gap="xs">
            {compact && day && (
              <Button size="compact-xs" variant="subtle" onClick={() => setOpen(!open)} data-testid="today-toggle">
                {open ? "Hide" : "Show"}
              </Button>
            )}
            <Anchor size="xs" component="button" onClick={onOpenPlan} data-testid="today-open-plan">
              {today.finished ? "Build the next one" : "Open the plan"}
            </Anchor>
          </Group>
        </Group>
        {day && expanded && <PlanChecklist day={day} onChanged={onChanged} onStart={onStart} />}
      </Stack>
    </Paper>
  );
}
