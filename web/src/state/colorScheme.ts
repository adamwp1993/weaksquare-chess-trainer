import type { MantineColorScheme, MantineColorSchemeManager } from "@mantine/core";
import { api } from "../api";

// FR-1.12: Mantine's default color-scheme manager keeps the choice in browser storage, which this
// app never uses (ARCHITECTURE §3 decision 14). This one keeps it in memory and saves it through
// the bridge into user.db. "auto" is Match system: Mantine follows prefers-color-scheme, which WebView2
// updates live when the Windows theme changes.
export function bridgeColorSchemeManager(initial: MantineColorScheme): MantineColorSchemeManager {
  let current = initial;
  return {
    get: () => current,
    set: (value) => {
      if (value === current) return;
      current = value;
      api.setSetting("ui.color_scheme", value).catch(() => undefined);
    },
    subscribe: () => undefined,
    unsubscribe: () => undefined,
    clear: () => undefined,
  };
}
