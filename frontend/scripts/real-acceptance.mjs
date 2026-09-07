/**
 * Real-AI web acceptance (C3 cutover contract).
 *
 * Boots an ISOLATED environment — task-exclusive PostgreSQL business +
 * checkpoint databases (project DBs are refused by name), FastAPI on a FREE
 * port in production mode (real provider from .env), exactly ONE production
 * worker, and a prebuilt Next.js console — then drives the full chain in a
 * real browser with the C1 REAL sample materials:
 *
 *   log in the env-seeded admin -> create evaluation set -> issue credential ->
 *   upload the real case through the external endpoint -> browser observes LIVE
 *   streaming increments while generation is still running -> REAL AI produces
 *   complete criteria (anchors + dual bases + verifiable citations) -> teacher
 *   opens the basis panel, saves an unanchored integer -> publish -> reopen ->
 *   accepted deletion -> navigation happens only after the durable cleanup
 *   finished (authoritative 404) -> checkpoint residue verified zero.
 *
 * One-shot replacement of the old runner: SQLite, the built-in fake sample,
 * fixed ports with kill-any-listener behavior and the two-field assertions
 * are all removed. Only processes started by THIS run are ever killed.
 *
 * Required environment:
 *   ACCEPT_BUSINESS_DSN=postgresql+psycopg://...@127.0.0.1:5432/blue_benchmark_c3_accept_web
 *   ACCEPT_CHECKPOINT_DSN=postgresql://...@127.0.0.1:5432/blue_benchmark_c3_accept_web_ckpt
 * Optional:
 *   ACCEPT_CORPUS_ROOT (default <repoRoot>/.local-samples/m0)
 *   ACCEPT_CASE (default m0-real-f-financial-report)
 *
 * Output is sanitized: stage markers, counts, ids and the final
 * M0_WEB_ACCEPTANCE=PASS/FAIL marker only — never material bodies or tokens.
 */

import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backendRoot = path.join(repoRoot, "backend");

const FORBIDDEN_DB_NAMES = new Set(["blue_benchmark", "blue_benchmark_checkpoint", "postgres", "template1"]);
const CORPUS_ROOT = process.env.ACCEPT_CORPUS_ROOT
  ?? path.join(repoRoot, ".local-samples", "m0");
const CASE_ID = process.env.ACCEPT_CASE ?? "m0-real-f-financial-report";
const GENERATION_TIMEOUT_MS = 30 * 60 * 1000;

const workDir = mkdtempSync(path.join(tmpdir(), "m0-web-acceptance-"));
const procs = [];
let browser = null;

function log(stage, extra = "") {
  console.log(`M0_WEB_ACCEPTANCE_STAGE=${stage}${extra ? ` ${extra}` : ""}`);
}

function fail(reason) {
  throw new Error(reason);
}

