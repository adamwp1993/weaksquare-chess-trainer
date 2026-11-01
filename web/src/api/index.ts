import type { ApiClient } from "./ApiClient";
import { MockClient } from "./mockClient";
import { PywebviewClient } from "./pywebviewClient";

// `vite build --mode mock` (Playwright, screenshots) and `vite --mode mock` use the mock client.
export const api: ApiClient = import.meta.env.MODE === "mock" ? new MockClient() : new PywebviewClient();

// Mock builds only: Playwright reads what the UI sent through the (mock) bridge, e.g. saved settings.
if (import.meta.env.MODE === "mock") (window as unknown as { __mockApi: ApiClient }).__mockApi = api;

export { ApiCallError } from "./ApiClient";
export type { ApiClient, BackendEvent } from "./ApiClient";
