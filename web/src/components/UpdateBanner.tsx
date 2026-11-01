import { Alert, Button, Group, Text } from "@mantine/core";
import type { UpdateOffer } from "../api/types";

const mb = (bytes: number) => `${Math.round(bytes / 1_048_576).toLocaleString("en-US")} MB`;
const n = (x: number) => x.toLocaleString("en-US");

/** The banner text, e.g. "A newer puzzle database is available (exported 2026-11-01, yours is from 2026-10-02). Download about 295 MB?" */
export function offerText(o: UpdateOffer): string {
  const dates = o.current_export_date
    ? `exported ${o.export_date}, yours is from ${o.current_export_date}`
    : `exported ${o.export_date}`;
  return `A newer puzzle database is available (${dates}).${o.size ? ` Download about ${mb(o.size)}?` : ""}`;
}

// FR-2.5: a non-blocking banner above the main area, never a dialog mid-puzzle.
export function UpdateBanner({
  offer,
  onUpdate,
  onNotNow,
  onSkip,
}: {
  offer: UpdateOffer;
  onUpdate: () => void;
  onNotNow: () => void;
  onSkip: () => void;
}) {
  return (
    <Alert color="blue" mb="md" data-testid="update-banner" title="Puzzle database update">
      <Text size="sm">{offerText(offer)}</Text>
      {offer.approx_count !== null && (
        <Text size="sm" c="dimmed" data-testid="update-count">
          About {n(offer.approx_count)} puzzles
          {offer.approx_new !== null && offer.approx_new !== 0 && ` (${offer.approx_new > 0 ? "+" : ""}${n(offer.approx_new)})`},
          approximate: Lichess's page can lag behind the file. You'll get the exact numbers after the update.
        </Text>
      )}
      <Group gap="xs" mt="sm">
        <Button size="xs" onClick={onUpdate} data-testid="update-now">
          Update now
        </Button>
        <Button size="xs" variant="default" onClick={onNotNow} data-testid="update-not-now">
          Not now
        </Button>
        <Button size="xs" variant="subtle" onClick={onSkip} data-testid="update-skip">
          Skip this export
        </Button>
      </Group>
    </Alert>
  );
}
