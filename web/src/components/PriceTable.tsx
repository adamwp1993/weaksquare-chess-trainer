import { Alert, Button, Group, NumberInput, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { LlmPriceChange, LlmProvider } from "../api/ApiClient";
import type { LlmPrice } from "../api/types";
import { refreshLlm } from "../state/llm";
import { Labeled } from "./OptionInfo";

const EMPTY: LlmPriceChange = { provider: "anthropic", model: "", input_per_m: 0, output_per_m: 0 };
const num = (v: string | number) => (v === "" ? null : Number(v));

// The editable price table (FR-8.9): every cost in the app comes from these rows and the token counts
// the provider reports. Edit fills the form; Save adds or replaces the row for that provider and model.
export function PriceTable() {
  const [rows, setRows] = useState<LlmPrice[] | null>(null);
  const [form, setForm] = useState<LlmPriceChange>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listLlmPrices().then(setRows, (e: Error) => setError(e.message));
  }, []);

  const done = (next: LlmPrice[]) => {
    setRows(next);
    setForm(EMPTY);
    refreshLlm(); // the model dropdown follows the table
  };
  const save = () => {
    setError(null);
    api.saveLlmPrice(form).then(done, (e: Error) => setError(e.message));
  };
  const remove = (r: LlmPrice) => {
    setError(null);
    api.deleteLlmPrice(r.provider, r.model).then(done, (e: Error) => setError(e.message));
  };
  const edit = (r: LlmPrice) =>
    setForm({
      provider: r.provider,
      model: r.model,
      input_per_m: r.input_per_m,
      output_per_m: r.output_per_m,
      long_ctx_threshold: r.long_ctx_threshold,
      long_input_per_m: r.long_input_per_m,
      long_output_per_m: r.long_output_per_m,
    });

  return (
    <Stack gap="xs" data-testid="price-table">
      <Text size="sm" fw={500}>
        Price table (USD per 1M tokens)
      </Text>
      <Text size="xs" c="dimmed">
        Check these against your provider's pricing page. A long-context price applies to the whole request when its input
        is over the threshold.
      </Text>
      {rows && (
        <Table striped withTableBorder fz="xs" verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Model</Table.Th>
              <Table.Th>Input</Table.Th>
              <Table.Th>Output</Table.Th>
              <Table.Th>Long context</Table.Th>
              <Table.Th>As of</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={`${r.provider}/${r.model}`} data-testid="price-row">
                <Table.Td>{r.model}</Table.Td>
                <Table.Td>${r.input_per_m}</Table.Td>
                <Table.Td>${r.output_per_m}</Table.Td>
                <Table.Td>
                  {r.long_ctx_threshold !== null
                    ? `$${r.long_input_per_m} / $${r.long_output_per_m} over ${r.long_ctx_threshold.toLocaleString()}`
                    : "—"}
                </Table.Td>
                <Table.Td>{r.as_of}</Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <Button size="compact-xs" variant="subtle" onClick={() => edit(r)}>
                      Edit
                    </Button>
                    <Button size="compact-xs" variant="subtle" color="red" onClick={() => remove(r)}>
                      Delete
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Group grow align="flex-end" gap="xs">
        <Select
          label={<Labeled id="price.provider">Provider</Labeled>}
          data={[
            { value: "anthropic", label: "Anthropic" },
            { value: "openai", label: "OpenAI" },
          ]}
          value={form.provider}
          allowDeselect={false}
          onChange={(v) => v && setForm({ ...form, provider: v as LlmProvider })}
        />
        <TextInput label={<Labeled id="price.model">Model ID</Labeled>} value={form.model} onChange={(e) => setForm({ ...form, model: e.currentTarget.value })} data-testid="price-model" />
      </Group>
      <Group grow align="flex-end" gap="xs">
        <NumberInput label={<Labeled id="price.input">Input $</Labeled>} min={0} max={1000} decimalScale={4} value={form.input_per_m}
          onChange={(v) => setForm({ ...form, input_per_m: Number(v) })} data-testid="price-input" />
        <NumberInput label={<Labeled id="price.output">Output $</Labeled>} min={0} max={1000} decimalScale={4} value={form.output_per_m}
          onChange={(v) => setForm({ ...form, output_per_m: Number(v) })} data-testid="price-output" />
      </Group>
      <Group grow align="flex-end" gap="xs">
        <NumberInput label={<Labeled id="price.longOver">Long context over (tokens)</Labeled>} min={1} allowDecimal={false} value={form.long_ctx_threshold ?? ""}
          onChange={(v) => setForm({ ...form, long_ctx_threshold: num(v) })} />
        <NumberInput label={<Labeled id="price.longInput">Long input $</Labeled>} min={0} max={1000} decimalScale={4} value={form.long_input_per_m ?? ""}
          onChange={(v) => setForm({ ...form, long_input_per_m: num(v) })} />
        <NumberInput label={<Labeled id="price.longOutput">Long output $</Labeled>} min={0} max={1000} decimalScale={4} value={form.long_output_per_m ?? ""}
          onChange={(v) => setForm({ ...form, long_output_per_m: num(v) })} />
      </Group>
      <Group gap="xs">
        <Button size="xs" onClick={save} disabled={!form.model.trim()} data-testid="price-save">
          Save price
        </Button>
        {form !== EMPTY && (
          <Button size="xs" variant="subtle" color="gray" onClick={() => setForm(EMPTY)}>
            Clear
          </Button>
        )}
      </Group>
      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)} data-testid="price-error">
          {error}
        </Alert>
      )}
    </Stack>
  );
}
