import { expect, test } from "@playwright/test";

test("生命周期主流程预演只有组合动作和只读历史入口", async ({ page }) => {
  const consoleErrors: string[] = [];
  const businessRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/api/")) businessRequests.push(request.url());
  });

  await page.goto("/login?preview=loading");
  await expect(page.locator('[aria-busy="true"]')).toBeVisible();

  await page.goto("/workspaces/preview-workspace/authoring/preview-conversation?preview=review");
  await expect(page.getByTestId("authoring-draft-review")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认题目并生成打分规则" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认题目输入" })).toHaveCount(0);

  await page.goto("/workspaces/preview-workspace/authoring/preview-conversation/rubric?preview=rubric_review");
  await expect(page.getByTestId("rubric-page")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认规则并发布到评测集" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认打分规则" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发布为题目修订" })).toHaveCount(0);
  await expect(page.getByText("fact_accuracy", { exact: true })).toHaveCount(0);

  await page.goto("/workspaces/preview-workspace?section=current&preview=success");
  const currentHeading = page.getByRole("heading", { name: "当前", exact: true });
  const connectionHeading = page.getByRole("heading", { name: "连接本地 Agent", exact: true });
  await expect(currentHeading).toBeVisible();
  await expect(connectionHeading).toBeVisible();
  const currentBox = await currentHeading.boundingBox();
  const connectionBox = await connectionHeading.boundingBox();
  expect(currentBox?.y).toBeLessThan(connectionBox?.y ?? 0);
  const primaryStyle = await page.getByRole("button", { name: "确认资料用途" }).evaluate((node) => ({
    background: getComputedStyle(node).backgroundColor,
    action: getComputedStyle(document.documentElement).getPropertyValue("--action").trim(),
  }));
  expect(primaryStyle.background).toBe("rgb(29, 29, 31)");
  expect(primaryStyle.action).toBe("#1d1d1f");
  await expect(page.getByRole("button", { name: "切换工作区导航" })).toBeHidden();

  await page.setViewportSize({ width: 390, height: 844 });
  const currentWidths = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: window.innerWidth }));
  expect(currentWidths.body).toBeLessThanOrEqual(currentWidths.viewport);
  await page.getByRole("button", { name: "切换工作区导航" }).click();
  const mobileNavigation = page.getByRole("dialog", { name: "场景导航" });
  await expect(mobileNavigation).toBeVisible();
  await expect(mobileNavigation.getByRole("link", { name: "当前", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(mobileNavigation.getByRole("link", { name: "当前", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(mobileNavigation).toHaveCount(0);
  await expect(page.getByRole("button", { name: "切换工作区导航" })).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.goto("/workspaces/preview-workspace?section=versions&preview=success");
  await expect(page.getByText("这里不再编排下一版")).toBeVisible();
  await expect(page.getByText("冻结")).toHaveCount(0);

  await page.goto("/workspaces/preview-workspace?preview=loading");
  await expect(page.locator('[aria-busy="true"]')).toBeVisible();
  await expect(page.getByTestId("agent-connection")).toHaveCount(0);

  await page.goto("/workspaces/preview-workspace?preview=forbidden");
  await expect(page.getByText("工作台读取失败")).toBeVisible();
  await expect(page.getByTestId("agent-connection")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: window.innerWidth }));
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
  expect(businessRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
