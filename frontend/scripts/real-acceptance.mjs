/**
 * Real-AI web acceptance runner (Child 5 / parent AC15).
 *
 * Boots an isolated environment — fresh SQLite DB, FastAPI on a dedicated port
 * in production mode (real provider from .env), exactly ONE production worker,
 * and a prebuilt Next.js console — then drives the full chain in a real
 * browser:
 *
 *   register admin -> create evaluation set -> issue credential -> capture the
 *   one-time Agent prompt -> upload a question through the external endpoint ->
 *   REAL AI generates 2-6 criteria -> teacher selects & saves -> publish ->
 *   reopen review -> re-publish.
 *
 * Output is sanitized: it prints stage markers, counts, ids and the final
 * M0_WEB_ACCEPTANCE=PASS/FAIL marker only. It never prints passwords, cookies,
 * tokens, the full prompt, material bodies, or raw model output.
 */

import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const API_PORT = 8200;
const WEB_PORT = 3200;
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const WEB_BASE = `http://127.0.0.1:${WEB_PORT}`;

const workDir = mkdtempSync(path.join(tmpdir(), "m0-web-acceptance-"));
const databaseUrl = `sqlite:///${path.join(workDir, "business.db")}`;
const procs = [];
let browser = null;

function log(stage, extra = "") {
  console.log(`M0_WEB_ACCEPTANCE_STAGE=${stage}${extra ? ` ${extra}` : ""}`);
}

function freePort(port) {
  try {
    const out = execFileSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
    for (const pid of out.split("\n")) if (pid) try { process.kill(Number(pid), "SIGKILL"); } catch {}
  } catch {}
}

function track(child) {
  procs.push(child);
}

function killAll() {
  if (browser) { try { browser.close(); } catch {} browser = null; }
  for (const child of procs) {
    try { if (child.pid) process.kill(-child.pid, "SIGTERM"); } catch { try { child.kill("SIGKILL"); } catch {} }
  }
}

async function waitFor(url, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`timeout waiting for ${label} at ${url}`);
}

const childEnv = {
  ...process.env,
  DATABASE_URL: databaseUrl,
  AI_RUNTIME_MODE: "production",
  SESSION_COOKIE_SECURE: "false",
  DATABASE_SCHEMA_CHECK_ON_STARTUP: "false",
  STORAGE_ROOT: path.join(workDir, "storage"),
};

