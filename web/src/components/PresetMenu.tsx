import { ActionIcon, Alert, Button, Group, Menu, Modal, Select, Stack, Text, TextInput } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ApiCallError } from "../api/ApiClient";
import type { FilterSpec, Preset } from "../api/types";

type Dialog = { kind: "save" } | { kind: "rename"; name: string } | { kind: "delete"; name: string } | null;

// FR-3.13: save, load, rename and delete named filter sets. Presets live in user.db.
export function PresetMenu({ spec, onLoad }: { spec: FilterSpec; onLoad: (spec: FilterSpec) => void }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.listPresets().then(setPresets, () => setPresets([]));
  }, []);
  useEffect(refresh, [refresh]);

  const close = () => {
    setDialog(null);
    setError(null);
    setConflict(false);
  };

  const open = (d: Dialog, initial = "") => {
    setName(initial);
    setError(null);
    setConflict(false);
    setDialog(d);
  };

  const run = async (fn: () => Promise<unknown>, after: () => void) => {
    try {
      await fn();
      after();
      close();
      refresh();
    } catch (e) {
      setConflict(e instanceof ApiCallError && e.code === "conflict" && dialog?.kind === "save");
      setError((e as Error).message);
    }
  };

  const load = (value: string) => {
    setLoadError(null);
    const p = presets.find((x) => x.name === value);
    if (!p) return;
    if (!p.spec) {
      setLoadError(p.error);
      return;
    }
    setCurrent(p.name);
    onLoad(p.spec);
  };

  return (
    <Stack gap={4}>
      <Group gap="xs" align="end" wrap="nowrap">
        <Select
          label="Preset"
          size="xs"
          placeholder="Load a preset"
          data={presets.map((p) => ({ value: p.name, label: p.spec ? p.name : `${p.name} (can't be used)` }))}
          value={current}
          onOptionSubmit={load}
          allowDeselect={false}
          searchable
          nothingFoundMessage="No presets yet"
          style={{ flex: 1 }}
          data-testid="preset-select"
        />
        <Button size="xs" variant="default" onClick={() => open({ kind: "save" }, current ?? "")} data-testid="preset-save">
          Save as…
        </Button>
        <Menu position="bottom-end">
          <Menu.Target>
            <ActionIcon variant="default" size="lg" aria-label="Preset actions" disabled={!current} data-testid="preset-actions">
              ⋯
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => current && open({ kind: "rename", name: current }, current)}>Rename…</Menu.Item>
            <Menu.Item color="red" onClick={() => current && open({ kind: "delete", name: current })}>
              Delete…
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
      {loadError && (
        <Text size="xs" c="red" data-testid="preset-load-error">
          {loadError}
        </Text>
      )}

      <Modal opened={dialog?.kind === "save" || dialog?.kind === "rename"} onClose={close}
             title={dialog?.kind === "rename" ? "Rename preset" : "Save these filters as a preset"}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={name}
            maxLength={60}
            onChange={(e) => {
              setName(e.currentTarget.value);
              setConflict(false);
              setError(null);
            }}
            data-autofocus
            data-testid="preset-name"
          />
          {error && (
            <Alert color={conflict ? "yellow" : "red"} data-testid="preset-error">
              {error}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              Cancel
            </Button>
            {dialog?.kind === "save" && conflict ? (
              <Button color="yellow" onClick={() => run(() => api.savePreset(name, spec, true), () => setCurrent(name.trim()))}
                      data-testid="preset-replace">
                Replace it
              </Button>
            ) : (
              <Button
                onClick={() =>
                  dialog?.kind === "rename"
                    ? run(() => api.renamePreset(dialog.name, name), () => setCurrent(name.trim()))
                    : run(() => api.savePreset(name, spec, false), () => setCurrent(name.trim()))
                }
                data-testid="preset-confirm"
              >
                {dialog?.kind === "rename" ? "Rename" : "Save"}
              </Button>
            )}
          </Group>
        </Stack>
      </Modal>

      <Modal opened={dialog?.kind === "delete"} onClose={close} title="Delete preset">
        <Stack gap="sm">
          <Text>Delete “{dialog?.kind === "delete" ? dialog.name : ""}”? Your filters right now stay as they are.</Text>
          {error && <Alert color="red">{error}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => dialog?.kind === "delete" && run(() => api.deletePreset(dialog.name), () => setCurrent(null))}
              data-testid="preset-delete-confirm"
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
