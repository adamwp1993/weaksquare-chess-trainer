import { Badge, Tooltip } from "@mantine/core";
import { dollars, useLlmSettings } from "../state/llm";

// FR-1.10: this month's AI spend against the budget, whenever an AI provider is set up with a key.
// Yellow from 80%, red at 100% (when Explain is off, FR-8.13). Clicking it opens Settings.
export function SpendIndicator({ onOpen }: { onOpen: () => void }) {
  const settings = useLlmSettings();
  const spend = settings?.spend;
  if (!spend?.configured) return null;
  const color = spend.level === "over" ? "red" : spend.level === "warn" ? "yellow" : "gray";
  const tip =
    spend.level === "over"
      ? "This month's AI budget is used up: Explain is off until next month or until you raise the budget."
      : spend.level === "warn"
        ? "Over 80% of this month's AI budget."
        : "This month's AI spend. Click to change the budget.";
  return (
    <Tooltip label={tip} multiline w={240}>
      <Badge
        component="button"
        variant="light"
        color={color}
        style={{ textTransform: "none", cursor: "pointer" }}
        onClick={onOpen}
        data-testid="spend-indicator"
        data-level={spend.level}
      >
        AI {dollars(spend.spent_usd)} / {dollars(spend.budget_usd)}
      </Badge>
    </Tooltip>
  );
}
