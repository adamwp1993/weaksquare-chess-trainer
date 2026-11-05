// FR-10.63: what Start shows for a lesson task: its drill, then its links. Opening one ticks the task (v0.12 planning).
// No URLs reach this screen: the backend builds and opens them (FR-10.59).
import { Alert, Anchor, Button, Group, Modal, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { api } from "../api";
import type { CoachLesson, PlanTaskAction } from "../api/types";

const SITE: Record<string, string> = { youtube: "Search YouTube", chesscom: "Search chess.com", custom: "Search my site" };

export function LessonTaskModal({
  taskId,
  lesson,
  rated,
  onClose,
  onChanged,
  onSession,
}: {
  taskId: number;
  lesson: CoachLesson;
  rated: boolean;
  onClose: () => void;
  onChanged: () => void;
  onSession: (a: PlanTaskAction) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const open = (target: string) =>
    api.openPlanLesson(taskId, target).then(() => {
      onChanged();
      onClose();
    }, (e: Error) => setError(e.message)); // prettier-ignore
  const drill = () =>
    api.startPlanLessonDrill(taskId, rated).then((a) => {
      onChanged();
      onClose();
      onSession(a);
    }, (e: Error) => setError(e.message)); // prettier-ignore
  return (
    <Modal opened onClose={onClose} title={`Lesson: ${lesson.label}`} data-testid="lesson-task-modal">
      <Stack gap="xs">
        {lesson.drill && (
          <Button size="sm" onClick={drill} data-testid="lesson-task-drill">
            Drill it here (use Explain after each one)
          </Button>
        )}
        {lesson.curated.map((title, i) => (
          <Anchor key={i} size="sm" component="button" ta="left" onClick={() => open(`curated:${i}`)} data-testid={`lesson-task-curated-${i}`}>
            {title}
          </Anchor>
        ))}
        <Group gap="md">
          {lesson.sites.map((s) => (
            <Anchor key={s} size="sm" component="button" onClick={() => open(s)} data-testid={`lesson-task-${s}`}>
              {SITE[s]}
            </Anchor>
          ))}
        </Group>
        <Text size="xs" c="dimmed">
          Links open in your default browser. The search words go to the site you click.
        </Text>
        {error && (
          <Alert color="red" p="xs" data-testid="lesson-task-error">
            {error}
          </Alert>
        )}
      </Stack>
    </Modal>
  );
}
