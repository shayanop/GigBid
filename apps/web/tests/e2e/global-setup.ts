import { spawn } from "node:child_process";
import { rmSync } from "node:fs";

// The Arq worker serves no HTTP, so it cannot be a Playwright webServer; start it here
// with the same environment and stop it after the run.
export default async function globalSetup() {
  rmSync("../../data/processed/e2e/workspace", { recursive: true, force: true }); // fresh calendar
  const worker = spawn("uv run python -m worker.main", {
    cwd: "../..",
    env: JSON.parse(process.env.E2E_ENV ?? "{}"),
    stdio: "inherit",
    shell: true, // finds `uv` on PATH on every platform
  });
  return async () => {
    if (process.platform === "win32" && worker.pid) {
      // Through a shell, kill() would stop only the shell; take the whole tree.
      spawn("taskkill", ["/pid", String(worker.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      worker.kill();
    }
  };
}
