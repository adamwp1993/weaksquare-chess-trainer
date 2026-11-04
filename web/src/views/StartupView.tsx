import { Alert, Anchor, Button, Center, Loader, Paper, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";
import type { AccountStatus } from "../api/types";
import { AccountPanel, accountLine } from "../components/AccountPanel";
import { AiSettingsPanel } from "../components/AiSettingsPanel";
import { useLlmSettings } from "../state/llm";

// The startup page (FR-1.1–1.7): shown at every launch. With a sign-in that Lichess accepts, and either no
// AI set up or an AI key that passed the silent check at launch, it's a single "Continue as <name>"
// button (the fast path, FR-1.6); you can always continue without one. The full form adds the optional
// AI provider, model and key (FR-1.2–1.4).
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
  const llm = useLlmSettings();
  const state = account?.state ?? "checking";
  const aiFailed = llm?.key_check === "failed";
  const fastPath = state === "signed_in" && !expanded && !aiFailed;

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
          {aiFailed && (
            <Alert color="yellow" data-testid="startup-ai-failed">
              Your AI key didn't work: {llm?.key_check_message} You can fix it below, or continue without AI explanations.
            </Alert>
          )}
          {fastPath ? (
            <Anchor component="button" size="sm" onClick={() => setExpanded(true)} data-testid="startup-more">
              Show all options
            </Anchor>
          ) : (
            <Stack gap="lg">
              <AccountPanel account={account} onChanged={onChanged} compact />
              <Stack gap={4}>
                <Text fw={500}>AI explanations (optional)</Text>
                <AiSettingsPanel />
              </Stack>
            </Stack>
          )}
        </Stack>
      </Paper>
    </Center>
  );
}
