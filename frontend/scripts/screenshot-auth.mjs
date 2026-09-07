import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(frontendRoot, "test-results", "visual");
mkdirSync(outDir, { recursive: true });

const BACKEND_PORT = 8123;
const workDir = mkdtempSync(path.join(tmpdir(), "m0-visual-"));
const databaseUrl = `sqlite:///${path.join(workDir, "business.db")}`;

function freePort(port) {
  try {
    const out = execFileSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], {
      stdio: ["ignore", "pipe", "ignore"],
    }).toString().trim();
    for (const pid of out.split("\n")) if (pid) try { process.kill(Number(pid), "SIGKILL"); } catch {}
  } catch {}
}

async function waitFor(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`not ready: ${url}`);
}

freePort(BACKEND_PORT);
freePort(3000);

execFileSync("uv", ["run", "alembic", "upgrade", "head"], {
  cwd: path.join(repoRoot, "backend"),
  env: { ...process.env, ALEMBIC_DATABASE_URL: databaseUrl },
  stdio: "pipe",
});

const backend = spawn("uv", ["run", "--project", "backend", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", String(BACKEND_PORT)], {
  cwd: repoRoot,
  detached: true,
  env: { ...process.env, DATABASE_URL: databaseUrl, AI_RUNTIME_MODE: "fake", SESSION_COOKIE_SECURE: "false", DATABASE_SCHEMA_CHECK_ON_STARTUP: "false", STORAGE_ROOT: path.join(workDir, "storage") },
  stdio: "ignore",
});
await waitFor(`http://127.0.0.1:${BACKEND_PORT}/healthz`);

const next = spawn("pnpm", ["start"], {
  cwd: frontendRoot,
  detached: true,
  env: { ...process.env, BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}` },
  stdio: "ignore",
});
await waitFor("http://127.0.0.1:3000/login");

const browser = await chromium.launch();
const shots = [];
for (const [name, viewport] of [["1440x900", { width: 1440, height: 900 }], ["1280x720", { width: 1280, height: 720 }]]) {
  for (const route of ["login"]) {
    const page = await browser.newPage({ viewport });
    await page.goto(`http://127.0.0.1:3000/${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    const file = path.join(outDir, `${route}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    shots.push(file);
    await page.close();
  }
}
await browser.close();

try { process.kill(-backend.pid, "SIGTERM"); } catch {}
try { process.kill(-next.pid, "SIGTERM"); } catch {}
await new Promise((r) => setTimeout(r, 1200));
freePort(BACKEND_PORT);
freePort(3000);
rmSync(workDir, { recursive: true, force: true });

console.log(shots.join("\n"));
