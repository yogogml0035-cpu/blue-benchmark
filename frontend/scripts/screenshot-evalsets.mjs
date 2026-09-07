import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, openSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(frontendRoot, "test-results", "visual");
const BACKEND_PORT = 8123;

const workDir = mkdtempSync(path.join(tmpdir(), "m0-visual-evalset-"));
const databaseUrl = `sqlite:///${path.join(workDir, "business.db")}`;

function freePort(port) {
  try {
    const out = execFileSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
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

freePort(BACKEND_PORT); freePort(3000);
execFileSync("uv", ["run", "alembic", "upgrade", "head"], { cwd: path.join(repoRoot, "backend"), env: { ...process.env, ALEMBIC_DATABASE_URL: databaseUrl }, stdio: "pipe" });
const backend = spawn("uv", ["run", "--project", "backend", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", String(BACKEND_PORT)], {
  cwd: repoRoot, detached: true,
  env: { ...process.env, DATABASE_URL: databaseUrl, AI_RUNTIME_MODE: "fake", SESSION_COOKIE_SECURE: "false", DATABASE_SCHEMA_CHECK_ON_STARTUP: "false", STORAGE_ROOT: path.join(workDir, "storage"), ADMIN_USERNAME: "visual-admin", ADMIN_PASSWORD: "visual-admin-password-1" },
  stdio: "ignore",
});
await waitFor(`http://127.0.0.1:${BACKEND_PORT}/healthz`);
const next = spawn("pnpm", ["start"], { cwd: frontendRoot, detached: true, env: { ...process.env, BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}`, NEXT_PUBLIC_AGENT_API_BASE_URL: "http://127.0.0.1:8000" }, stdio: "ignore" });
await waitFor("http://127.0.0.1:3000/login");

// The admin is seeded from ADMIN_USERNAME / ADMIN_PASSWORD on backend startup;
// log in and create a handful of evaluation sets through the real API.
const base = `http://127.0.0.1:${BACKEND_PORT}`;
const reg = await fetch(`${base}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier: "visual-admin", password: "visual-admin-password-1" }) });
const cookie = reg.headers.get("set-cookie").split(";")[0];
const names = ["媒体改写评测集", "会议纪要评测集", "客服问答评测集", "代码审查评测集", "翻译质量评测集", "摘要生成评测集", "数据抽取评测集", "营销文案评测集"];
for (const name of names) {
  await fetch(`${base}/api/scenes`, { method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie }, body: JSON.stringify({ name, description: "用于验证文件夹卡片视觉与连接状态的示例评测集。" }) });
}

const browser = await chromium.launch();
const shots = [];
for (const [label, viewport] of [["1440x900", { width: 1440, height: 900 }], ["1280x720", { width: 1280, height: 720 }]]) {
  const context = await browser.newContext({ viewport });
  await context.addCookies([{ name: cookie.split("=")[0], value: cookie.split("=")[1], url: "http://127.0.0.1:3000" }]);
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:3000/evaluation-sets", { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  const listShot = path.join(outDir, `evalsets-list-${label}.png`);
  await page.screenshot({ path: listShot, fullPage: false });
  shots.push(listShot);
  // Open the first folder for the detail view.
  await page.locator('a[href^="/evaluation-sets/"]').first().click();
  await page.waitForTimeout(1000);
  const detailShot = path.join(outDir, `evalset-detail-${label}.png`);
  await page.screenshot({ path: detailShot, fullPage: false });
  shots.push(detailShot);
  await context.close();
}
await browser.close();

try { process.kill(-backend.pid, "SIGTERM"); } catch {}
try { process.kill(-next.pid, "SIGTERM"); } catch {}
await new Promise((r) => setTimeout(r, 1200));
freePort(BACKEND_PORT); freePort(3000);
rmSync(workDir, { recursive: true, force: true });
console.log(shots.join("\n"));
