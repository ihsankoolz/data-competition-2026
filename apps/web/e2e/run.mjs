/**
 * `pnpm e2e [-- <filter>...]`: runs `playwright test`. pnpm passes a literal
 * "--" through, which would make Playwright ignore the filter, so drop it.
 */
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const cli = require.resolve("@playwright/test/cli");
const args = process.argv.slice(2).filter((a) => a !== "--");

const result = spawnSync(process.execPath, [cli, "test", ...args], { stdio: "inherit" });
process.exit(result.status ?? 1);
