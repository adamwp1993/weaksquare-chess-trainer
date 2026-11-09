// The move list with nested side lines (v0.14, FR-13.8), shared by a study chapter and the Analysis tab (v0.15,
// FR-14.4). Comments are plain text: React escapes them, and they're never turned into links (FR-13.7).
import { Box, ScrollArea, Text } from "@mantine/core";
import { type ReactNode, useEffect, useRef } from "react";
import type { StudyMove } from "../api/types";
import { moveNumber, nagText } from "../state/studyTree";

/** The move list with nested side lines, as on Lichess: inline main line, side lines indented underneath. */
export function MoveTree({
  moves,
  cur,
  onSelect,
  testIdPrefix = "study",
  emptyText = "No moves in this chapter.",
  maxHeight = 460,
}: {
  moves: StudyMove[];
  cur: number;
  onSelect: (id: number) => void;
  /** "study" (FR-13.8) or "analysis" (FR-14.4): the test ids' prefix. */
  testIdPrefix?: string;
  emptyText?: string;
  maxHeight?: number;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    viewport.current
      ?.querySelector(`[data-move-id="${cur}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [cur]);
  const root = moves[0];
  return (
    <ScrollArea.Autosize mah={maxHeight} viewportRef={viewport} type="auto">
      <Box data-testid={`${testIdPrefix}-moves`} style={{ lineHeight: 1.9 }}>
        {root.comment && <Comment text={root.comment} prefix={testIdPrefix} />}
        {root.children.length ? (
          renderLine(moves, 0, root.children[0], cur, onSelect, testIdPrefix)
        ) : (
          <Text size="sm" c="dimmed">
            {emptyText}
          </Text>
        )}
      </Box>
    </ScrollArea.Autosize>
  );
}

function renderLine(
  moves: StudyMove[],
  parent: number,
  first: number,
  cur: number,
  onSelect: (id: number) => void,
  prefix: string,
): ReactNode[] {
  const out: ReactNode[] = [];
  let p = parent;
  let id: number | undefined = first;
  let needNumber = true;
  while (id !== undefined) {
    const n: StudyMove = moves[id];
    const { number, white } = moveNumber(moves, id);
    out.push(
      <MoveSpan
        key={`m${id}`}
        move={n}
        label={white ? `${number}. ` : needNumber ? `${number}… ` : ""}
        active={id === cur}
        onSelect={onSelect}
        prefix={prefix}
      />,
    );
    needNumber = false;
    if (n.comment) {
      out.push(<Comment key={`c${id}`} text={n.comment} prefix={prefix} />);
      needNumber = true;
    }
    const siblings = moves[p].children;
    if (siblings[0] === id && siblings.length > 1) {
      for (const sib of siblings.slice(1)) {
        out.push(
          <Box
            key={`v${sib}`}
            pl="md"
            my={2}
            style={{
              borderLeft: "2px solid var(--mantine-color-default-border)",
            }}
            data-testid={`${prefix}-variation`}
          >
            {renderLine(moves, p, sib, cur, onSelect, prefix)}
          </Box>,
        );
      }
      needNumber = true;
    }
    p = id;
    id = n.children[0];
  }
  return out;
}

function MoveSpan({
  move,
  label,
  active,
  onSelect,
  prefix,
}: {
  move: StudyMove;
  label: string;
  active: boolean;
  onSelect: (id: number) => void;
  prefix: string;
}) {
  return (
    <Text
      component="span"
      size="sm"
      fw={active ? 700 : 400}
      px={3}
      mr={2}
      bg={active ? "var(--mantine-primary-color-light)" : undefined}
      style={{ cursor: "pointer", borderRadius: 4, whiteSpace: "nowrap" }}
      onClick={() => onSelect(move.id)}
      data-move-id={move.id}
      data-testid={active ? `${prefix}-current-move` : undefined}
      aria-current={active ? "step" : undefined}
    >
      {label}
      {move.san}
      {nagText(move.nags)}
    </Text>
  );
}

function Comment({ text, prefix }: { text: string; prefix: string }) {
  return (
    <Text
      component="span"
      size="sm"
      c="dimmed"
      mx={4}
      style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
      data-testid={`${prefix}-inline-comment`}
    >
      {text}{" "}
    </Text>
  );
}
