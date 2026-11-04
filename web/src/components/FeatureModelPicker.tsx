import { Button, Group, PasswordInput, SegmentedControl, Select, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { api } from "../api";
import type { LlmProvider } from "../api/ApiClient";
import type { LlmFeature, LlmSettings } from "../api/types";
import { dollars, publishLlm, useLlmSettings } from "../state/llm";

const SAME = "same";
const LABELS: Record<LlmProvider, string> = { anthropic: "Anthropic", openai: "OpenAI" };
const PREFIX: Record<LlmProvider, string> = { anthropic: "sk-ant-…", openai: "sk-…" };
const REASONING: { value: LlmSettings["reasoning"]; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

// A model ID as the providers spell them (the backend's MODEL_ID): typed IDs are allowed, as in FR-1.3.
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$/;
type Saved = { choice: "same" | LlmProvider; model: string; reasoning: LlmSettings["reasoning"] };

/** The value a feature's Select holds: "same", or "provider|model". */
function valueOf(f: LlmFeature): string {
  return f.choice === SAME || f.choice === "none" ? SAME : `${f.choice}|${f.model}`;
}

// Game Review's model (FR-1.15, v0.9): "Same as Explain" (the default) or any model in the price table, from
// either provider, with about what one Explain my game costs on it. The same setting appears in Settings →
// AI, on the startup page and on the Review page (Adam, v0.9 planning). Keys stay one per provider: if
// the model's provider has no key yet, a key field appears right here. You can also type a model ID that
// isn't in the list and choose its provider (FR-1.3, v0.9-B4); without a price row it can't be used yet.
export function FeatureModelPicker({
  feature = "game_review",
  reasoning = false,
  compact = false,
  onError,
}: {
  feature?: "game_review" | "coach";
  reasoning?: boolean;
  compact?: boolean;
  onError?: (message: string | null) => void;
}) {
  const settings = useLlmSettings();
  const [key, setKey] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [search, setSearch] = useState<string | null>(null); // what you're typing in the model field
  // The choice being saved, so a second change before the first returns builds on it, not on the stale
  // props (v0.9-B1).
  const [pending, setPending] = useState<Saved | null>(null);
  const f = settings?.features.find((x) => x.feature === feature);
  if (!settings || !f) return null;
  const fail = (e: Error) => (onError ? onError(e.message) : setLocalError(e.message));
  const clear = () => (onError ? onError(null) : setLocalError(null));

  const explainModel = settings.provider === "none" ? "" : (settings.providers.find((p) => p.provider === settings.provider)?.model ?? "");
  const groups = (["anthropic", "openai"] as LlmProvider[]).map((p) => ({
    group: LABELS[p] + (settings.providers.find((x) => x.provider === p)?.key_stored ? "" : " (needs a key)"),
    items: f.options
      .filter((o) => o.provider === p)
      .map((o) => ({ value: `${o.provider}|${o.model}`, label: `${o.model}  ·  about ${dollars(o.usd)} per ${feature === "coach" ? "report" : "game"}` })),
  }));
  const own = f.choice !== SAME && f.choice !== "none" && !f.options.some((o) => `${o.provider}|${o.model}` === valueOf(f));
  const typed = (search ?? "").trim();
  const typedItems =
    MODEL_ID.test(typed) && !f.options.some((o) => o.model === typed)
      ? (["anthropic", "openai"] as LlmProvider[])
          .filter((p) => `${p}|${typed}` !== valueOf(f))
          .map((p) => ({ value: `${p}|${typed}`, label: `Use “${typed}” with ${LABELS[p]}` }))
      : [];
  const data = [
    { group: "Default", items: [{ value: SAME, label: explainModel ? `Same as Explain (${explainModel})` : "Same as Explain" }] },
    ...groups,
    ...(own ? [{ group: "Other", items: [{ value: valueOf(f), label: `${f.model} (not in the price table)` }] }] : []),
    ...(typedItems.length ? [{ group: "Type a model ID", items: typedItems }] : []),
  ];
  const current: Saved = pending ?? {
    choice: f.choice === "none" ? SAME : (f.choice as Saved["choice"]),
    model: f.model,
    reasoning: f.reasoning,
  };
  const save = (over: Partial<Saved>) => {
    clear();
    const next: Saved = { ...current, ...over };
    if (next.choice === SAME) next.model = "";
    setPending(next);
    const done = () => setPending((p) => (p === next ? null : p));
    api.setLlmFeature(feature, next.choice, next.model, next.reasoning).then(
      (s) => {
        done();
        publishLlm(s);
      },
      (e: Error) => {
        done();
        fail(e);
      },
    );
  };
  const pick = (v: string | null) => {
    setSearch(null);
    if (!v) return;
    if (v === SAME) return save({ choice: SAME, model: "" });
    const [p, ...rest] = v.split("|");
    save({ choice: p as LlmProvider, model: rest.join("|") });
  };
  const needsKey =
    f.provider !== "none" && f.choice !== SAME && !settings.providers.find((p) => p.provider === f.provider)?.key_stored;
  const saveKey = () => {
    clear();
    api.setLlmKey(f.provider as LlmProvider, key).then((s) => {
      setKey("");
      publishLlm(s);
    }, fail);
  };

  return (
    <Stack gap={4} data-testid={`ai-feature-${feature}`}>
      <Select
        label={compact ? undefined : `${f.label} model`}
        aria-label={`${f.label} model`}
        description={
          compact
            ? undefined
            : feature === "coach"
              ? "Get AI coaching on a Coach report uses it. A report is sent once, so a stronger model costs little."
              : "Explain this move and Explain my game use it. One game is a much bigger request than one puzzle."
        }
        data={data}
        value={current.choice === SAME ? SAME : `${current.choice}|${current.model}`}
        allowDeselect={false}
        onChange={pick}
        searchable
        searchValue={search ?? undefined}
        onSearchChange={setSearch}
        onBlur={() => setSearch(null)}
        nothingFoundMessage="Not a model ID"
        size={compact ? "xs" : "sm"}
        w={compact ? 300 : undefined}
        comboboxProps={{ withinPortal: true }}
        data-testid={`ai-feature-model-${feature}`}
      />
      {needsKey && (
        <Group align="flex-end" gap="xs" wrap="nowrap">
          <PasswordInput
            style={{ flex: 1 }}
            size={compact ? "xs" : "sm"}
            label={`${LABELS[f.provider as LlmProvider]} API key`}
            description="Saved in Windows Credential Manager, never in a file. Every feature on this provider shares it."
            placeholder={PREFIX[f.provider as LlmProvider]}
            value={key}
            onChange={(e) => setKey(e.currentTarget.value)}
            autoComplete="off"
            data-testid={`ai-feature-key-${feature}`}
          />
          <Button size={compact ? "xs" : "sm"} onClick={saveKey} disabled={!key.trim()} data-testid={`ai-feature-key-save-${feature}`}>
            Save key
          </Button>
        </Group>
      )}
      {reasoning && (
        <Stack gap={2}>
          <Text size="sm" fw={500}>
            {f.label} reasoning
          </Text>
          <SegmentedControl
            data={REASONING}
            value={current.reasoning}
            onChange={(v) => save({ reasoning: v as LlmSettings["reasoning"] })}
            data-testid={`ai-feature-reasoning-${feature}`}
          />
        </Stack>
      )}
      {localError && (
        <Text size="xs" c="red" data-testid={`ai-feature-error-${feature}`}>
          {localError}
        </Text>
      )}
    </Stack>
  );
}
