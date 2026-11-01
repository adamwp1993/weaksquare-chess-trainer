import { ActionIcon, AppShell, Center, Group, Loader, Menu, Modal, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { PuzzleDbStatus } from "./api/types";
import { AboutModal } from "./views/AboutModal";
import { ImportView } from "./views/ImportView";

export function App() {
  const [aboutOpen, setAboutOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [dbStatus, setDbStatus] = useState<PuzzleDbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.getPuzzleDbStatus().then(setDbStatus, (e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  const imported = useCallback(() => {
    setUpdateOpen(false);
    refresh();
  }, [refresh]);

  let main;
  if (error) main = <Text c="red">{error}</Text>;
  else if (!dbStatus)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else if (!dbStatus.installed)
    main = <ImportView firstRun runningJobId={dbStatus.import_job_id} onDone={imported} />;
  else
    main = (
      <Text data-testid="db-ready">
        {dbStatus.puzzle_count?.toLocaleString("en-US")} puzzles ready
        {dbStatus.export_date && ` (Lichess export of ${dbStatus.export_date})`}.
      </Text>
    );

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={3}>WeakSquare Chess Trainer</Title>
          <Menu position="bottom-end" width={240}>
            <Menu.Target>
              <ActionIcon variant="subtle" size="lg" aria-label="Menu">
                ☰
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {dbStatus?.installed && (
                <Menu.Item onClick={() => setUpdateOpen(true)}>Update puzzle database…</Menu.Item>
              )}
              <Menu.Item onClick={() => setAboutOpen(true)}>About</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </AppShell.Header>
      <AppShell.Main>{main}</AppShell.Main>
      <AboutModal opened={aboutOpen} onClose={() => setAboutOpen(false)} />
      <Modal opened={updateOpen} onClose={() => setUpdateOpen(false)} title="Update the puzzle database" size="lg">
        <ImportView firstRun={false} runningJobId={dbStatus?.import_job_id ?? null} onDone={imported} />
      </Modal>
    </AppShell>
  );
}
