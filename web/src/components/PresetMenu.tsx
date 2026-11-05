import { ActionIcon, Alert, Badge, Button, Group, Menu, Modal, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ApiCallError } from "../api/ApiClient";
import type { FilterSpec, Preset } from "../api/types";
import { Labeled } from "./OptionInfo";

type Dialog = { kind: "save" } | { kind: "rename"; name: string } | { kind: "delete"; name: string } | null;

// FR-3.13: save, load, rename and delete named filter sets. Presets live in user.db.
// Adam, 2026-11-04 (during the v0.11 build): Update a saved preset with the current filters, and a
// Manage presets list to rename or delete any preset without loading it first (unusable ones too).
export function PresetMenu({ spec, onLoad }: { spec: FilterSpec; onLoad: (spec: FilterSpec) => void }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [manage, setManage] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
    setNotice(null);
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
    setNotice(null);
    const p = presets.find((x) => x.name === value);
    if (!p) return;
    if (!p.spec) {
      setLoadError(p.error);
      return;
    }
    setCurrent(p.name);
    onLoad(p.spec);
  };

  const update = (target: string) =>
    api.savePreset(target, spec, true).then(
      () => {
        setNotice(`“${target}” now has your current filters.`);
        refresh();
      },
      (e: Error) => setLoadError(e.message),
    );

  const renamed = (from: string, to: string) => {
    if (current === from) setCurrent(to.trim());
  };

  return (
    <Stack gap={4}>
      <Group gap="xs" align="end" wrap="nowrap">
        <Select
          label={<Labeled id="preset.load">Preset</Labeled>}
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
            <ActionIcon variant="default" size="lg" aria-label="Preset actions" data-testid="preset-actions">
              ⋯
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item disabled={!current} onClick={() => current && update(current)} data-testid="preset-update">
              {current ? `Update “${current}” with these filters` : "Update the loaded preset"}
            </Menu.Item>
            <Menu.Item disabled={!current} onClick={() => current && open({ kind: "rename", name: current }, current)}>
              Rename…
            </Menu.Item>
            <Menu.Item color="red" disabled={!current} onClick={() => current && open({ kind: "delete", name: current })}>
              Delete…
            </Menu.Item>
            <Menu.Divider />
            <Menu.Item onClick={() => setManage(true)} data-testid="preset-manage">
              Manage presets…
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
      {loadError && (
        <Text size="xs" c="red" data-testid="preset-load-error">
          {loadError}
        </Text>
      )}
      {notice && (
        <Text size="xs" c="dimmed" data-testid="preset-notice">
          {notice}
        </Text>
      )}

      <Modal opened={manage && dialog === null} onClose={() => setManage(false)} title="Your presets" size="lg" data-testid="preset-manager">
        {presets.length === 0 ? (
          <Text size="sm" c="dimmed">
            No presets yet. Use Save as… to keep the filters you have now.
          </Text>
        ) : (
          <Table withTableBorder striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Last saved</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {presets.map((p) => (
                <Table.Tr key={p.name} data-testid={`preset-row-${p.name}`}>
                  <Table.Td>
                    <Group gap={6}>
                      <Text size="sm">{p.name}</Text>
                      {!p.spec && (
                        <Badge size="xs" color="gray" variant="light" title={p.error ?? undefined}>
                          can't be used
                        </Badge>
                      )}
                      {p.name === current && (
                        <Badge size="xs" variant="light">
                          loaded
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{p.updated_at.slice(0, 16).replace("T", " ")}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Button size="compact-xs" variant="default" onClick={() => update(p.name)} data-testid="preset-row-update">
                        Overwrite with these filters
                      </Button>
                      <Button size="compact-xs" variant="default" onClick={() => open({ kind: "rename", name: p.name }, p.name)} data-testid="preset-row-rename">
                        Rename
                      </Button>
                      <Button size="compact-xs" color="red" variant="light" onClick={() => open({ kind: "delete", name: p.name })} data-testid="preset-row-delete">
                        Delete
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        {notice && (
          <Text size="xs" c="dimmed" mt="xs">
            {notice}
          </Text>
        )}
      </Modal>

      <Modal opened={dialog?.kind === "save" || dialog?.kind === "rename"} onClose={close}
             title={dialog?.kind === "rename" ? "Rename preset" : "Save these filters as a preset"}>
        <Stack gap="sm">
          <TextInput
            data-no-tip="a name you type"
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
                    ? run(() => api.renamePreset(dialog.name, name), () => renamed(dialog.name, name))
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
              onClick={() =>
                dialog?.kind === "delete" &&
                run(() => api.deletePreset(dialog.name), () => current === dialog.name && setCurrent(null))
              }
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
