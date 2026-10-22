/**
 * End-to-end tests. Self-contained: Playwright starts its own SAP mock, API
 * and web server on separate ports (8101, 8100, 3100) and stops them when the
 * run ends, so it never clashes with `make dev` on 8001 / 8000 / 3000.
 *
 *   pnpm e2e                 all specs
 *   pnpm e2e -- dup-panel    one spec
 */
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const WEB_PORT = 3100;
const API_PORT = 8100;
const SAP_PORT = 8101;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: [
    {
      name: "sap-mock",
      command: `uv run uvicorn services.sap_mock.main:app --port ${SAP_PORT}`,
      cwd: REPO_ROOT,
      url: `http://localhost:${SAP_PORT}/b1s/v2/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      name: "api",
      command: "node apps/web/e2e/start-api.mjs",
      cwd: REPO_ROOT,
      env: { E2E_API_PORT: String(API_PORT), E2E_SAP_PORT: String(SAP_PORT) },
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      name: "web",
      command: `pnpm exec next dev --port ${WEB_PORT}`,
      cwd: __dirname,
      // Own build folder, so it does not collide with a `next dev` already running here.
      env: { API_ORIGIN: `http://localhost:${API_PORT}`, NEXT_DIST_DIR: ".next-e2e" },
      url: `http://localhost:${WEB_PORT}/requests/new`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
