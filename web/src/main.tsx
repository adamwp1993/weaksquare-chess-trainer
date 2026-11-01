import "@mantine/core/styles.css";
import { MantineProvider, createTheme } from "@mantine/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import { App } from "./App";

// NFR-4: forward front-end errors to the log file, rate-limited on both sides.
let forwarded = 0;
function forward(message: string, source: string) {
  if (forwarded++ > 50) return;
  api.logFrontendError(message.slice(0, 2000), source.slice(0, 200)).catch(() => undefined);
}
window.addEventListener("error", (e) => forward(String(e.message), `${e.filename}:${e.lineno}`));
window.addEventListener("unhandledrejection", (e) => forward(String(e.reason), "unhandledrejection"));

const theme = createTheme({ primaryColor: "teal", defaultRadius: "md" });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <App />
    </MantineProvider>
  </StrictMode>,
);
