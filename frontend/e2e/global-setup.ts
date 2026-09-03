/**
 * Playwright global setup: boot an isolated FastAPI for browser tests.
 *
 * The backend runs from the repo's real code against a throwaway SQLite file
 * in fake AI mode, on a dedicated port. Next.js (started by Playwright's
 * webServer) proxies /api to it via BACKEND_URL. The process is torn down
 * after the run; nothing touches the development database.
 */

import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, openSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const BACKEND_PORT = 8123;
/** Persistent location for the isolated backend log so failures are inspectable. */
export const BACKEND_LOG = path.join(tmpdir(), "m0-e2e-backend.log");
let backend: ChildProcess | undefined;
let workDir: string | undefined;

async function waitForBackend(base: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/healthz`);
      if (response.ok) return;
    } catch {
      // still starting
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`isolated backend did not become ready at ${base}`);
}

function killBackend(): void {
  if (!backend || backend.pid === undefined || backend.killed) return;
  try {
    // Kill the whole process group: `uv run` spawns the uvicorn child, and a
    // signal to the wrapper alone would orphan it on the port.
    process.kill(-backend.pid, "SIGTERM");
  } catch {
    try {
      backend.kill("SIGKILL");
    } catch {
      // already gone
    }
  }
}

/** Defensive: free the backend port in case a previous run leaked a process. */
function freePort(port: number): void {
  try {
    const out = execFileSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
    for (const pid of out.split("\n")) {
      if (!pid) continue;
      try {
        process.kill(Number(pid), "SIGKILL");
      } catch {
        // already gone
      }
    }
  } catch {
    // lsof found nothing or is unavailable
  }
}

export default async function globalSetup(): Promise<void> {
  workDir = mkdtempSync(path.join(tmpdir(), "m0-e2e-backend-"));
  const databaseFile = path.join(workDir, "business.db");
  const repoRoot = path.resolve(process.cwd(), "..");
  const databaseUrl = `sqlite:///${databaseFile}`;

  // Start clean even if a previous run leaked a backend on the port.
  freePort(BACKEND_PORT);

  // Migrate the fresh isolated database before the server starts; the app
  // itself never creates schema on startup.
  execFileSync("uv", ["run", "alembic", "upgrade", "head"], {
    cwd: path.join(repoRoot, "backend"),
    env: { ...process.env, ALEMBIC_DATABASE_URL: databaseUrl },
    stdio: "pipe",
  });

  backend = spawn(
    "uv",
    ["run", "--project", "backend", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", String(BACKEND_PORT)],
    {
      cwd: repoRoot,
      detached: true,
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        AI_RUNTIME_MODE: "fake",
        SESSION_COOKIE_SECURE: "false",
        DATABASE_SCHEMA_CHECK_ON_STARTUP: "false",
        STORAGE_ROOT: path.join(workDir, "storage"),
      },
      stdio: ["ignore", openSync(BACKEND_LOG, "w"), openSync(BACKEND_LOG, "a")],
    },
  );

  await waitForBackend(`http://127.0.0.1:${BACKEND_PORT}`);
}

export async function globalTeardown(): Promise<void> {
  killBackend();
  await new Promise((resolve) => setTimeout(resolve, 1_500));
  freePort(BACKEND_PORT);
  if (workDir) {
    rmSync(workDir, { recursive: true, force: true });
  }
}
