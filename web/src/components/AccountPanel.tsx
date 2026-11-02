import { Alert, Anchor, Button, Group, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ApiCallError } from "../api/ApiClient";
import type { AccountStatus } from "../api/types";
import { useJob } from "../state/useJob";

const REVOKE_PAGE = "https://lichess.org/account/security";

/** One line saying where your Lichess account stands (FR-1.1). */
export function accountLine(account: AccountStatus | null): string {
  if (!account) return "Checking…";
  switch (account.state) {
    case "signed_in":
      return `Signed in as ${account.username}`;
    case "checking":
      return `Checking your Lichess sign-in${account.username ? ` (${account.username})` : ""}…`;
    case "offline":
      return `Signed in as ${account.username}, but Lichess can't be reached right now.`;
    case "expired":
      return "Your Lichess sign-in has expired or was revoked. Sign in again.";
    default:
      return "Not signed in";
  }
}

// Sign in with Lichess (PKCE in your default browser, FR-6.1a) and sign out (revokes the token,
// FR-6.6). Used on the startup page and in Settings → Account.
export function AccountPanel({
  account,
  onChanged,
  compact = false,
}: {
  account: AccountStatus | null;
  onChanged: () => void;
  /** Hide the status line (the startup page shows its own). */
  compact?: boolean;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const [error, setError] = useState<string | null>(null);
  const [revokeFailed, setRevokeFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const waiting = job?.state === "running";
  const signedIn = account?.state === "signed_in" || account?.state === "offline" || account?.state === "checking";

  useEffect(() => {
    if (job && job.state !== "running") onChanged();
  }, [job, onChanged]);

  const signIn = async () => {
    setError(null);
    try {
      setJobId(await api.startSignIn());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const signOut = async (forceLocal: boolean) => {
    setError(null);
    setBusy(true);
    try {
      await api.signOut(forceLocal);
      setRevokeFailed(false);
      setJobId(null);
      onChanged();
    } catch (e) {
      if (e instanceof ApiCallError && e.code === "revoke_failed") setRevokeFailed(true);
      else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack gap="xs" data-testid="account-panel">
      {!compact && (
        <Text size="sm" data-testid="account-status">
          {accountLine(account)}
        </Text>
      )}
      {waiting ? (
        <Group gap="xs" data-testid="sign-in-waiting">
          <Text size="sm">Waiting for you in your browser… Approve WeakSquare on lichess.org, then come back here.</Text>
          <Button size="xs" variant="default" onClick={() => api.cancelSignIn()}>
            Cancel
          </Button>
        </Group>
      ) : (
        <Group gap="xs">
          {!signedIn && (
            <Button onClick={signIn} data-testid="sign-in">
              Sign in with Lichess
            </Button>
          )}
          {signedIn && (
            <>
              <Button size="xs" variant="default" onClick={signIn} data-testid="sign-in-other">
                Sign in as someone else
              </Button>
              <Button size="xs" variant="default" color="red" onClick={() => signOut(false)} loading={busy} data-testid="sign-out">
                Sign out
              </Button>
            </>
          )}
        </Group>
      )}
      {job?.state === "failed" && (
        <Alert color="red" data-testid="sign-in-failed">
          {job.message}
        </Alert>
      )}
      {error && <Alert color="red">{error}</Alert>}
      {revokeFailed && (
        <Alert color="yellow" data-testid="revoke-failed">
          <Stack gap="xs">
            <Text size="sm">
              Lichess couldn't be reached, so your sign-in wasn't revoked there. You can remove it from this PC anyway and
              revoke it later at <Anchor href={REVOKE_PAGE} target="_blank" rel="noreferrer">lichess.org/account/security</Anchor>.
            </Text>
            <Group gap="xs">
              <Button size="xs" color="red" onClick={() => signOut(true)} data-testid="sign-out-anyway">
                Remove from this PC anyway
              </Button>
              <Button size="xs" variant="default" onClick={() => setRevokeFailed(false)}>
                Keep it
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}
      <Text size="xs" c="dimmed">
        Signing in opens lichess.org in your browser. WeakSquare asks only to read and record your puzzle activity; the
        sign-in is kept in Windows Credential Manager, never in a file.
      </Text>
    </Stack>
  );
}
