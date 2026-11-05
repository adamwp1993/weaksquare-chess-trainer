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
import { FeatureModelPicker } from "./FeatureModelPicker";
import { PriceTable } from "./PriceTable";
import { Labeled, OptionInfo } from "./OptionInfo";

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
// v0.9 (FR-1.15): Game Review has its own model picker ("Same as Explain" by default) in both versions,
// and its own reasoning level in the full one. Keys, the cap and the budget are shared.
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
  // An emptied field keeps the saved amount (v0.7-B4): $0 is a real choice that blocks every Explain, so it
  // has to be typed, never left behind by clearing the box.
  const saveDollars = (field: "run_cap_usd" | "monthly_budget_usd", text: string) => {
    const value = text.trim() === "" ? NaN : Number(text);
    if (!Number.isFinite(value)) {
      setInputsKey((k) => k + 1);
      return;
    }
    if (value !== settings[field]) save({ [field]: value });
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
      <Text size="sm" fw={600}>
        Puzzle Explain
      </Text>
      <Select
        label={<Labeled id="ai.provider">AI provider (optional)</Labeled>}
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
            label={<Labeled id="ai.model">Model</Labeled>}
            description="Pick one; nothing is chosen for you. You can also type another model ID."
            placeholder="Choose a model"
            data={options}
            value={modelValue}
            filter={({ options: all, search }) => {
              // A picked model shows the whole list, so you can switch without clearing it (v0.7-B6);
              // anything else you type narrows it.
              const q = search.trim().toLowerCase();
              if (!q || info.models.some((m) => m.model === search.trim())) return all;
              return all.filter((o) => "value" in o && o.value.toLowerCase().includes(q));
            }}
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
              data-no-tip="your key: it has its own description"
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
      {full && info && (
            <Stack gap={2} data-option-group>
              <Text size="sm" fw={500}>
                Puzzle Explain reasoning
                <OptionInfo id="ai.reasoning" />
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
      )}
      {/* Game Review can be set up on its own provider, even with puzzle Explain off (v0.9-B5). */}
      <Stack gap={4} mt="xs">
        <Text size="sm" fw={600}>
          Game Review
        </Text>
        <FeatureModelPicker reasoning={full} onError={setError} />
      </Stack>
      {full && (
        <Stack gap={4} mt="xs">
          <Text size="sm" fw={600}>
            Coach
          </Text>
          <FeatureModelPicker feature="coach" reasoning onError={setError} />
        </Stack>
      )}
      {full && (
        <>
          <Group grow align="flex-start" key={inputsKey}>
            <NumberInput
              label={<Labeled id="ai.runCap">Per-run cap ($)</Labeled>}
              description="A request that could cost more is blocked"
              defaultValue={settings.run_cap_usd}
              min={0}
              max={1000}
              step={0.1}
              decimalScale={2}
              onBlur={(e) => saveDollars("run_cap_usd", e.currentTarget.value)}
              data-testid="ai-cap"
            />
            <NumberInput
              label={<Labeled id="ai.budget">Monthly budget ($)</Labeled>}
              description="Warns at 80%, blocks at 100%"
              defaultValue={settings.monthly_budget_usd}
              min={0}
              max={1000}
              step={1}
              decimalScale={2}
              onBlur={(e) => saveDollars("monthly_budget_usd", e.currentTarget.value)}
              data-testid="ai-budget"
            />
          </Group>
          <Text size="sm" data-testid="ai-spend-line">
            This month: {dollars(spend.spent_usd)} of {dollars(spend.budget_usd)}
            {spend.level === "over" ? " (budget used up: the AI is off until next month or until you raise it)" : spend.level === "warn" ? " (over 80%)" : ""}
          </Text>
          <Text size="xs" c="dimmed" data-testid="ai-spend-by-feature">
            {settings.features.map((f) => `${f.label} ${dollars(f.spent_usd)}`).join("  ·  ")}
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
