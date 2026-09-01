import { expect, test } from "@playwright/test";

test("生命周期主流程预演只有组合动作和只读历史入口", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto("/workspaces/preview-workspace/authoring/preview-conversation?preview=review");
  await expect(page.getByTestId("authoring-draft-review")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认题目并生成打分规则" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认题目输入" })).toHaveCount(0);

  await page.goto("/workspaces/preview-workspace/authoring/preview-conversation/rubric?preview=rubric_review");
  await expect(page.getByTestId("rubric-page")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认规则并发布到评测集" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认打分规则" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发布为题目修订" })).toHaveCount(0);

  await page.goto("/workspaces/preview-workspace?section=versions&preview=success");
  await expect(page.getByText("这里不再编排下一版")).toBeVisible();
  await expect(page.getByText("冻结")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: window.innerWidth }));
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
  expect(consoleErrors).toEqual([]);
});
