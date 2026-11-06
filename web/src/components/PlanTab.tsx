// FR-10.61-10.65: the Coach's Plan tab. Your settings, a preview before anything is saved, and each week and day as
// checklists with today opened. A new plan replaces the current one only when you confirm, and old plans stay as
// history with their completion. All text from the backend is plain React text.
import { Accordion, Alert, Badge, Button, Chip, Group, Modal, NumberInput, Paper, Select, Stack, Switch, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { PlanParams } from "../api/ApiClient";
import type { PlanPreview, PlanSettings, PlanTask, TrainingPlan } from "../api/types";
import { Labeled, OptionInfo } from "./OptionInfo";
import { PlanChecklist, dayLabel } from "./PlanChecklist";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const STATUS_TEXT: Record<string, string> = { current: "Current", replaced: "Ended" };

function Totals({ p }: { p: TrainingPlan }) {
  return (
    <Text size="sm" c="dimmed" data-testid="plan-totals">
      {p.done} done · {p.skipped} skipped · {p.left} left · about {p.minutes_spent} min spent
    </Text>
  );
}

/** A plan's days as a read-only list: what a preview and an AI plan show. */
export function PlanPreviewList({ plan, testid }: { plan: PlanPreview; testid: string }) {
  return (
    <Stack gap={6} data-testid={testid}>
      {plan.days.map((d) => (
        <Paper key={d.position} withBorder p="xs">
          <Text size="xs" c="dimmed">
            Week {d.week} · {d.date ? dayLabel(d.date) : `Day ${d.position}`}
          </Text>
          {d.tasks.map((t, i) => (
            <Text key={i} size="sm">
              {t.title} ({t.minutes} min)
            </Text>
          ))}
        </Paper>
      ))}
    </Stack>
  );
}

function PlanDays({
  plan,
  readOnly,
  onChanged,
  onStart,
}: {
  plan: TrainingPlan;
  readOnly: boolean;
  onChanged: () => void;
  onStart: (t: PlanTask) => void;
}) {
  const today = plan.days.find((d) => d.is_today) ?? null;
  return (
    <Accordion multiple defaultValue={today ? [String(today.id)] : []} variant="separated" data-testid="plan-days">
      {plan.days.map((d) => {
        const done = d.tasks.filter((t) => t.status === "done").length;
        return (
          <Accordion.Item key={d.id} value={String(d.id)}>
            <Accordion.Control data-testid={`plan-day-control-${d.id}`}>
              <Group gap="xs">
                <Text size="sm">
                  Week {d.week} · {dayLabel(d.date)}
                </Text>
                {d.is_today && (
                  <Badge size="xs" data-testid="plan-today-badge">
                    Today
                  </Badge>
                )}
                <Text size="xs" c="dimmed">
                  {done} of {d.tasks.length} done
                </Text>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <PlanChecklist day={d} readOnly={readOnly} onChanged={onChanged} onStart={onStart} />
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
}

export function PlanTab({
  version,
  onChanged,
  onStart,
}: {
  version: number; // bumped after any change, from here or the Today card
  onChanged: () => void;
  onStart: (t: PlanTask) => void;
}) {
  const [settings, setSettings] = useState<PlanSettings | null>(null);
  const [plan, setPlan] = useState<TrainingPlan | null>(null);
  const [history, setHistory] = useState<TrainingPlan[]>([]);
  const [viewing, setViewing] = useState<TrainingPlan | null>(null);
  const [preview, setPreview] = useState<PlanPreview | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.getCurrentPlan().then(setPlan, (e: Error) => setError(e.message));
    api.listPlans().then((all) => setHistory(all.filter((p) => p.status !== "current")), () => undefined); // prettier-ignore
  }, []);
  useEffect(() => {
    api.getPlanSettings().then(setSettings, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load, version]);

  if (!settings) return <Text c="dimmed">Loading…</Text>;
  const params: PlanParams = { weeks: settings.weeks, weekdays: settings.weekdays, minutes: settings.minutes };
  const set = (patch: Partial<PlanParams>) => {
    setPreview(null);
    const next = { ...settings, ...patch };
    setSettings(next);
    // AI coaching plans in these settings (FR-10.66), so they're kept as you change them. An invalid value isn't.
    if (next.weekdays.length > 0 && next.minutes >= 10 && next.minutes <= 120) {
      api.setSetting("plan.params", { weeks: next.weeks, weekdays: next.weekdays, minutes: next.minutes }).catch((e: Error) => setError(e.message));
    }
  };
  const valid = settings.weekdays.length > 0 && settings.minutes >= 10 && settings.minutes <= 120;
  const showPreview = () => {
    setError(null);
    setBusy(true);
    api.previewPlan(params).then(setPreview, (e: Error) => setError(e.message)).finally(() => setBusy(false)); // prettier-ignore
  };
  const create = (confirmed: boolean) => {
    setError(null);
    setBusy(true);
    setConfirm(false);
    api
      .createPlan(params, confirmed)
      .then(() => {
        setPreview(null);
        load();
        onChanged();
      }, (e: Error) => setError(e.message)) // prettier-ignore
      .finally(() => setBusy(false));
  };
  const carry = (on: boolean) => {
    setSettings({ ...settings, carry_over: on });
    api.setSetting("plan.carry_over", on).then(onChanged, (e: Error) => setError(e.message));
  };

  return (
    <Stack gap="md" data-testid="plan-tab">
      {plan && (
        <Paper withBorder p="md" data-testid="plan-current">
          <Stack gap="sm">
            <Group justify="space-between">
              <Title order={4}>
                Your plan{plan.source === "ai" ? " (from the AI)" : ""}
              </Title>
              <Totals p={plan} />
            </Group>
            <PlanDays plan={plan} readOnly={false} onChanged={onChanged} onStart={onStart} />
          </Stack>
        </Paper>
      )}
      <Paper withBorder p="md" data-testid="plan-builder">
        <Stack gap="sm">
          <Title order={5}>{plan ? "Build a new plan" : "Build your plan"}</Title>
          <Text size="sm" c="dimmed">
            Built from your latest Coach report: your top weaknesses get the most time. Free, and it stays on your PC.
          </Text>
          {!settings.has_report && !plan && (
            <Alert color="blue" p="xs" data-testid="plan-no-report">
              Run the Coach first: a plan is built from your latest report.
            </Alert>
          )}
          <Group align="flex-end">
            <Select
              w={120}
              label={<Labeled id="plan.weeks">Weeks</Labeled>}
              value={String(settings.weeks)}
              onChange={(v) => set({ weeks: Number(v) })}
              data={["1", "2", "3", "4"]}
              allowDeselect={false}
              data-testid="plan-weeks"
            />
            <NumberInput
              w={170}
              label={<Labeled id="plan.minutes">Minutes per day</Labeled>}
              min={10}
              max={120}
              step={5}
              value={settings.minutes}
              onChange={(v) => typeof v === "number" && set({ minutes: Math.round(v) })}
              data-testid="plan-minutes"
            />
          </Group>
          <Stack gap={4} data-option-group>
            <Text size="sm" fw={500}>
              Training days
              <OptionInfo id="plan.weekdays" />
            </Text>
            <Chip.Group multiple value={settings.weekdays.map(String)} onChange={(v) => set({ weekdays: v.map(Number).sort((a, b) => a - b) })}>
              <Group gap={4} data-testid="plan-weekdays">
                {WEEKDAYS.map((d, i) => (
                  <Chip key={d} value={String(i)} size="xs" wrapperProps={{ "data-testid": `plan-weekday-${i}` }}>
                    {d}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
          </Stack>
          <Switch
            label={<Labeled id="plan.carry">Carry over missed tasks</Labeled>}
            checked={settings.carry_over}
            onChange={(e) => carry(e.currentTarget.checked)}
            data-testid="plan-carry"
          />
          <Group>
            <Button size="sm" variant="default" onClick={showPreview} disabled={!valid || busy} data-testid="plan-preview">
              Preview the plan
            </Button>
          </Group>
          {preview && (
            <Stack gap="xs">
              <Text size="sm" data-testid="plan-preview-start">
                It would start on {preview.start_date ? dayLabel(preview.start_date) : "your next training day"}: {preview.days.length} training days.
              </Text>
              <PlanPreviewList plan={preview} testid="plan-preview-list" />
              <Group>
                <Button onClick={() => (preview.replaces ? setConfirm(true) : create(false))} disabled={busy} data-testid="plan-create">
                  Start this plan
                </Button>
              </Group>
            </Stack>
          )}
          {error && (
            <Alert color="red" p="xs" data-testid="plan-tab-error">
              {error}
            </Alert>
          )}
        </Stack>
      </Paper>
      {history.length > 0 && (
        <Paper withBorder p="md" data-testid="plan-history">
          <Stack gap="xs">
            <Title order={5}>Earlier plans</Title>
            {history.map((p) => (
              <Group key={p.id} justify="space-between" data-testid={`plan-old-${p.id}`}>
                <Text size="sm">
                  {dayLabel(p.start_date)} · {p.weeks} week{p.weeks === 1 ? "" : "s"} · {STATUS_TEXT[p.status]}: {p.done} done, {p.skipped} skipped
                </Text>
                <Button size="compact-xs" variant="subtle" onClick={() => setViewing(p)} data-testid={`plan-old-view-${p.id}`}>
                  View
                </Button>
              </Group>
            ))}
          </Stack>
        </Paper>
      )}
      <Modal opened={viewing !== null} onClose={() => setViewing(null)} size="lg" title="An earlier plan" data-testid="plan-old-modal">
        {viewing && (
          <Stack>
            <Totals p={viewing} />
            <PlanDays plan={viewing} readOnly onChanged={() => undefined} onStart={() => undefined} />
          </Stack>
        )}
      </Modal>
      <Modal opened={confirm} onClose={() => setConfirm(false)} title="Replace your current plan?" data-testid="plan-confirm">
        <Stack>
          <Text size="sm">This starts the new plan. Your current plan stays under Earlier plans with what you've done so far.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button onClick={() => create(true)} data-testid="plan-confirm-button">
              Replace it
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
