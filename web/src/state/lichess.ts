import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AccountStatus, SyncStatus } from "../api/types";

const POLL_MS = 5000; // a fallback: pushed events normally arrive first

/** Your Lichess account and the sync queue, kept current from pushed events (FR-1.1, 1.7, 6.11a). */
export function useLichess() {
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);

  const refresh = useCallback(() => {
    api.getAccountStatus().then(setAccount, () => undefined);
    api.getSyncStatus().then(setSync, () => undefined);
  }, []);

  useEffect(() => {
    // Fetch once on mount, then follow pushed events (with a slow poll as a fallback).
    refresh();
    const unsubscribe = api.onEvent((event) => {
      if (event.name === "account") {
        setAccount(event.payload);
        api.getSyncStatus().then(setSync, () => undefined);
      }
      if (event.name === "sync") setSync(event.payload.status);
    });
    const timer = setInterval(refresh, POLL_MS);
    return () => {
      unsubscribe();
      clearInterval(timer);
    };
  }, [refresh]);

  return { account, sync, refresh };
}

/** "1834", or "1500?" while Lichess says it's provisional. */
export function formatRating(account: AccountStatus | null): string | null {
  if (!account || account.state !== "signed_in" || account.rating === null) return null;
  return `${account.rating}${account.provisional ? "?" : ""}`;
}

export function signedRating(diff: number): string {
  return diff > 0 ? `+${diff}` : `−${Math.abs(diff)}`;
}
