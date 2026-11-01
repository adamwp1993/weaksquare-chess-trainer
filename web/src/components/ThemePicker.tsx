import { Badge, Button, Checkbox, Group, Popover, ScrollArea, Stack, Text, TextInput } from "@mantine/core";
import { useMemo, useState } from "react";
import type { ThemeGroup } from "../api/types";

// FR-3.1 / FR-3.2: a dropdown of grouped checkboxes with search and Select all / Clear.
// Used twice: for the themes to include, and for the themes to exclude.
export function ThemePicker({
  label,
  catalog,
  value,
  onChange,
  emptyLabel,
  testId,
}: {
  label: string;
  catalog: ThemeGroup[];
  value: string[];
  onChange: (themes: string[]) => void;
  emptyLabel: string;
  testId: string;
}) {
  const [search, setSearch] = useState("");
  const selected = new Set(value);
  const names = useMemo(
    () => new Map(catalog.flatMap((g) => g.themes.map((t) => [t.key, t.name] as const))),
    [catalog],
  );

  const q = search.trim().toLowerCase();
  const visible = catalog
    .map((g) => ({ ...g, themes: g.themes.filter((t) => !q || t.name.toLowerCase().includes(q) || t.key.toLowerCase().includes(q)) }))
    .filter((g) => g.themes.length > 0);
  const visibleKeys = visible.flatMap((g) => g.themes.map((t) => t.key));

  const toggle = (key: string) => {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange([...next]);
  };

  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        {label}
      </Text>
      <Popover width={360} position="bottom-start" shadow="md" trapFocus>
        <Popover.Target>
          <Button variant="default" fullWidth justify="space-between" data-testid={testId}>
            {value.length === 0 ? emptyLabel : `${value.length} selected`}
          </Button>
        </Popover.Target>
        <Popover.Dropdown>
          <Stack gap="xs">
            <TextInput
              placeholder="Search themes"
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
              aria-label={`Search ${label.toLowerCase()}`}
            />
            <Group gap="xs">
              <Button size="compact-xs" variant="light" onClick={() => onChange([...new Set([...value, ...visibleKeys])])}>
                Select all
              </Button>
              <Button size="compact-xs" variant="subtle" onClick={() => onChange([])}>
                Clear
              </Button>
            </Group>
            <ScrollArea.Autosize mah={340} type="auto">
              <Stack gap="sm">
                {visible.map((g) => (
                  <Stack gap={4} key={g.name}>
                    <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                      {g.name}
                    </Text>
                    {g.themes.map((t) => (
                      <Checkbox
                        key={t.key}
                        size="xs"
                        checked={selected.has(t.key)}
                        onChange={() => toggle(t.key)}
                        label={
                          <Group gap={6} wrap="nowrap">
                            <span>{t.name}</span>
                            <Text span size="xs" c="dimmed">
                              {t.count.toLocaleString("en-US")}
                            </Text>
                          </Group>
                        }
                      />
                    ))}
                  </Stack>
                ))}
                {visible.length === 0 && (
                  <Text size="sm" c="dimmed">
                    No theme matches “{search}”.
                  </Text>
                )}
              </Stack>
            </ScrollArea.Autosize>
          </Stack>
        </Popover.Dropdown>
      </Popover>
      {value.length > 0 && (
        <Group gap={4}>
          {value.map((k) => (
            <Badge key={k} variant="light" size="sm" style={{ textTransform: "none" }}>
              {names.get(k) ?? k}
            </Badge>
          ))}
        </Group>
      )}
    </Stack>
  );
}
