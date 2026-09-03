import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(frontendRoot, "test-results", "visual");
const API_PORT = 8210;
const WEB_PORT = 3210;
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const WEB_BASE = `http://127.0.0.1:${WEB_PORT}`;

const workDir = mkdtempSync(path.join(tmpdir(), "m0-workbench-shot-"));
const databaseUrl = `sqlite:///${path.join(workDir, "business.db")}`;
const procs = [];

function freePort(port) {
  try {
    const out = execFileSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
    for (const pid of out.split("\n")) if (pid) try { process.kill(Number(pid), "SIGKILL"); } catch {}
  } catch {}
}
function track(c) { procs.push(c); }
function killAll() { for (const c of procs) { try { if (c.pid) process.kill(-c.pid, "SIGTERM"); } catch { try { c.kill("SIGKILL"); } catch {} } } }
async function waitFor(url, t, label) {
  const dl = Date.now() + t;
  while (Date.now() < dl) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise((r) => setTimeout(r, 400)); }
  throw new Error(`timeout ${label}`);
}

const childEnv = { ...process.env, DATABASE_URL: databaseUrl, AI_RUNTIME_MODE: "fake", SESSION_COOKIE_SECURE: "false", DATABASE_SCHEMA_CHECK_ON_STARTUP: "false", STORAGE_ROOT: path.join(workDir, "storage") };

async function main() {
  freePort(API_PORT); freePort(WEB_PORT);
  execFileSync("uv", ["run", "alembic", "upgrade", "head"], { cwd: path.join(repoRoot, "backend"), env: { ...process.env, ALEMBIC_DATABASE_URL: databaseUrl }, stdio: "pipe" });
  track(spawn("uv", ["run", "--project", "backend", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", String(API_PORT)], { cwd: repoRoot, detached: true, env: childEnv, stdio: "ignore" }));
  track(spawn("uv", ["run", "python", "-m", "app.lib.operations.worker"], { cwd: path.join(repoRoot, "backend"), detached: true, env: childEnv, stdio: "ignore" }));
  await waitFor(`${API_BASE}/healthz`, 60000, "api");
  execFileSync("pnpm", ["build"], { cwd: frontendRoot, env: { ...process.env, BACKEND_URL: API_BASE, NEXT_PUBLIC_AGENT_API_BASE_URL: API_BASE }, stdio: "pipe" });
  track(spawn("pnpm", ["start", "--port", String(WEB_PORT)], { cwd: frontendRoot, detached: true, env: { ...process.env, BACKEND_URL: API_BASE, NEXT_PUBLIC_AGENT_API_BASE_URL: API_BASE }, stdio: "ignore" }));
  await waitFor(`${WEB_BASE}/login`, 60000, "web");

  // Seed: admin + scene + credential + question (fake generation).
  await fetch(`${API_BASE}/api/auth/register`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "shot-admin", password: "shot-admin-password-1" }) });
  const login = await fetch(`${API_BASE}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier: "shot-admin", password: "shot-admin-password-1" }) });
  const cookie = login.headers.get("set-cookie").split(";")[0];
  const scene = await (await fetch(`${API_BASE}/api/scenes`, { method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie }, body: JSON.stringify({ name: "截图评测集" }) })).json();
  const issued = await (await fetch(`${API_BASE}/api/scenes/${scene.id}/credentials`, { method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie }, body: JSON.stringify({}) })).json();
  await fetch(`${API_BASE}/api/external/question-batches`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${issued.token}` }, body: JSON.stringify({ schema_version: "1.0", command_id: "shot-cmd", cases: [{ client_case_id: "shot-case", title: "工作台截图用例", task_prompt: "请把素材整理成正式说明。", reference_examples: [{ client_ref_id: "r1", source_name: "素材", content_text: "参考素材正文。" }], bad_cases: [{ content_text: "坏例子。", teacher_feedback_texts: ["反馈。"], reason_summary: "原因。" }], reference_answer: "标准答案。", memory_materials: [{ client_ref_id: "m1", source_label: "记忆", content_text: "记忆正文。" }] }] }) });
  // Wait for fake generation.
  let qid = null, status = null, dl = Date.now() + 60000;
  while (Date.now() < dl) {
    const list = await (await fetch(`${API_BASE}/api/questions?scene_id=${scene.id}`, { headers: { Cookie: cookie } })).json();
    if (list.items.length) { qid = list.items[0].id; status = list.items[0].status; if (status === "pending_review") break; }
    await new Promise((r) => setTimeout(r, 500));
  }

  const shots = [];
  for (const [label, viewport] of [["1440x900", { width: 1440, height: 900 }], ["1280x720", { width: 1280, height: 720 }]]) {
    const ctx = await chromium.launch().then((b) => ({ browser: b, context: null }));
    const browser = ctx.browser;
    const context = await browser.newContext({ viewport });
    await context.addCookies([{ name: cookie.split("=")[0], value: cookie.split("=")[1], url: WEB_BASE }]);
    const page = await context.newPage();
    await page.goto(`${WEB_BASE}/evaluation-sets/${scene.id}/questions/${qid}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    const f = path.join(outDir, `workbench-${label}.png`);
    await page.screenshot({ path: f, fullPage: false });
    shots.push(f);
    await browser.close();
  }
  console.log(shots.join("\n"));
}

main().then(() => { killAll(); rmSync(workDir, { recursive: true, force: true }); freePort(API_PORT); freePort(WEB_PORT); }).catch((e) => { console.error(e.message); killAll(); rmSync(workDir, { recursive: true, force: true }); freePort(API_PORT); freePort(WEB_PORT); process.exit(1); });
