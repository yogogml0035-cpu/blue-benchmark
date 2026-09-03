/**
 * Playwright global setup: boot an isolated FastAPI for browser tests.
 *
 * The backend runs from the repo's real code against a throwaway SQLite file
 * (migrated first — the app never creates schema on startup) on a dedicated
 * port. The setup returns a teardown function; Playwright invokes it after the
 * run, killing the whole backend process group and removing the temp dir.
 * (`globalTeardown` as a separate named export from this file is NOT called by
 * Playwright — returning the function from globalSetup is the supported path.)
 */

import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, openSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const BACKEND_PORT = 8123;
/** Persistent location for the isolated backend log so failures are inspectable. */
export const BACKEND_LOG = path.join(tmpdir(), "m0-e2e-backend.log");

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

function killProcessTree(child: ChildProcess | undefined): void {
  if (!child || child.pid === undefined || child.killed) return;
  try {
    // Kill the whole process group: `uv run` spawns the uvicorn child, and a
    // signal to the wrapper alone would orphan it on the port.
    process.kill(-child.pid, "SIGTERM");
  } catch {
    try {
      child.kill("SIGKILL");
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
        // Log so an unexpected squatter is diagnosable rather than silent.
        console.log(`[global-setup] freeing port ${port}: killing PID ${pid}`);
        process.kill(Number(pid), "SIGKILL");
      } catch {
        // already gone
      }
    }
  } catch {
    // lsof found nothing or is unavailable
  }
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  const workDir = mkdtempSync(path.join(tmpdir(), "m0-e2e-backend-"));
  const databaseFile = path.join(workDir, "business.db");
  const repoRoot = path.resolve(process.cwd(), "..");
  const databaseUrl = `sqlite:///${databaseFile}`;
  let backend: ChildProcess | undefined;
  let worker: ChildProcess | undefined;

  const cleanup = async (): Promise<void> => {
    killProcessTree(worker);
    killProcessTree(backend);
    // Give the groups a moment to exit, then hard-free the port as a backstop.
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    freePort(BACKEND_PORT);
    rmSync(workDir, { recursive: true, force: true });
  };

  const childEnv = {
    ...process.env,
    DATABASE_URL: databaseUrl,
    AI_RUNTIME_MODE: "fake",
    SESSION_COOKIE_SECURE: "false",
    DATABASE_SCHEMA_CHECK_ON_STARTUP: "false",
    STORAGE_ROOT: path.join(workDir, "storage"),
  };

  try {
    // Start clean even if a previous run leaked a backend on the port.
    freePort(BACKEND_PORT);

    // Migrate the fresh isolated database before the server starts.
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
        env: childEnv,
        stdio: ["ignore", openSync(BACKEND_LOG, "w"), openSync(BACKEND_LOG, "a")],
      },
    );

    // A fake-mode worker to process rubric-generation jobs so uploaded
    // questions move generating -> pending_review during browser tests.
    worker = spawn("uv", ["run", "python", "-m", "app.lib.operations.worker"], {
      cwd: path.join(repoRoot, "backend"),
      detached: true,
      env: childEnv,
      stdio: "ignore",
    });

    await waitForBackend(`http://127.0.0.1:${BACKEND_PORT}`);
  } catch (error) {
    // Do not leak the process or temp dir when setup itself fails.
    await cleanup();
    throw error;
  }

  return cleanup;
}
