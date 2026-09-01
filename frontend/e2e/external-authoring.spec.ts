import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const EVAL_MARKDOWN = "/Users/hsikey/BenchMark/EvalData/理想汽车供稿-对话上下文-2026-08-27.md";

test.skip(process.env.E2E_EXTERNAL !== "1", "需要 E2E_EXTERNAL=1 执行真实外部收题流程");

test("外部连接码只创建草稿并回到精确网站题稿", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const username = `external-browser-${nonce}`;
  const password = "external-browser-pass-123";

  await page.goto("/login");
  await page.getByRole("button", { name: "注册" }).click();
  await page.getByRole("textbox", { name: "用户名 2–50 字" }).fill(username);
  await page.getByRole("textbox", { name: "邮箱 可留空" }).fill(`${username}@example.com`);
  await page.getByRole("textbox", { name: "密码 8–128 字符" }).fill(password);
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page).toHaveURL(/\/workspaces$/);
  await page.getByRole("textbox", { name: "名称 1–100 字" }).fill(`外部收题浏览器验收 ${nonce}`);
  await page.getByRole("button", { name: "创建场景" }).click();
  const workspaceLink = page.getByRole("link", { name: "上传真实案例", exact: true }).last();
  await expect(workspaceLink).toBeVisible();
  const workspaceHref = await workspaceLink.getAttribute("href");
  const workspaceId = workspaceHref?.split("/")[2];
  expect(workspaceId).toBeTruthy();
  await page.goto(`/workspaces/${workspaceId}`);

  const connectionPanel = page.getByTestId("agent-connection");
  await expect(connectionPanel).toBeVisible();
  await connectionPanel.getByRole("button", { name: "创建连接码" }).click();
  const code = await page.getByRole("textbox", { name: "一次性连接码" }).inputValue();
  expect(code.length).toBeGreaterThan(20);

  const exchange = await page.request.post("/api/external/authoring-connections/exchange", {
    data: { connection_code: code },
  });
  expect(exchange.status()).toBe(200);
  const exchanged = await exchange.json() as { access_token: string };
  expect(exchanged.access_token).toBeTruthy();

  const sourceText = readFileSync(EVAL_MARKDOWN, "utf8");
  const browserSourceText = sourceText.replace(/\r\n?/g, "\n");
  const sourceBytes = Buffer.from(sourceText, "utf8");
  const push = await page.request.post("/api/external/evaluation-case-drafts", {
    headers: { Authorization: `Bearer ${exchanged.access_token}` },
    data: {
      schema_version: "1.0",
      command_id: `browser-${nonce}`,
      title: "浏览器外部题稿",
      task_requirement: "  浏览器验收时老师输入的原始任务\n保留空白。  ",
      input_files: [{
        client_file_id: "evaldata-markdown",
        display_name: "理想汽车供稿-对话上下文-2026-08-27.md",
        media_type: "text/markdown",
        content_mode: "full",
        content_text: sourceText,
        source_size_bytes: sourceBytes.length,
        source_sha256: createHash("sha256").update(sourceBytes).digest("hex"),
      }],
      bad_samples: [],
      reference_answer_text: "浏览器验收老师认可的标准答案。",
    },
  });
  expect(push.status()).toBe(201);
  const result = await push.json() as { draft_url: string; draft_id: string };
  expect(result.draft_url).toContain(`?draft=${result.draft_id}`);
  expect(result.draft_url).not.toContain(exchanged.access_token);

  await page.getByRole("button", { name: "关闭" }).click();
  await page.goto(result.draft_url);
  await expect(page.getByTestId("authoring-conversation")).toBeVisible();
  await expect(page.getByTestId("authoring-draft-review").getByRole("heading", { name: "浏览器外部题稿" })).toBeVisible();
  await expect(page.getByTestId("authoring-status")).toHaveText("待审阅");
  await expect(page.getByLabel("任务指令")).toHaveValue("  浏览器验收时老师输入的原始任务\n保留空白。  ");
  const inputFileText = await page.locator('textarea[id^="input-file-"]').inputValue();
  expect(inputFileText).toBe(browserSourceText);

  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: window.innerWidth }));
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
  expect(consoleErrors).toEqual([]);
});
