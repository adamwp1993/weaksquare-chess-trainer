// FR-10.64: a day's tasks as checkboxes, shared by the Coach's Plan tab and the Today's plan card, so a tick in one
// shows in the other. The boxes tick themselves from what the app saw, and a hand choice always wins (the backend's
// rule): this component only shows the state it's given and reloads after every change.
import { Alert, Badge, Button, Checkbox, Group, Menu, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { api } from "../api";
import type { PlanDay, PlanTask } from "../api/types";

const STATUS: Record<string, { label: string; color: string } | null> = {
  left: null,
  done: null,
  skipped: { label: "Skipped", color: "gray" },
  carried: { label: "Moved to the next day", color: "gray" },
  missed: { label: "Missed", color: "orange" },
};

function TaskRow({
  t,
  readOnly,
  onChanged,
  onStart,
  onError,
}: {
  t: PlanTask;
  readOnly: boolean;
  onChanged: () => void;
  onStart: (t: PlanTask) => void;
  onError: (m: string) => void;
}) {
  const run = (p: Promise<unknown>) => p.then(onChanged, (e: Error) => onError(e.message));
  const done = t.status === "done";
  const skipped = t.status === "skipped";
  const badge = STATUS[t.status];
  const canAct = !readOnly && !done && t.status !== "carried";
  return (
    <Group justify="space-between" wrap="nowrap" gap="xs" data-testid={`plan-task-${t.id}`} data-status={t.status}>
      <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
        <Checkbox
          aria-label={t.title}
          checked={done}
          disabled={readOnly}
          data-no-tip="a task's own checkbox: its label is the task"
          onChange={(e) => run(api.setPlanTaskTick(t.id, e.currentTarget.checked))}
          data-testid={`plan-tick-${t.id}`}
        />
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="sm" td={skipped ? "line-through" : undefined} c={skipped ? "dimmed" : undefined} style={{ overflowWrap: "anywhere" }}>
            {t.title}
          </Text>
          <Group gap={6}>
            <Text size="xs" c="dimmed">
              {t.minutes} min
              {t.count !== null ? ` · ${Math.min(t.progress ?? 0, t.count)} of ${t.count}` : ""}
              {done && t.manual === "done" && !t.auto ? " · ticked by hand" : ""}
              {t.manual === "undone" && t.auto ? " · unticked by you" : ""}
              {t.carried ? " · carried over" : ""}
            </Text>
            {badge && (
              <Badge size="xs" variant="light" color={badge.color}>
                {badge.label}
              </Badge>
            )}
          </Group>
        </Stack>
      </Group>
      {canAct && (
        <Group gap={4} wrap="nowrap">
          {!skipped && (
            <Button size="compact-xs" onClick={() => onStart(t)} data-testid={`plan-start-${t.id}`}>
              Start
            </Button>
          )}
          <Menu position="bottom-end">
            <Menu.Target>
              <Button size="compact-xs" variant="subtle" aria-label={`More for ${t.title}`} data-testid={`plan-more-${t.id}`}>
                ⋯
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={() => run(api.skipPlanTask(t.id, !skipped))} data-testid={`plan-skip-${t.id}`}>
                {skipped ? "Don't skip" : "Skip"}
              </Menu.Item>
              {!skipped && (
                <Menu.Item onClick={() => run(api.swapPlanTask(t.id))} data-testid={`plan-swap-${t.id}`}>
                  Swap for another task
                </Menu.Item>
              )}
            </Menu.Dropdown>
          </Menu>
        </Group>
      )}
    </Group>
  );
}

export function PlanChecklist({
  day,
  readOnly = false,
  onChanged,
  onStart,
}: {
  day: PlanDay;
  readOnly?: boolean;
  onChanged: () => void;
  onStart: (t: PlanTask) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  return (
    <Stack gap={6} data-testid={`plan-day-${day.id}`}>
      {day.tasks.map((t) => (
        <TaskRow
          key={t.id}
          t={t}
          readOnly={readOnly}
          onChanged={() => {
            setError(null);
            onChanged();
          }}
          onStart={onStart}
          onError={setError}
        />
      ))}
      {error && (
        <Alert color="red" p="xs" data-testid="plan-error">
          {error}
        </Alert>
      )}
    </Stack>
  );
}

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

/** "Thu, 5 Nov" from a calendar date. Formatted as UTC so a calendar date stays that date everywhere. */
export function dayLabel(iso: string): string {
  return DATE_FORMAT.format(new Date(`${iso}T12:00:00Z`));
}
