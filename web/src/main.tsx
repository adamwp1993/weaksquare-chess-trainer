import "@mantine/core/styles.css";
import "@mantine/charts/styles.css";
import { MantineProvider, createTheme, type CSSVariablesResolver, type MantineColorScheme } from "@mantine/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import { App } from "./App";
import { bridgeColorSchemeManager } from "./state/colorScheme";

// NFR-4: forward front-end errors to the log file, rate-limited on both sides.
let forwarded = 0;
function forward(message: string, source: string) {
  if (forwarded++ > 50) return;
  api.logFrontendError(message.slice(0, 2000), source.slice(0, 200)).catch(() => undefined);
}
window.addEventListener("error", (e) => forward(String(e.message), `${e.filename}:${e.lineno}`));
window.addEventListener("unhandledrejection", (e) => forward(String(e.reason), "unhandledrejection"));

// FR-1.12: text keeps WCAG AA contrast in both schemes (tests/e2e/test_appearance.py checks every
// screen). Mantine's teal-6/teal-8 buttons and its "dimmed" grey fall short of 4.5:1, so filled
// buttons use teal-9 and dimmed text is darker in light mode and lighter in dark mode.
const theme = createTheme({ primaryColor: "teal", primaryShade: { light: 9, dark: 9 }, defaultRadius: "md" });

const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    "--mantine-color-dimmed": "#5f6870", // 5.7:1 on white
    "--mantine-primary-color-filled-hover": "#066649", // hover darkens instead of lightening to teal-8
    "--mantine-color-teal-light-color": "#066649", // light badges (themes): 6:1 on their pale teal
    "--mantine-primary-color-light-color": "#066649",
    "--mantine-color-green-text": "#2b7a3b", // "Correct" / "Solved": 5.3:1 (Mantine's is 4.4:1)
    "--mantine-color-yellow-light-color": "#7a4a00", // the sync chip (v0.3): 6.7:1 on its pale yellow
  },
  dark: {
    "--mantine-color-dimmed": "#a3a3a3", // 6.0:1 on the dark background
    "--mantine-primary-color-filled-hover": "#066649",
  },
});

// FR-1.12: wait for the saved color scheme before the first render, so the app starts in it. The
// window behind the page is already painted in that scheme by app.py, so nothing flashes meanwhile.
const SETTINGS_WAIT_MS = 1500;

async function initialScheme(): Promise<MantineColorScheme> {
  const timeout = new Promise<MantineColorScheme>((resolve) => setTimeout(() => resolve("light"), SETTINGS_WAIT_MS));
  const saved = api.getSettings().then(
    (s) => s.color_scheme,
    () => "light" as const,
  );
  return Promise.race([saved, timeout]);
}

initialScheme().then((scheme) => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <MantineProvider
        theme={theme}
        cssVariablesResolver={cssVariablesResolver}
        colorSchemeManager={bridgeColorSchemeManager(scheme)}
        defaultColorScheme={scheme}
      >
        <App />
      </MantineProvider>
    </StrictMode>,
  );
});
