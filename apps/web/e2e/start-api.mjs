/**
 * Playwright webServer launcher for the API (port 8100).
 *
 * 1. Loads FIELD_ENCRYPTION_KEY (and friends) from the repo `.env` with
 *    Node's own loader. Values are never printed.
 * 2. Seeds a separate database, data/e2e.db, so a running dev setup is untouched.
 * 3. Starts uvicorn and stays in the foreground; Playwright stops the whole
 *    process tree when the run ends.
 */
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..", "..");
const port = process.env.E2E_API_PORT ?? "8100";
const sapPort = process.env.E2E_SAP_PORT ?? "8101";
const dbPath = "data/e2e.db";

/** The repo `.env`; in a git worktree it lives in the main checkout. */
function findEnvFile() {
  const local = path.join(repoRoot, ".env");
  if (existsSync(local)) return local;
  try {
    const common = execFileSync(
      "git",
      ["rev-parse", "--path-format=absolute", "--git-common-dir"],
      {
        cwd: repoRoot,
        encoding: "utf8",
      },
    ).trim();
    const main = path.join(path.dirname(common), ".env");
    if (existsSync(main)) return main;
  } catch {
    // Not a git checkout: fall through.
  }
  return null;
}

const envFile = findEnvFile();
if (envFile) process.loadEnvFile(envFile);

// .env.example uses inline comments; strip any that the loader kept.
for (const key of ["FIELD_ENCRYPTION_KEY", "LLM_MODEL_FAST", "LLM_MODEL_JUDGE"]) {
  const v = process.env[key];
  if (v) process.env[key] = v.replace(/\s+#.*$/, "").trim();
}
if (!process.env.FIELD_ENCRYPTION_KEY) {
  console.error("[e2e api] FIELD_ENCRYPTION_KEY is not set: add it to the repo .env.");
  process.exit(1);
}

const env = {
  ...process.env,
  APP_DB_PATH: dbPath,
  LLM_MODE: "replay",
  SAP_BASE_URL: `http://localhost:${sapPort}/b1s/v2`,
};

const seed = spawnSync(
  "uv",
  [
    "run",
    "python",
    "-m",
    "services.api.db.seed",
    "--fixtures",
    "data/fixtures/seasonal_trend",
    "--db",
    dbPath,
  ],
  { cwd: repoRoot, env, stdio: "inherit" },
);
if (seed.status !== 0) {
  console.error("[e2e api] seeding data/e2e.db failed");
  process.exit(seed.status ?? 1);
}

// --timeout-keep-alive: longer than the Next proxy's 5 s idle pool, or a reused socket that
// uvicorn is closing comes back as a 500 "socket hang up" (D-025; same value as the Makefile).
const uvicorn = ["run", "uvicorn", "services.api.main:app", "--port", port];
const server = spawn("uv", [...uvicorn, "--timeout-keep-alive", "75"], {
  cwd: repoRoot,
  env,
  stdio: "inherit",
});

const stop = () => {
  if (!server.killed) server.kill();
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
process.on("exit", stop);
server.on("exit", (code) => process.exit(code ?? 0));
