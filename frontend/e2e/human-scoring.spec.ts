import { expect, test } from "@playwright/test";

const workspace = "preview-workspace";
const revision = "preview-question-revision";

test("人工评分入口和评分草稿预演保持可操作", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto(`/workspaces/${workspace}/question-revisions/${revision}/submissions/new?preview=loading`);
  await expect(page.locator('main[aria-busy="true"]')).toBeVisible();
  await page.goto(`/workspaces/${workspace}/question-revisions/${revision}/submissions/new?preview=human_entry`);
  await expect(page.getByTestId("submission-entry")).toBeVisible();
  await expect(page.getByRole("button", { name: "粘贴文本" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "上传文件" }).click();
  await expect(page.getByLabel("答卷文件")).toBeVisible();
  await page.getByRole("button", { name: "粘贴文本" }).click();
  await page.getByLabel("待评文本").fill("一份用于预演的待评答卷。\n事实边界清晰。 ");
  await expect(page.getByRole("button", { name: "保存并开始评分" })).toBeEnabled();

  await page.goto(`/workspaces/${workspace}/submissions/preview-submission?preview=human_draft`);
  await expect(page.getByTestId("human-scoring-page")).toBeVisible();
  await expect(page.getByText("标准答案期望得分").first()).toBeVisible();
  await expect(page.getByLabel("待评得分").first()).toBeVisible();
  await page.getByLabel("待评得分").first().fill("50");
  await page.getByLabel("评分理由").first().fill("有一条事实没有给出对应依据。");
  await page.getByLabel("待评得分").nth(1).fill("40");
  await expect(page.getByRole("button", { name: "提交评分" })).toBeEnabled();

  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: window.innerWidth }));
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
  expect(consoleErrors).toEqual([]);
});

test("已提交和重评历史预演不会隐藏 lineage", async ({ page }) => {
  await page.goto(`/workspaces/${workspace}/submissions/preview-submission?preview=human_submitted`);
  await expect(page.getByTestId("score-result")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新评分" })).toBeVisible();
  await expect(page.getByTestId("score-history")).toContainText("首次评分");

  await page.goto(`/workspaces/${workspace}/submissions/preview-submission?preview=human_history`);
  await expect(page.getByTestId("score-history")).toContainText("2 次");
  await expect(page.getByTestId("score-history")).toContainText("基于第 1 次评分");

  await page.goto(`/workspaces/${workspace}/submissions/preview-submission?preview=forbidden`);
  await expect(page.getByText("无法访问")).toBeVisible();
  await expect(page.getByTestId("human-scoring-page")).toHaveCount(0);
});
