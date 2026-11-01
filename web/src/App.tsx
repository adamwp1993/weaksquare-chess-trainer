import { ActionIcon, AppShell, Group, Title, Tooltip } from "@mantine/core";
import { useState } from "react";
import { AboutModal } from "./views/AboutModal";

export function App() {
  const [aboutOpen, setAboutOpen] = useState(false);

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={3}>WeakSquare Chess Trainer</Title>
          <Tooltip label="About">
            <ActionIcon variant="subtle" size="lg" aria-label="About" onClick={() => setAboutOpen(true)}>
              ?
            </ActionIcon>
          </Tooltip>
        </Group>
      </AppShell.Header>
      <AppShell.Main />
      <AboutModal opened={aboutOpen} onClose={() => setAboutOpen(false)} />
    </AppShell>
  );
}
