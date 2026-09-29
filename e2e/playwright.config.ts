import { defineConfig } from "@playwright/test";

// E2E suite: requires the full stack running (backend :8000 with a real DB +
// configured providers, frontend dev server :5173). Not executed in CI without
// those dependencies — see README "Tests".
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  use: {
    baseURL: "http://localhost:5173",
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
