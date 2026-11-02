import { Anchor, Button, Code, Group, Modal, Stack, Table, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppInfo, EngineStatus } from "../api/types";

// NFR-7: version, data and logs folders (with Open), puzzle DB export date, Stockfish version and path,
// license, source link.
export function AboutModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    api.getAppInfo().then(setInfo, (e: Error) => setError(e.message));
    api.getEngineStatus().then(setEngine, () => setEngine(null));
  }, [opened]);

  const open = (kind: "data" | "logs") => api.openFolder(kind).catch((e: Error) => setError(e.message));

  return (
    <Modal opened={opened} onClose={onClose} title="About WeakSquare Chess Trainer" size="lg">
      {error && <Text c="red">{error}</Text>}
      {info && (
        <Stack gap="sm">
          <Table withRowBorders={false} verticalSpacing={4}>
            <Table.Tbody>
              <Table.Tr>
                <Table.Th w={170}>Version</Table.Th>
                <Table.Td>
                  {info.version}
                  {info.dev_mode && " (development run)"}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>Data folder</Table.Th>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap" align="flex-start">
                    <Code style={{ wordBreak: "break-all", flex: 1, minWidth: 0 }}>{info.data_dir}</Code>
                    <Button size="compact-xs" variant="light" style={{ flexShrink: 0 }} onClick={() => open("data")}>
                      Open
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>Logs folder</Table.Th>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap" align="flex-start">
                    <Code style={{ wordBreak: "break-all", flex: 1, minWidth: 0 }}>{info.logs_dir}</Code>
                    <Button size="compact-xs" variant="light" style={{ flexShrink: 0 }} onClick={() => open("logs")}>
                      Open
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>Puzzle database</Table.Th>
                <Table.Td data-testid="about-puzzle-db">
                  {info.puzzle_count === null
                    ? "Not imported yet"
                    : `${info.puzzle_count.toLocaleString("en-US")} puzzles` +
                      (info.puzzle_db_export_date ? `, Lichess export of ${info.puzzle_db_export_date}` : "")}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>Stockfish</Table.Th>
                <Table.Td data-testid="about-engine">
                  {engine?.state === "ready" ? (
                    <Stack gap={2}>
                      <Text size="sm">
                        {engine.name} ({engine.source === "custom" ? "your own engine" : engine.tag})
                      </Text>
                      <Code style={{ wordBreak: "break-all" }}>{engine.path}</Code>
                    </Stack>
                  ) : engine?.state === "custom_invalid" ? (
                    <Stack gap={2}>
                      <Text size="sm">Your custom engine can't be found (Settings → Engine)</Text>
                      {engine.path && <Code style={{ wordBreak: "break-all" }}>{engine.path}</Code>}
                    </Stack>
                  ) : (
                    "Not installed (Settings → Engine)"
                  )}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>License</Table.Th>
                <Table.Td>{info.license}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th>Source code</Table.Th>
                <Table.Td>
                  <Anchor href={info.source_url} target="_blank" rel="noreferrer">
                    {info.source_url}
                  </Anchor>
                </Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
          <Text size="xs" c="dimmed">
            Puzzles come from the Lichess open puzzle database (public domain). This app isn't affiliated with
            Lichess.
          </Text>
        </Stack>
      )}
    </Modal>
  );
}