async function main() {
  log("setup");
  freePort(API_PORT);
  freePort(WEB_PORT);

  execFileSync("uv", ["run", "alembic", "upgrade", "head"], {
    cwd: path.join(repoRoot, "backend"),
    env: { ...process.env, ALEMBIC_DATABASE_URL: databaseUrl },
    stdio: "pipe",
  });
  log("migrated");

  track(spawn("uv", ["run", "--project", "backend", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", String(API_PORT)], {
    cwd: repoRoot, detached: true, env: childEnv, stdio: "ignore",
  }));
  track(spawn("uv", ["run", "python", "-m", "app.lib.operations.worker"], {
    cwd: path.join(repoRoot, "backend"), detached: true, env: childEnv, stdio: "ignore",
  }));
  log("api_worker_started");
  await waitFor(`${API_BASE}/healthz`, 60000, "api");

  // Build the console pointing at the acceptance API.
  execFileSync("pnpm", ["build"], {
    cwd: frontendRoot,
    env: { ...process.env, BACKEND_URL: API_BASE, NEXT_PUBLIC_AGENT_API_BASE_URL: API_BASE },
    stdio: "pipe",
  });
  log("frontend_built");
  track(spawn("pnpm", ["start", "--port", String(WEB_PORT)], {
    cwd: frontendRoot, detached: true,
    env: { ...process.env, BACKEND_URL: API_BASE, NEXT_PUBLIC_AGENT_API_BASE_URL: API_BASE },
    stdio: "ignore",
  }));
  await waitFor(`${WEB_BASE}/login`, 60000, "frontend");
  log("frontend_started");

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // 1. Register the first admin.
  await page.goto(`${WEB_BASE}/`);
  await page.waitForURL(/\/register$/, { timeout: 20000 });
  await page.getByLabel("用户名").fill("acceptance-admin");
  await page.getByLabel("密码", { exact: true }).fill("acceptance-admin-password-1");
  await page.getByLabel("确认密码").fill("acceptance-admin-password-1");
  await page.getByRole("button", { name: "创建管理员" }).click();
  await page.waitForURL(/\/evaluation-sets$/, { timeout: 20000 });
  log("registered");

  // 2. Create an evaluation set.
  await page.getByRole("button", { name: "创建评测集" }).first().click();
  await page.getByLabel("名称").fill("真实验收评测集");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await page.waitForURL(/\/evaluation-sets\/.+$/, { timeout: 20000 });
  const sceneId = page.url().split("/").pop();
  log("scene_created", `scene_id=${sceneId}`);

  // 3. Issue a credential and capture the one-time prompt's token.
  await page.getByRole("button", { name: "生成上传凭证" }).click();
  const prompt = await page.getByRole("textbox", { name: "绑定提示词" }).inputValue();
  const tokenMatch = prompt.match(/sep_[A-Za-z0-9_-]+/);
  if (!tokenMatch) throw new Error("no token in prompt");
  const token = tokenMatch[0];
  const tokenCount = prompt.split(token).length - 1;
  log("credential_issued", `token_occurrences=${tokenCount}`);
  // Close the one-time prompt for real: not copied, so the dialog asks to
  // confirm discarding the prompt (exercising the "cannot recover" guard).
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "不复制并关闭" }).click();
  await page.getByRole("textbox", { name: "绑定提示词" }).waitFor({ state: "detached", timeout: 5000 });

  // 4. Upload a question through the external endpoint (as the Skill would).
  const upload = await fetch(`${API_BASE}/api/external/question-batches`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      schema_version: "1.0",
      command_id: "real-acceptance-cmd",
      cases: [{
        client_case_id: "real-acceptance-case",
        title: "真实验收用例",
        task_prompt: "请把提供的素材整理成一段正式、准确、结构清晰的说明文字。",
        reference_examples: [{ client_ref_id: "ref-1", source_name: "素材", content_text: "这是一段用于验收的参考素材，描述了整理说明的基本要求。" }],
        bad_cases: [{ content_text: "这是被否定的示例输出。", teacher_feedback_texts: ["结构混乱，要点缺失。"], reason_summary: "结构与要点不达标。" }],
        reference_answer: "应当输出一段结构清晰、要点完整、表述正式的说明文字。",
        memory_materials: [{ client_ref_id: "mem-1", source_label: "记忆", content_text: "验收场景下优先保证结构清晰与要点完整。" }],
      }],
    }),
  });
  if (upload.status !== 201) throw new Error(`upload failed ${upload.status}`);
  const questionId = (await upload.json()).cases[0].question_id;
  log("question_uploaded", `question_id=${questionId}`);

  // 5. Wait for REAL AI generation to reach pending_review.
  const cookies = await page.context().cookies();
  const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  let detail = null;
  const genDeadline = Date.now() + 300000;
  while (Date.now() < genDeadline) {
    const r = await fetch(`${API_BASE}/api/questions/${questionId}`, { headers: { Cookie: cookieHeader } });
    if (r.ok) {
      detail = await r.json();
      if (detail.status === "pending_review") break;
      if (detail.status === "generation_failed") throw new Error(`generation failed: ${detail.last_error?.code}`);
    }
    await new Promise((res) => setTimeout(res, 3000));
  }
  if (!detail || detail.status !== "pending_review") throw new Error("generation did not complete");
  const criteriaCount = (detail.criteria || []).length;
  if (criteriaCount < 2 || criteriaCount > 6) throw new Error(`criteria count out of range: ${criteriaCount}`);
  log("real_generation_done", `criteria_count=${criteriaCount} confirmed=${detail.criteria_confirmed}`);

  // 6. Open the workbench, select candidates, save, publish, reopen, re-publish.
  await page.goto(`${WEB_BASE}/evaluation-sets/${sceneId}/questions/${questionId}`);
  const checkboxes = page.locator('input[type="checkbox"][aria-label^="选择维度"]');
  await checkboxes.first().waitFor({ timeout: 20000 });
  const boxCount = await checkboxes.count();
  if (boxCount !== criteriaCount) throw new Error(`workbench criteria mismatch ${boxCount} != ${criteriaCount}`);
  await checkboxes.nth(0).check();
  await page.getByRole("button", { name: "保存维度" }).click();
  await page.getByRole("button", { name: "确认保存" }).click();
  await page.getByRole("button", { name: "发布" }).waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "发布" }).click();
  await page.getByText("已发布", { exact: true }).first().waitFor({ timeout: 20000 });
  log("published");

  await page.getByRole("button", { name: "重新打开审改" }).click();
  await page.getByText("待审改", { exact: true }).first().waitFor({ timeout: 20000 });
  log("reopened");

  await page.getByRole("button", { name: "发布" }).click();
  await page.getByText("已发布", { exact: true }).first().waitFor({ timeout: 20000 });
  log("republished");

  await browser.close();
  log("done");
  console.log("M0_WEB_ACCEPTANCE=PASS");
}

main()
  .then(() => { killAll(); rmSync(workDir, { recursive: true, force: true }); freePort(API_PORT); freePort(WEB_PORT); process.exit(0); })
  .catch((err) => {
    console.log(`M0_WEB_ACCEPTANCE=FAIL reason=${err.message}`);
    killAll(); rmSync(workDir, { recursive: true, force: true }); freePort(API_PORT); freePort(WEB_PORT);
    process.exit(1);
  });
