import { expect, test, type Locator, type Page } from "@playwright/test";

const EVAL_DATA = "/Users/hsikey/BenchMark/EvalData";
const SAMPLE_FILES = [
  `${EVAL_DATA}/理想汽车供稿-对话上下文-原始记录-2026-08-27.jsonl`,
  `${EVAL_DATA}/新一代理想MEGA新闻稿-对话上下文完整导出-20260828.zip`,
  `${EVAL_DATA}/理想汽车供稿-对话上下文-2026-08-27.md`,
];

async function reloadUntilVisible(page: Page, target: Locator, timeoutMs = 900_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // Let the mounted page's SSE/GET recovery loop finish first. Reloading
    // every 1.5s aborts the very request that would produce the target and can
    // livelock a real Provider run forever.
    try {
      await target.waitFor({ state: "visible", timeout: 5_000 });
      return;
    } catch {
      await page.reload({ waitUntil: "domcontentloaded" });
    }
  }
  throw new Error("页面在服务端快照完成后仍未出现预期状态");
}

test.skip(process.env.E2E_REAL_AI !== "1", "需要 E2E_REAL_AI=1 才执行真实 Provider 流程");

test("真实 AI 可从 EvalData 形成并确认多道题", async ({ page }) => {
  const consoleErrors: string[] = [];
  const scoreRequestBodies: Record<string, unknown>[] = [];
  const rubricStartRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/rubric/start")) rubricStartRequests.push(request.url());
    if (request.method() !== "POST" || !request.url().includes("/submissions/") || !request.url().endsWith("/scores")) return;
    const body = request.postData();
    if (body) scoreRequestBodies.push(JSON.parse(body) as Record<string, unknown>);
  });

  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const username = `authoring-e2e-${nonce}`;
  const password = "authoring-e2e-pass-123";

  await page.goto("/login");
  await page.getByRole("button", { name: "注册" }).click();
  await page.getByRole("textbox", { name: "用户名 2–50 字" }).fill(username);
  await page.getByRole("textbox", { name: "邮箱 可留空" }).fill(`${username}@example.com`);
  await page.getByRole("textbox", { name: "密码 8–128 字符" }).fill(password);
  await page.getByRole("button", { name: "注册并进入" }).click();

  await expect(page).toHaveURL(/\/workspaces$/);
  await page.getByRole("textbox", { name: "名称 1–100 字" }).fill(`EvalData 真实 AI ${nonce}`);
  await page.getByRole("button", { name: "创建场景" }).click();
  const workspaceLink = page.getByRole("link", { name: "上传真实案例", exact: true }).last();
  await expect(workspaceLink).toBeVisible();
  await workspaceLink.click();

  await page.getByRole("textbox", { name: "批次标题 1–200 字" }).fill(`EvalData 批次 ${nonce}`);
  await page.getByRole("textbox", { name: /任务说明/ }).fill("从真实资料识别可独立验收的新闻稿题目，保留事实边界。");
  await page.locator('input[type="file"]').setInputFiles(SAMPLE_FILES);
  await page.getByRole("button", { name: "上传并开始分析" }).click();

  await expect(page).toHaveURL(/\/authoring\/new\?batch=/);
  await page.getByRole("button", { name: "开始建题" }).click();
  await expect(page).toHaveURL(/\/authoring\/[0-9a-f-]+$/);
  await expect(page.getByTestId("authoring-conversation")).toBeVisible();

  const boundaries = page.getByTestId("authoring-boundaries");
  await reloadUntilVisible(page, boundaries);
  const candidates = boundaries.locator('input[type="checkbox"]');
  await expect(candidates.first()).toBeVisible();
  expect(await candidates.count()).toBeGreaterThan(0);
  // This lifecycle gate follows one teacher-selected question end to end;
  // the backend still supports 0..N candidates, while the parent E2E covers
  // the multi-question branch separately.
  for (let index = 1; index < await candidates.count(); index += 1) {
    if (await candidates.nth(index).isChecked()) await candidates.nth(index).uncheck();
  }

  // A normal teacher correction is a second real AI turn. It must not change
  // the candidate boundary until the teacher explicitly confirms it.
  const attachments = page.getByTestId("authoring-attachment-picker").locator('input[type="checkbox"]');
  if (await attachments.count() > 0) await attachments.first().check();
  await page.getByRole("textbox", { name: "给 AI 的消息" }).fill("请保持不同交付物的候选题相互独立，不能混用证据。");
  await page.getByTestId("authoring-send").click();
  await reloadUntilVisible(page, boundaries);
  await expect(page.getByTestId("authoring-status")).toHaveText("待审阅", { timeout: 900_000 });
  const boundaryResponse = page.waitForResponse((response) => response.url().includes("/question-boundaries") && response.status() === 200);
  await boundaries.getByRole("button", { name: "确认选中题目" }).click();
  await boundaryResponse;
  // Keep one selected question for this end-to-end gate; explicitly discard
  // other AI candidates so the conversation can advance to the selected draft.
  await page.waitForTimeout(1_000);
  if (await boundaries.isVisible().catch(() => false)) {
    const remaining = boundaries.locator('input[type="checkbox"]');
    if (await remaining.count() > 0) {
      const discardResponse = page.waitForResponse((response) => response.url().includes("/question-boundaries") && response.status() === 200);
      await boundaries.getByRole("button", { name: "舍弃选中" }).click();
      await page.getByRole("button", { name: "确认舍弃", exact: true }).click();
      await discardResponse;
    }
  }

  const authoringDeadline = Date.now() + 840_000;
  while (Date.now() < authoringDeadline) {
    if (page.url().includes("/rubric")) break;
    const status = await page.getByTestId("authoring-status").innerText();
    if (status.includes("已确认")) break;
    if (status.includes("整理失败") || status.includes("等待恢复") || status.includes("重建连续性")) {
      throw new Error(`真实 AI 建题流程进入不可继续状态：${status}`);
    }
    const pendingBoundaries = page.getByTestId("authoring-boundaries");
    if (await pendingBoundaries.isVisible().catch(() => false)) {
      const pendingCandidates = pendingBoundaries.locator('input[type="checkbox"]');
      if (await pendingCandidates.count() > 0) {
        const discardResponse = page.waitForResponse((response) => response.url().includes("/question-boundaries") && response.status() === 200);
        await pendingBoundaries.getByRole("button", { name: "舍弃选中" }).click();
        await page.getByRole("button", { name: "确认舍弃", exact: true }).click();
        await discardResponse;
        await page.waitForTimeout(500);
        continue;
      }
    }

    const standardAnswer = page.getByRole("textbox", { name: "老师标准答案" });
    if (status.includes("需要补充")) {
      const answer = (await standardAnswer.count()) > 0
        ? standardAnswer
        : page.getByRole("textbox", { name: "给 AI 的消息" });
      await expect(answer).toBeVisible({ timeout: 15_000 });
      await answer.fill(
        (await standardAnswer.count()) > 0
          ? "老师终版确认：最终交付必须基于可复核事实，缺失信息不能自行补全。"
          : "老师补充确认：请只使用资料中可复核的事实，缺失内容不能自行补全。",
      );
      await expect(page.getByTestId("authoring-send")).toBeEnabled({ timeout: 15_000 });
      await page.getByTestId("authoring-send").click();
      await page.waitForTimeout(1_000);
      continue;
    }
    if (await standardAnswer.count() > 0) {
      await standardAnswer.fill("老师终版确认：最终交付必须基于可复核事实，缺失信息不能自行补全。");
      const send = page.getByTestId("authoring-send");
      if (await send.isDisabled()) {
        await page.waitForTimeout(1_000);
        continue;
      }
      await send.click();
      await page.waitForTimeout(1_000);
      continue;
    }

    const review = page.getByTestId("authoring-draft-review");
    if (await review.count() > 0 && await review.isVisible()) {
      // The authoring UI keeps the local draft visible while a real Worker
      // turn is still running, but deliberately disables persistence actions.
      // Wait for the authoritative snapshot before editing or confirming.
      const save = review.getByRole("button", { name: "保存修改" });
      if (await save.isDisabled()) {
        await page.waitForTimeout(1_000);
        continue;
      }
      const confirm = review.getByRole("button", { name: "确认题目并生成打分规则" });
      if (await confirm.count() > 0 && await confirm.isEnabled()) {
        await confirm.click();
        await page.waitForTimeout(500);
        continue;
      }
      const roles = review.locator("select");
      for (let index = 0; index < await roles.count(); index += 1) {
        await roles.nth(index).selectOption("fact");
      }
      await save.click();
      await page.waitForTimeout(500);
      continue;
    }

    await page.waitForTimeout(1_000);
  }

  // The second-stage rubric flow is entered by the single
  // “确认题目并生成打分规则” action and owns its own GET polling.
  await expect(page).toHaveURL(/\/authoring\/[0-9a-f-]+\/rubric(?:\?.*)?$/);
  await expect(page.getByTestId("rubric-page")).toBeVisible();
  const generateRubric = page.getByRole("button", { name: "生成打分规则" });
  if (await generateRubric.isVisible().catch(() => false)) await generateRubric.click();
  await expect(page.getByTestId("rubric-status")).toHaveText("待审阅", { timeout: 900_000 });
  await expect(page.getByText("评分项满分 / 100")).toBeVisible();
  const referencePass = page.getByText("标准答案可通过");
  if (!(await referencePass.isVisible().catch(() => false))) {
    // A real model may propose a conservative critical-item anchor.  That is
    // a valid review state, not a publishable state: exercise the teacher's
    // explicit correction path before continuing.
    const criteria = page.getByTestId("rubric-editor").locator("article");
    for (let index = 0; index < await criteria.count(); index += 1) {
      const criterion = criteria.nth(index);
      const maxScore = await criterion.getByLabel("满分", { exact: true }).inputValue();
      await criterion.getByLabel("标准答案期望得分", { exact: true }).fill(maxScore);
      const hardFail = criterion.getByLabel("标准答案命中该条件", { exact: true });
      if (await hardFail.count() > 0 && await hardFail.isChecked()) await hardFail.uncheck();
    }
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
  }
  await expect(referencePass).toBeVisible();

  await page.getByRole("button", { name: "确认规则并发布到评测集" }).click();
  await page.getByRole("button", { name: "确认规则并发布", exact: true }).click();
  await expect(page.getByTestId("rubric-status")).toHaveText("已发布", { timeout: 30_000 });
  await expect(page.getByText("已进入当前评测集")).toBeVisible();
  await expect(page.getByText("已发布修订")).toBeVisible();
  expect(rubricStartRequests.length).toBe(1);

  // Human scoring is intentionally not an AI operation. The answer itself is
  // still a real EvalData file, and the page must bind it to the exact
  // published revision returned by the real provider/worker flow above.
  await page.getByRole("link", { name: "提交待评答卷" }).click();
  await expect(page).toHaveURL(/\/question-revisions\/[0-9a-f-]+\/submissions\/new$/);
  await page.getByRole("button", { name: "上传文件" }).click();
  await page.locator('input[type="file"]').setInputFiles(SAMPLE_FILES[2]);
  await page.getByRole("button", { name: "保存并开始评分" }).click();
  await expect(page).toHaveURL(/\/submissions\/[0-9a-f-]+$/);
  await expect(page.getByTestId("human-scoring-page")).toBeVisible();

  const criteria = page.locator('article[data-testid^="criterion-"]');
  await expect(criteria.first()).toBeVisible();
  expect(await criteria.count()).toBeGreaterThan(0);
  for (let index = 0; index < await criteria.count(); index += 1) {
    const criterion = criteria.nth(index);
    const score = criterion.getByLabel("待评得分");
    const maximum = await score.getAttribute("max");
    await score.fill(maximum ?? "0");
    const safeHardFail = criterion.getByLabel("未命中");
    if (await safeHardFail.count() > 0) await safeHardFail.check();
  }
  await page.getByRole("button", { name: "提交评分" }).click();
  await expect(page.getByTestId("score-result")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("score-history")).toContainText("1 次");
  expect(scoreRequestBodies.length).toBe(1);
  expect(scoreRequestBodies[0]).not.toHaveProperty("total_score");
  expect(scoreRequestBodies[0]).not.toHaveProperty("passed");
  expect(scoreRequestBodies[0]).not.toHaveProperty("critical_passed");

  await page.reload();
  await expect(page.getByRole("button", { name: "重新评分" })).toBeVisible();
  await page.getByRole("button", { name: "重新评分" }).click();
  const firstCriterion = page.locator('article[data-testid^="criterion-"]').first();
  await firstCriterion.getByLabel("待评得分").fill("0");
  const firstSafeHardFail = firstCriterion.getByLabel("未命中");
  if (await firstSafeHardFail.count() > 0) await firstSafeHardFail.check();
  await firstCriterion.getByLabel(/评分理由/).fill("本轮复核发现第一项没有达到标准答案锚点。");
  await page.getByRole("button", { name: "保存重新评分" }).click();
  await expect(page.getByTestId("score-history")).toContainText("2 次", { timeout: 30_000 });
  expect(scoreRequestBodies.length).toBe(2);
  expect(scoreRequestBodies[1]).not.toHaveProperty("total_score");
  expect(scoreRequestBodies[1]).not.toHaveProperty("passed");
  expect(scoreRequestBodies[1]).not.toHaveProperty("critical_passed");

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileWidths = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: window.innerWidth }));
  expect(mobileWidths.body).toBeLessThanOrEqual(mobileWidths.viewport);

  expect(consoleErrors).toEqual([]);
});