function dbNameOf(dsn) {
  const raw = dsn.replace("postgresql+psycopg://", "postgresql://");
  const withScheme = raw.includes("://") ? raw : `postgresql://${raw}`;
  return new URL(withScheme).pathname.replace(/^\//, "").split("?")[0];
}

function requireIsolatedDsn(value, label) {
  if (!value) fail(`必须提供 ${label}（隔离验收库）；SQLite/项目库/内存替代一律拒绝`);
  const name = dbNameOf(value);
  if (!name) fail(`${label} 缺少库名`);
  if (FORBIDDEN_DB_NAMES.has(name)) fail(`${label} 指向受保护库 ${name}`);
  return value;
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function track(child) {
  procs.push(child);
}

function killOwnProcesses() {
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
  fail(`timeout waiting for ${label} at ${url}`);
}

async function main() {
  log("setup");
  const businessDsn = requireIsolatedDsn(process.env.ACCEPT_BUSINESS_DSN, "ACCEPT_BUSINESS_DSN");
  const checkpointDsn = requireIsolatedDsn(process.env.ACCEPT_CHECKPOINT_DSN, "ACCEPT_CHECKPOINT_DSN");
  const checkpointPlain = checkpointDsn.replace("postgresql+psycopg://", "postgresql://");
  const businessSqla = businessDsn.includes("+")
    ? businessDsn
    : businessDsn.replace("postgresql://", "postgresql+psycopg://");

  const apiPort = await getFreePort();
  const webPort = await getFreePort();
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const webBase = `http://127.0.0.1:${webPort}`;
  log("ports", `api=${apiPort} web=${webPort}`);

  // Rebuild the real C1 case (hash-gated; fails loudly without the corpus).
  execFileSync("uv", [
    "run", "python", "-m", "scripts.m0_samples",
    "--source-root", CORPUS_ROOT,
    "--out", path.join(workDir, "samples"),
    "--command-id", "web-acceptance",
  ], { cwd: backendRoot, stdio: "pipe" });
  const batch = JSON.parse(
    readFileSync(path.join(workDir, "samples", "batch.json"), "utf-8"),
  );
  const realCase = batch.cases.find((c) => c.client_case_id === CASE_ID);
  if (!realCase) fail(`case ${CASE_ID} 不在重建批次中`);
  log("samples", `case=${CASE_ID} answer_chars=${realCase.reference_answer.length}`);

  // Migrate the isolated business DB and prepare the checkpoint schema.
  execFileSync("uv", ["run", "alembic", "upgrade", "head"], {
    cwd: backendRoot,
    env: { ...process.env, ALEMBIC_DATABASE_URL: businessSqla },
    stdio: "pipe",
  });
  execFileSync("uv", ["run", "python", "-c", `
import os, psycopg
from pydantic import SecretStr
from app.lib.ai_runtime import deep_runtime
from app.lib.settings import settings
class C:
    checkpoint_database_url = SecretStr(os.environ["ACCEPT_CHECKPOINT_DSN"])
    langgraph_aes_key = settings.langgraph_aes_key
assert settings.langgraph_aes_key.get_secret_value(), "LANGGRAPH_AES_KEY missing"
conn = psycopg.connect(os.environ["ACCEPT_CHECKPOINT_DSN"], autocommit=True)
deep_runtime.build_saver(conn, C()).setup()
conn.close()
print("checkpoint schema ready")
`], {
    cwd: backendRoot,
    env: { ...process.env, ACCEPT_CHECKPOINT_DSN: checkpointPlain },
    stdio: "pipe",
  });
  log("migrated");

  const childEnv = {
    ...process.env,
    DATABASE_URL: businessSqla,
    CHECKPOINT_DATABASE_URL: checkpointPlain,
    AI_RUNTIME_MODE: "production",
    SESSION_COOKIE_SECURE: "false",
    DATABASE_SCHEMA_CHECK_ON_STARTUP: "false",
    // Short lease so the worker-kill recovery phase requeues quickly.
    OPERATION_LEASE_SECONDS: "20",
    // The API lifespan seeds the single admin from these on startup.
    ADMIN_USERNAME: "acceptance-admin",
    ADMIN_PASSWORD: "acceptance-admin-password-1",
  };

  track(spawn("uv", ["run", "uvicorn", "app.main:app", "--port", String(apiPort)], {
    cwd: backendRoot, detached: true, env: childEnv, stdio: "ignore",
  }));
  const workerChild = spawn("uv", ["run", "python", "-m", "app.lib.operations.worker"], {
    cwd: backendRoot, detached: true, env: childEnv, stdio: "ignore",
  });
  track(workerChild);
  log("api_worker_started");
  await waitFor(`${apiBase}/healthz`, 60000, "api");

  execFileSync("pnpm", ["build"], {
    cwd: frontendRoot,
    env: { ...process.env, BACKEND_URL: apiBase, NEXT_PUBLIC_AGENT_API_BASE_URL: apiBase },
    stdio: "pipe",
  });
  log("frontend_built");
  track(spawn("pnpm", ["start", "--port", String(webPort)], {
    cwd: frontendRoot, detached: true,
    env: { ...process.env, BACKEND_URL: apiBase, NEXT_PUBLIC_AGENT_API_BASE_URL: apiBase },
    stdio: "ignore",
  }));
  await waitFor(`${webBase}/login`, 60000, "frontend");
  log("frontend_started");

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // 1. Log in as the env-seeded admin (no registration surface exists).
  await page.goto(`${webBase}/`);
  await page.waitForURL(/\/login$/, { timeout: 20000 });
  await page.getByLabel("用户名").fill("acceptance-admin");
  await page.getByLabel("密码", { exact: true }).fill("acceptance-admin-password-1");
  await page.getByRole("button", { name: "登 录" }).click();
  await page.waitForURL(/\/evaluation-sets$/, { timeout: 20000 });
  log("logged_in");

  // 2. Create an evaluation set.
  await page.getByRole("button", { name: "创建评测集" }).first().click();
  await page.getByLabel("名称").fill("真实验收评测集");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await page.waitForURL(/\/evaluation-sets\/.+$/, { timeout: 20000 });
  const sceneId = page.url().split("/").pop();
  log("scene_created", `scene_id=${sceneId}`);

  // 3. Issue the 1:1 credential and capture the one-time prompt's token.
  await page.getByRole("button", { name: "创建凭证" }).click();
  const prompt = await page.getByRole("textbox", { name: "绑定提示词" }).inputValue();
  const tokenMatch = prompt.match(/sep_[A-Za-z0-9_-]+/);
  if (!tokenMatch) fail("no token in prompt");
  const token = tokenMatch[0];
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "不复制并关闭" }).click();
  log("credential_issued");

  // 4. Upload the REAL case (full materials, no truncation) via the external API.
  const upload = await fetch(`${apiBase}/api/external/question-batches`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      schema_version: "1.0",
      command_id: `web-acceptance-${Date.now()}`,
      cases: [realCase],
    }),
  });
  if (upload.status !== 201) fail(`upload failed ${upload.status}`);
  const questionId = (await upload.json()).cases[0].question_id;
  log("question_uploaded", `question_id=${questionId}`);

  const cookies = await page.context().cookies();
  const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  const getDetail = async () => {
    const r = await fetch(`${apiBase}/api/questions/${questionId}`, { headers: { Cookie: cookieHeader } });
    return { status: r.status, body: r.ok ? await r.json() : null };
  };

  // 5. LIVE streaming proof: the browser receives real increments WHILE the
  //    generation is still running (before any completion).
  await page.goto(`${webBase}/evaluation-sets/${sceneId}/questions/${questionId}`);
  await page.getByTestId("generation-progress").waitFor({ timeout: 20000 });
  const connection = page.getByTestId("timeline-connection");
  {
    // The stream must actually reach "已连接" — a perpetual connecting state
    // (proxy buffering / auth) must not pass as live streaming.
    const deadline = Date.now() + 30000;
    for (;;) {
      const text = await connection.textContent();
      if (text && text.includes("已连接")) break;
      if (Date.now() > deadline) fail(`SSE 未进入已连接状态（当前：${text}），疑似代理缓冲或鉴权问题`);
      await page.waitForTimeout(250);
    }
  }
  // Real event lines only — the empty-state placeholder carries no testid, so
  // it can never satisfy this count. Observing lines WHILE the status badge
  // still says 生成中 proves increments arrived before completion.
  const contentLines = page.getByTestId("timeline-body").locator(
    '[data-testid="timeline-stream"], [data-testid="timeline-stage"], [data-testid="timeline-tool"]',
  );
  let sawLiveIncrement = false;
  const liveDeadline = Date.now() + GENERATION_TIMEOUT_MS;
  while (Date.now() < liveDeadline && !sawLiveIncrement) {
    const badge = await page.getByText("生成中", { exact: true }).count();
    const lines = await contentLines.count();
    if (badge > 0 && lines > 0) {
      // Sample once more after a beat: still generating + still non-empty is
      // a live observation, not a post-completion snapshot.
      await page.waitForTimeout(1500);
      const stillGenerating = await page.getByText("生成中", { exact: true }).count();
      if (stillGenerating > 0) sawLiveIncrement = true;
    }
    if (!sawLiveIncrement) await page.waitForTimeout(1000);
  }
  if (!sawLiveIncrement) fail("生成完成前浏览器没有收到任何真实增量（假流式或代理缓冲）");
  log("live_streaming_observed");

  // 5a. Late joiner catches up from the persisted log (cursor replay), and a
  //     mid-generation page refresh restores the timeline without restarting
  //     the job.
  {
    const det = (await getDetail()).body;
    const opId = det.active_operation_id;
    if (!opId) fail("生成中但缺少 active_operation_id");
    const snap = await (await fetch(
      `${apiBase}/api/questions/${questionId}/runs/${opId}/events`,
      { headers: { Cookie: cookieHeader } },
    )).json();
    if (!snap.events.length) fail("晚订阅读取不到已持久化的事件");
    log("late_join_replayed", `events=${snap.events.length}`);

    await page.reload();
    await page.getByTestId("generation-progress").waitFor({ timeout: 20000 });
    const restoredDeadline = Date.now() + 60000;
    for (;;) {
      const lines = await page.getByTestId("timeline-body").locator(
        '[data-testid="timeline-stream"], [data-testid="timeline-stage"], [data-testid="timeline-tool"]',
      ).count();
      if (lines > 0) break;
      if (Date.now() > restoredDeadline) fail("刷新后时间线没有从持久化日志恢复");
      await page.waitForTimeout(500);
    }
    const afterRefresh = (await getDetail()).body;
    if (afterRefresh.status !== "generating") fail("刷新触发了第二次生成或状态异常");
    log("refresh_restored_timeline");
  }

  // 5b. REAL worker restart recovery: kill the worker mid-run, wait for the
  //     lease to expire, start a NEW worker; the run must resume on the same
  //     thread without duplicating the initial input.
  {
    const det = (await getDetail()).body;
    if (det.status !== "generating") fail("击杀 Worker 前生成已结束，无法验证重启恢复");
    const opId = det.active_operation_id;
    try { process.kill(-workerChild.pid, "SIGKILL"); } catch { workerChild.kill("SIGKILL"); }
    log("worker_killed_midrun", `operation=${opId}`);
    await new Promise((r) => setTimeout(r, 26000)); // lease 20s + margin
    const restarted = spawn("uv", ["run", "python", "-m", "app.lib.operations.worker"], {
      cwd: backendRoot, detached: true, env: childEnv, stdio: "ignore",
    });
    track(restarted);
    log("worker_restarted");
    // Recovery proof is asserted after settle: the persisted log must contain
    // a run_resumed/thread_state_incomplete event for this operation.
    globalThis.__resumedOpId = opId;
  }

  // 6. Wait for the REAL generation to settle.
  let detail = null;
  const genDeadline = Date.now() + GENERATION_TIMEOUT_MS;
  while (Date.now() < genDeadline) {
    const r = await getDetail();
    if (r.status === 200) {
      detail = r.body;
      if (detail.status === "pending_review") break;
      if (detail.status === "generation_failed") fail(`generation failed: ${detail.last_error?.code}`);
    }
    await new Promise((res) => setTimeout(res, 3000));
  }
  if (!detail || detail.status !== "pending_review") fail("generation did not complete");
  const criteria = detail.criteria || [];
  if (criteria.length < 2) fail(`criteria count out of range: ${criteria.length}`);

  // Complete-contract + citation verification against the uploaded materials.
  const locatorTexts = { task_prompt: realCase.task_prompt, reference_answer: realCase.reference_answer };
  (realCase.reference_examples || []).forEach((x, i) => { locatorTexts[`reference_examples[${i}]`] = x.content_text; });
  (realCase.bad_cases || []).forEach((bc, i) => {
    locatorTexts[`bad_cases[${i}].content`] = bc.content_text;
    (bc.teacher_feedback_texts || []).forEach((fb, j) => { locatorTexts[`bad_cases[${i}].feedback[${j}]`] = fb; });
    if (bc.reason_summary) locatorTexts[`bad_cases[${i}].reason_summary`] = bc.reason_summary;
  });
  (realCase.memory_materials || []).forEach((m, i) => { locatorTexts[`memory_materials[${i}]`] = m.content_text; });
  for (const item of criteria) {
    if (!item.score_anchors.some((a) => a.score === item.pass_score)) fail("建议分缺少锚点描述");
    if (item.pass_score_basis.explained_score !== item.pass_score) fail("通过分依据解释分数不一致");
    for (const key of ["criterion_basis", "pass_score_basis"]) {
      if (!item[key].claims.length) fail(`${key} 缺少主张`);
      for (const claim of item[key].claims) {
        if (!["teacher_explicit", "ai_inferred"].includes(claim.kind)) fail("主张分类非法");
        if (claim.kind === "teacher_explicit" && !claim.citation) fail("老师明确要求缺少引用");
        if (claim.citation) {
          const text = locatorTexts[claim.citation.locator];
          if (text === undefined) fail(`引用定位符不属于本题材料: ${claim.citation.locator}`);
          const quote = claim.citation.quote.trim();
          if (quote && !text.includes(quote)) fail("引用原文不在对应材料中");
        }
      }
    }
  }
  log("real_generation_done", `criteria=${criteria.length}`);

  // Recovery evidence: the operation that survived the worker kill must show
  // a checkpoint resume in its persisted public log.
  {
    const resumedOp = globalThis.__resumedOpId;
    if (resumedOp) {
      const allEvents = [];
      let after = 0;
      for (;;) {
        const pageBody = await (await fetch(
          `${apiBase}/api/questions/${questionId}/runs/${resumedOp}/events?after_sequence=${after}`,
          { headers: { Cookie: cookieHeader } },
        )).json();
        allEvents.push(...pageBody.events);
        if (!pageBody.events.length || pageBody.last_sequence <= after) break;
        after = pageBody.last_sequence;
      }
      const resumed = allEvents.some(
        (e) => e.kind === "run_resumed" && e.stage === "thread_state_incomplete",
      );
      if (!resumed) fail("Worker 重启后未观察到 thread_state_incomplete 的恢复事件");
      const humanTurns = allEvents.filter((e) => e.kind === "run_started").length;
      if (humanTurns > 1) fail("恢复过程重复提交了初始输入");
      log("worker_restart_recovery_verified", `events=${allEvents.length}`);
    }
  }

  // Events API replay: the full public process is retained after completion.
  const eventsResp = await fetch(
    `${apiBase}/api/questions/${questionId}/runs/${detail.last_operation_id}/events`,
    { headers: { Cookie: cookieHeader } },
  );
  if (!eventsResp.ok) fail("events endpoint failed");
  const eventsBody = await eventsResp.json();
  const kinds = eventsBody.events.map((e) => e.kind);
  if (!kinds.includes("run_completed")) fail("事件日志缺少 run_completed");
  if (kinds[kinds.length - 1] !== "run_completed") fail("run_completed 不是最后一个事件");
  if (!kinds.includes("tool_started")) fail("事件日志缺少真实工具事件");
  log("events_replayed", `events=${eventsBody.events.length}`);

  // 7. Teacher flow in the browser: basis panel, unanchored integer, save,
  //    publish, reopen.
  await page.goto(`${webBase}/evaluation-sets/${sceneId}/questions/${questionId}`);
  const checkboxes = page.locator('input[type="checkbox"][aria-label^="选择维度"]');
  await checkboxes.first().waitFor({ timeout: 20000 });
  const boxCount = await checkboxes.count();
  if (boxCount !== criteria.length) fail(`workbench criteria mismatch ${boxCount} != ${criteria.length}`);

  await page.getByRole("button", { name: "查看依据" }).first().click();
  await page.getByText("为什么设这个维度").first().waitFor({ timeout: 10000 });
  log("basis_panel_opened");

  await checkboxes.nth(0).check();
  const scoreInput = page.locator('input[aria-label$="的通过分"]').first();
  await scoreInput.fill("5");
  await page.getByRole("button", { name: "保存维度" }).click();
  await page.getByRole("button", { name: "确认保存" }).click();
  await page.getByRole("button", { name: "发布" }).waitFor({ timeout: 20000 });
  const saved = (await getDetail()).body;
  if (saved.criteria[0].pass_score !== 5) fail("任意整数 5 未保存成功");
  if (saved.criteria[0].pass_score_basis.explained_score === 5) fail("依据被静默改写");
  await page.getByRole("button", { name: "发布" }).click();
  await page.getByText("已发布", { exact: true }).first().waitFor({ timeout: 20000 });
  log("published");

  await page.getByRole("button", { name: "重新打开审改" }).click();
  await page.getByText("待审改", { exact: true }).first().waitFor({ timeout: 20000 });
  log("reopened");

  // 8. Accepted deletion: navigation only after the durable cleanup (404).
  //     Thread ids are captured BEFORE deletion — the registry rows disappear
  //     with the question, and residue must be checked against the captured
  //     list, not an empty post-delete query.
  const threadsBeforeDelete = JSON.parse(execFileSync("uv", ["run", "python", "-c", `
import json, os
from app.features.question_library import run_streams
print(json.dumps(run_streams.list_question_threads(os.environ["ACCEPT_QUESTION_ID"])))
`], {
    cwd: backendRoot,
    env: { ...process.env, DATABASE_URL: businessSqla, ACCEPT_QUESTION_ID: questionId },
    stdio: ["ignore", "pipe", "ignore"],
  }).toString().trim());
  if (!Array.isArray(threadsBeforeDelete) || threadsBeforeDelete.length === 0) {
    fail("删除前未捕获到任何运行线程登记，无法证明跨库清理范围");
  }
  log("threads_captured", `count=${threadsBeforeDelete.length}`);
  const threadCheck = async () => {
    const r = await fetch(`${apiBase}/api/questions/${questionId}`, { headers: { Cookie: cookieHeader } });
    return r.status;
  };
  await page.getByRole("button", { name: "删除题目" }).click();
  await page.getByLabel("题目标题").fill(detail.title);
  await page.getByTestId("delete-confirm").click();
  await page.waitForURL(/\/evaluation-sets\/[^/]+$/, { timeout: 180000 });
  if ((await threadCheck()) !== 404) fail("删除导航后题目仍可读取");
  log("deleted_and_navigated");

  // 9. Checkpoint residue verified zero through the backend primitives.
  const residueOut = execFileSync("uv", ["run", "python", "-c", `
import json, os
import psycopg
from app.features.question_library import run_streams
from app.lib.ai_runtime import deep_runtime
from pydantic import SecretStr
from app.lib.settings import settings
class C:
    checkpoint_database_url = SecretStr(os.environ["ACCEPT_CHECKPOINT_DSN"])
    langgraph_aes_key = settings.langgraph_aes_key
conn = psycopg.connect(os.environ["ACCEPT_CHECKPOINT_DSN"], autocommit=True)
saver = deep_runtime.build_saver(conn, C())
threads = run_streams.list_question_threads(os.environ["ACCEPT_QUESTION_ID"])
captured = json.loads(os.environ["ACCEPT_CAPTURED_THREADS"])
residues = {t: deep_runtime.thread_data_residue(conn, t) for t in captured}
print(json.dumps({"threads": len(threads), "residues": residues}))
`], {
    cwd: backendRoot,
    env: {
      ...process.env,
      DATABASE_URL: businessSqla,
      ACCEPT_CHECKPOINT_DSN: checkpointPlain,
      ACCEPT_QUESTION_ID: questionId,
      ACCEPT_CAPTURED_THREADS: JSON.stringify(threadsBeforeDelete),
    },
    stdio: ["ignore", "pipe", "ignore"],
  }).toString();
  const residue = JSON.parse(residueOut.trim().split("\n").pop());
  if (residue.threads !== 0) {
    // Business-side registry rows must be gone with the question.
    fail(`业务库线程登记残留 ${residue.threads} 行`);
  }
  for (const [thread, counts] of Object.entries(residue.residues)) {
    if (Object.values(counts).some((v) => v !== 0)) fail(`检查点残留 ${thread}: ${JSON.stringify(counts)}`);
  }
  log("residue_verified", `threads_checked=${Object.keys(residue.residues).length}`);

  await browser.close();
  log("done");
  console.log("M0_WEB_ACCEPTANCE=PASS");
}

function cleanup() {
  killOwnProcesses();
  rmSync(workDir, { recursive: true, force: true });
}

main()
  .then(() => { cleanup(); process.exit(0); })
  .catch((err) => {
    console.log(`M0_WEB_ACCEPTANCE=FAIL reason=${err.message}`);
    cleanup();
    process.exit(1);
  });
