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
    await page.reload({ waitUntil: "domcontentloaded" });
    if (await target.isVisible().catch(() => false)) return;
    await page.waitForTimeout(1_500);
  }
  throw new Error("页面在服务端快照完成后仍未出现预期状态");
}

test.skip(process.env.E2E_REAL_AI !== "1", "需要 E2E_REAL_AI=1 才执行真实 Provider 流程");

test("真实 AI 可从 EvalData 形成并确认多道题", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

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

  const authoringDeadline = Date.now() + 840_000;
  while (Date.now() < authoringDeadline) {
    const status = await page.getByTestId("authoring-status").innerText();
    if (status.includes("已确认")) break;
    if (status.includes("整理失败") || status.includes("等待恢复") || status.includes("重建连续性")) {
      throw new Error(`真实 AI 建题流程进入不可继续状态：${status}`);
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
      const roles = review.locator("select");
      for (let index = 0; index < await roles.count(); index += 1) {
        await roles.nth(index).selectOption("fact");
      }
      await save.click();
      const confirm = review.getByRole("button", { name: "确认题目输入" });
      await expect(confirm).toBeEnabled();
      await confirm.click();
      await page.waitForTimeout(500);
      continue;
    }

    await page.waitForTimeout(1_000);
  }

  await expect(page.getByTestId("authoring-status")).toHaveText("已确认", { timeout: 60_000 });
  await page.reload();
  await expect(page.getByTestId("authoring-status")).toHaveText("已确认", { timeout: 30_000 });
  expect(consoleErrors).toEqual([]);
});
