import { Badge, Button, Group, Paper, Text } from "@mantine/core";

// FR-1.14: the filters panel, collapsed. Show filters brings the full panel back exactly as it was.
export function FiltersStrip({ summary, rated, onExpand }: { summary: string; rated: boolean; onExpand: () => void }) {
  return (
    <Paper withBorder radius="md" p="xs" data-testid="filters-strip">
      <Group justify="space-between" wrap="nowrap" gap="sm">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <Button size="xs" variant="light" onClick={onExpand} title="Show filters (F)" data-testid="show-filters">
            » Show filters
          </Button>
          <Text size="sm" truncate data-testid="filters-summary">
            {summary}
          </Text>
        </Group>
        <Badge variant="light" color={rated ? "blue" : "gray"} style={{ textTransform: "none", flexShrink: 0 }}>
          {rated ? "Rated" : "Unrated"}
        </Badge>
      </Group>
    </Paper>
  );
}
