import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Strict Content Security Policy for built bundles (SR-3). Not applied to the dev server, whose
// hot-reload client needs inline scripts and a websocket.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "media-src 'self'", // the bundled move sounds (FR-1.13)
  "font-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

function cspPlugin(): Plugin {
  return {
    name: "weaksquare-csp",
    apply: "build",
    transformIndexHtml(html) {
      return html.replace(
        "<head>",
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`,
      );
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), cspPlugin()],
  build: { assetsInlineLimit: 0, sourcemap: false },
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
});
