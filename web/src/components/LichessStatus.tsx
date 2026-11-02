import { Badge, Group, Loader, Text, Tooltip } from "@mantine/core";
import type { AccountStatus, AttemptRating, SyncStatus } from "../api/types";
import { formatRating, signedRating } from "../state/lichess";

// The header: your Lichess puzzle rating (FR-6.11a, only as Lichess reported it, and only when
// signed in) and the sync queue (FR-1.7: "Offline: N solves waiting to sync").
export function LichessStatus({ account, sync }: { account: AccountStatus | null; sync: SyncStatus | null }) {
  const rating = formatRating(account);
  const pending = sync?.pending ?? 0;
  let chip: string | null = null;
  if (sync?.state === "syncing" && pending > 0) chip = "Syncing…";
  else if (pending > 0 && sync?.state === "waiting") chip = `Lichess asked us to slow down: ${pending} waiting`;
  else if (pending > 0 && account?.state !== "signed_in")
    chip = `${account?.state === "offline" ? "Offline" : "Not signed in"}: ${pending} ${pending === 1 ? "solve" : "solves"} waiting to sync`;
  else if (pending > 0 && sync?.state === "offline") chip = `Offline: ${pending} ${pending === 1 ? "solve" : "solves"} waiting to sync`;
  return (
    <Group gap="sm">
      {chip && (
        <Badge variant="light" color="yellow" style={{ textTransform: "none" }} data-testid="sync-chip">
          {chip}
        </Badge>
      )}
      {rating && (
        <Tooltip label={`Your Lichess puzzle rating (${account?.username})`}>
          <Text fw={600} data-testid="header-rating">
            Puzzle rating {rating}
          </Text>
        </Tooltip>
      )}
    </Group>
  );
}

const THEMED_TIP =
  "Lichess weighs a solve by what you knew in advance: a themed session (e.g. only forks) counts for much less than a mix, so small changes there are expected.";

// FR-6.11b: the rating change for one puzzle on the result panel, or why there isn't one.
export function RatingChange({ info }: { info: AttemptRating | null }) {
  if (!info) return null;
  let body;
  switch (info.status) {
    case "done":
      body = (
        <Text fw={700} c={info.diff !== null && info.diff > 0 ? "green" : "red"} data-testid="rating-change">
          {signedRating(info.diff ?? 0)}
        </Text>
      );
      break;
    case "syncing":
      body = (
        <Group gap={6} data-testid="rating-change">
          <Loader size="xs" />
          <Text size="sm">Syncing…</Text>
        </Group>
      );
      break;
    case "offline":
      body = <Text size="sm" data-testid="rating-change">Will sync later</Text>;
      break;
    case "unrated":
      body = <Text size="sm" data-testid="rating-change">Unrated (Rated is off)</Text>;
      break;
    case "already_played":
      body = <Text size="sm" data-testid="rating-change">Already played: rating unaffected</Text>;
      break;
    default:
      body = <Text size="sm" data-testid="rating-change">Not rated by Lichess</Text>;
  }
  return (
    <Tooltip label={THEMED_TIP} multiline w={260}>
      <Group gap={6}>
        <Text size="sm">Lichess rating:</Text>
        {body}
      </Group>
    </Tooltip>
  );
}
