import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Browser tests of the whole application (e2e/): a real browser against the API on a new SQLite store, set up
// by scripts/e2e_server.py, serving the built web application. Build it first: npm run build.
const PORT = 8011;

export default defineConfig({
  testDir: "./e2e",
  // Traces and screenshots of failures: in the repository on CI (kept as an artifact), in the temporary folder
  // elsewhere, where a synced folder (OneDrive) can hold the old files while Playwright clears them.
  outputDir: process.env.CI ? "test-results" : join(tmpdir(), "auditiq-e2e-results"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 60_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `python ../scripts/e2e_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 300_000,
    stdout: "pipe",
  },
});
