import { Alert, Anchor, Button, Center, Loader, Paper, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";
import type { AccountStatus } from "../api/types";
import { AccountPanel, accountLine } from "../components/AccountPanel";

// The startup page (FR-1.1, 1.5–1.7): shown at every launch. With a sign-in that Lichess accepts,
// it's a single "Continue as <name>" button (the fast path); you can always continue without one.
export function StartupView({
  account,
  onContinue,
  onChanged,
}: {
  account: AccountStatus | null;
  onContinue: () => void;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const state = account?.state ?? "checking";
  const fastPath = state === "signed_in" && !expanded;

  let continueLabel = "Continue without signing in";
  if (state === "signed_in") continueLabel = `Continue as ${account?.username}`;
  else if (state === "offline") continueLabel = `Continue offline as ${account?.username}`;
  else if (state === "checking" && account?.username) continueLabel = `Continue as ${account.username}`;

  return (
    <Center mih="calc(100vh - 56px - 2 * var(--mantine-spacing-md))">
      <Paper withBorder radius="md" p="xl" w={520} data-testid="startup">
        <Stack gap="md">
          <Title order={2}>Welcome</Title>
          <Text size="sm" c="dimmed">
            Train tactics on the Lichess puzzle database. Signing in with Lichess syncs your solves and shows your puzzle
            rating; it's optional.
          </Text>
          <Text fw={500} data-testid="startup-status">
            {state === "checking" && <Loader size="xs" mr={8} />}
            {accountLine(account)}
          </Text>
          {state === "offline" && (
            <Alert color="yellow" data-testid="startup-offline">
              Lichess can't be reached. Continue offline: your solves are saved here and sync when Lichess is back.
            </Alert>
          )}
          <Button size="md" onClick={onContinue} data-testid="startup-continue">
            {continueLabel}
          </Button>
          {fastPath ? (
            <Anchor component="button" size="sm" onClick={() => setExpanded(true)} data-testid="startup-more">
              Show all options
            </Anchor>
          ) : (
            <AccountPanel account={account} onChanged={onChanged} compact />
          )}
        </Stack>
      </Paper>
    </Center>
  );
}
