import {
  Alert,
  Autocomplete,
  Button,
  Group,
  NumberInput,
  PasswordInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import { useState } from "react";
import { api } from "../api";
import type { LlmSettingsChange } from "../api/ApiClient";
import type { LlmSettings } from "../api/types";
import { dollars, publishLlm, useLlmSettings } from "../state/llm";
import { useJob } from "../state/useJob";
import { PriceTable } from "./PriceTable";

const REASONING: { value: LlmSettings["reasoning"]; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

function change(s: LlmSettings, over: Partial<LlmSettingsChange>): LlmSettingsChange {
  const provider = over.provider ?? s.provider;
  const model = over.model ?? (provider === "none" ? "" : (s.providers.find((p) => p.provider === provider)?.model ?? ""));
  return {
    provider,
    model,
    reasoning: s.reasoning,
    run_cap_usd: s.run_cap_usd,
    monthly_budget_usd: s.monthly_budget_usd,
    ...over,
  };
}

// AI explanations (FR-1.2–1.4, 1.8, 8.9–8.15): the provider, its model (nothing is pre-selected; the
// dropdown lists the price table's models with about what one Explain costs, and you can type any other
// ID), the API key (saved to Windows Credential Manager, never shown again) and Test key. The full
// version (Settings → AI) adds reasoning, the per-run cap, the monthly budget and the price table.
export function AiSettingsPanel({ full = false }: { full?: boolean }) {
  const settings = useLlmSettings();
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  // What you're typing in the model field, for the provider it was typed for (switching provider drops it).
  const [modelEdit, setModelEdit] = useState<{ provider: string; text: string } | null>(null);
  const [testJob, setTestJob] = useState<string | null>(null);
  const [inputsKey, setInputsKey] = useState(0); // remounts the number inputs so a refused value snaps back
  const job = useJob(testJob);

  if (!settings) return null;

  const provider = settings.provider;
  const modelText = modelEdit && modelEdit.provider === provider ? modelEdit.text : null;
  const setModelText = (text: string | null) => setModelEdit(text === null ? null : { provider, text });
  const info = provider === "none" ? null : settings.providers.find((p) => p.provider === provider)!;
  const save = (over: Partial<LlmSettingsChange>) => {
    setError(null);
    return api.setLlmSettings(change(settings, over)).then(publishLlm, (e: Error) => {
      setError(e.message);
      setInputsKey((k) => k + 1);
    });
  };
  const saveKey = async () => {
    if (!info) return;
    setError(null);
    try {
      publishLlm(await api.setLlmKey(info.provider, key));
      setKey(""); // it's in Credential Manager now; the field never shows it again
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const removeKey = async () => {
    if (!info) return;
    setError(null);
    api.deleteLlmKey(info.provider).then(publishLlm, (e: Error) => setError(e.message));
  };
  const testKey = async () => {
    if (!info) return;
    setError(null);
    api.startLlmKeyTest(info.provider, info.model).then(setTestJob, (e: Error) => setError(e.message));
  };

  const options = info?.models.map((m) => ({ value: m.model, label: `${m.model}  ·  about ${dollars(m.explain_usd)} per Explain` })) ?? [];
  const modelValue = modelText ?? info?.model ?? "";
  const commitModel = () => {
    if (modelText === null || !info || modelText.trim() === info.model) return setModelText(null);
    save({ model: modelText.trim() }).then(() => setModelText(null));
  };
  const unpriced = info && info.model && !info.models.some((m) => m.model === info.model);
  const spend = settings.spend;

  return (
    <Stack gap="xs" data-testid="ai-settings">
      <Select
        label="AI provider (optional)"
        description="Explain sends the puzzle position and moves to this provider. You pay them directly."
        data={[
          { value: "none", label: "None" },
          { value: "anthropic", label: "Anthropic" },
          { value: "openai", label: "OpenAI" },
        ]}
        value={provider}
        allowDeselect={false}
        onChange={(v) => v && save({ provider: v as LlmSettingsChange["provider"] })}
        data-testid="ai-provider"
      />
      {info && (
        <>
          <Autocomplete
            label="Model"
            description="Pick one; nothing is chosen for you. You can also type another model ID."
            placeholder="Choose a model"
            data={options}
            value={modelValue}
            onChange={setModelText}
            onOptionSubmit={(v) => save({ model: v }).then(() => setModelText(null))}
            onBlur={commitModel}
            onKeyDown={(e) => e.key === "Enter" && commitModel()}
            data-testid="ai-model"
          />
          {unpriced && (
            <Text size="xs" c="orange" data-testid="ai-unpriced">
              {info.model} isn't in the price table, so Explain can't work out its cost. Add its prices below
              {full ? "" : " in Settings → AI"}.
            </Text>
          )}
          <Group align="flex-end" gap="xs" wrap="nowrap">
            <PasswordInput
              style={{ flex: 1 }}
              label={`${info.label} API key`}
              description={info.key_stored ? "A key is saved in Windows Credential Manager." : "Saved in Windows Credential Manager, never in a file."}
              placeholder={info.key_stored ? "Paste a new key to replace it" : info.provider === "anthropic" ? "sk-ant-…" : "sk-…"}
              value={key}
              onChange={(e) => setKey(e.currentTarget.value)}
              autoComplete="off"
              data-testid="ai-key"
            />
            <Button onClick={saveKey} disabled={!key.trim()} data-testid="ai-key-save">
              Save key
            </Button>
          </Group>
          <Group gap="xs">
            <Button variant="light" onClick={testKey} disabled={!info.key_stored || job?.state === "running"} data-testid="ai-key-test">
              Test key
            </Button>
            {info.key_stored && (
              <Button variant="subtle" color="red" onClick={removeKey} data-testid="ai-key-remove">
                Remove key
              </Button>
            )}
          </Group>
          {job && (
            <Text size="sm" c={job.state === "failed" ? "red" : job.state === "done" ? "green" : "dimmed"} data-testid="ai-key-result">
              {job.message}
            </Text>
          )}
        </>
      )}
      {full && (
        <>
          <Stack gap={2}>
            <Text size="sm" fw={500}>
              Reasoning
            </Text>
            <SegmentedControl
              data={REASONING}
              value={settings.reasoning}
              onChange={(v) => save({ reasoning: v as LlmSettings["reasoning"] })}
              data-testid="ai-reasoning"
            />
            <Text size="xs" c="dimmed">
              Hidden reasoning is billed as output: Medium allows about 2× the cost of Low, High about 4×.
            </Text>
          </Stack>
          <Group grow align="flex-start" key={inputsKey}>
            <NumberInput
              label="Per-run cap ($)"
              description="A request that could cost more is blocked"
              value={settings.run_cap_usd}
              min={0}
              max={1000}
              step={0.1}
              decimalScale={2}
              onBlur={(e) => save({ run_cap_usd: Number(e.currentTarget.value) })}
              data-testid="ai-cap"
            />
            <NumberInput
              label="Monthly budget ($)"
              description="Warns at 80%, blocks at 100%"
              value={settings.monthly_budget_usd}
              min={0}
              max={1000}
              step={1}
              decimalScale={2}
              onBlur={(e) => save({ monthly_budget_usd: Number(e.currentTarget.value) })}
              data-testid="ai-budget"
            />
          </Group>
          <Text size="sm" data-testid="ai-spend-line">
            This month: {dollars(spend.spent_usd)} of {dollars(spend.budget_usd)}
            {spend.level === "over" ? " (budget used up: Explain is off until next month or until you raise it)" : spend.level === "warn" ? " (over 80%)" : ""}
          </Text>
          <PriceTable />
        </>
      )}
      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)} data-testid="ai-error">
          {error}
        </Alert>
      )}
    </Stack>
  );
}
