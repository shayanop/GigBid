import { defineConfig, devices } from "@playwright/test";

// End-to-end runs start the whole stack on their own ports (so they can run next to the
// dev stack) against the test database, with the scripted `fake` model profile.
// Needs Postgres and Redis (docker compose ... up -d postgres redis) and TEST_* in ../../.env.
try {
  process.loadEnvFile("../../.env");
} catch {
  // CI provides the variables directly.
}

const ROOT = "../..";
const PORTS = { web: 3010, api: 8010, gigsim: 8110, marketplace: 8210, portfolio: 8310, workspace: 8410 };
const env = {
  ...process.env,
  GIGBID_PROFILE: "fake",
  DATABASE_URL: process.env.TEST_DATABASE_URL ?? "",
  REDIS_URL: "redis://localhost:6379/14",
  SESSION_SECRET: "e2e-session-secret-0123456789",
  MCP_SIGNING_SECRET: "e2e-signing-secret",
  GIGSIM_URL: `http://localhost:${PORTS.gigsim}`,
  MARKETPLACE_MCP_URL: `http://localhost:${PORTS.marketplace}/mcp`,
  PORTFOLIO_MCP_URL: `http://localhost:${PORTS.portfolio}/mcp`,
  WORKSPACE_MCP_URL: `http://localhost:${PORTS.workspace}/mcp`,
  WORKSPACE_DIR: "data/processed/e2e/workspace",
  MARKETPLACE_AUDIT_LOG: "data/processed/audit/e2e.jsonl",
  MARKETPLACE_RATE_PER_MIN: "1000",
} as Record<string, string>;

const python = (command: string, port: number, extra: Record<string, string> = {}) => ({
  command: `uv run ${command}`,
  cwd: ROOT,
  env: { ...env, PORT: String(port), ...extra },
  port,
  reuseExistingServer: false,
  timeout: 120_000,
});

process.env.E2E_ENV = JSON.stringify(env); // read by global-setup.ts to start the worker

export default defineConfig({
  globalSetup: "./tests/e2e/global-setup.ts",
  testDir: "tests/e2e",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: `http://localhost:${PORTS.web}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    python(`uvicorn gigsim.app:create_app --factory --port ${PORTS.gigsim}`, PORTS.gigsim),
    python("python -m mcp_servers.marketplace.server", PORTS.marketplace),
    python("python -m mcp_servers.portfolio.server", PORTS.portfolio),
    python("python -m mcp_servers.workspace.server", PORTS.workspace),
    // psycopg async needs the selector loop; uvicorn picks Proactor on Windows.
    python(`uvicorn apps.api.main:app --port ${PORTS.api} --loop asyncio:SelectorEventLoop`, PORTS.api),
    {
      command: `npx next build && npx next start --port ${PORTS.web}`,
      env: { ...env, API_URL: `http://localhost:${PORTS.api}`, NEXT_DIST_DIR: ".next-e2e" },
      port: PORTS.web,
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
