/**
 * End-to-end tests. Self-contained: Playwright starts its own SAP mock, API
 * and web server on separate ports (8101, 8100, 3100) and stops them when the
 * run ends, so it never clashes with `make dev` on 8001 / 8000 / 3000.
 *
 *   pnpm e2e                 all specs
 *   pnpm e2e -- dup-panel    one spec
 *   E2E_WEB_PORT / E2E_API_PORT / E2E_SAP_PORT move the ports (two worktrees at once)
 */
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const API_PORT = Number(process.env.E2E_API_PORT ?? 8100);
const SAP_PORT = Number(process.env.E2E_SAP_PORT ?? 8101);

export default defineConfig({
  testDir: "./e2e",
  // The timed demo walkthrough is a rehearsal tool, run only by `make rehearse` (D-021);
  // the theme screenshots only by `make theme-shots` (D-022 #5).
  testIgnore: [
    ...(process.env.REHEARSE ? [] : ["**/walkthrough.spec.ts"]),
    ...(process.env.THEME_SHOTS ? [] : ["**/theme-shots.spec.ts"]),
  ],
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
      // Keep-alive past httpx's 5 s idle pool (D-025; same value as the Makefile).
      command: `uv run uvicorn services.sap_mock.main:app --port ${SAP_PORT} --timeout-keep-alive 75`,
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
      // Node's own entry point, not `pnpm exec`: the pnpm/.cmd shims break under Windows bash.
      command: `"${process.execPath}" node_modules/next/dist/bin/next dev --port ${WEB_PORT}`,
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
