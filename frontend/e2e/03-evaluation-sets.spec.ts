import { expect, test, type Page } from "@playwright/test";

/**
 * Evaluation-set and credential flows against the real backend. Runs serially
 * per project; each project gets the shared isolated backend (admin already
 * exists from the auth specs on chromium, created here otherwise).
 */

test.describe.configure({ mode: "serial" });

const ADMIN = { username: "benchmark-admin", email: "benchmark-admin@example.com", password: "benchmark-admin-password-1" };

async function ensureLoggedIn(page: Page): Promise<void> {
  await page.goto("/");
  await page.waitForURL(/\/(register|login|evaluation-sets)$/, { timeout: 15_000 });
  if (/\/register$/.test(page.url())) {
    await page.getByLabel("用户名").fill(ADMIN.username);
    await page.getByLabel("邮箱（可选）").fill(ADMIN.email);
    await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
    await page.getByLabel("确认密码").fill(ADMIN.password);
    await page.getByRole("button", { name: "创建管理员" }).click();
    await expect(page).toHaveURL(/\/evaluation-sets$/);
    return;
  }
  if (/\/login$/.test(page.url())) {
    await page.getByLabel("邮箱地址").fill(ADMIN.username);
    await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
    await page.getByRole("button", { name: "登 录" }).click();
    await expect(page).toHaveURL(/\/evaluation-sets$/);
  }
}

async function createEvaluationSet(page: Page, name: string, description?: string): Promise<void> {
  await page.getByRole("button", { name: "创建评测集" }).first().click();
  await page.getByLabel("名称").fill(name);
  if (description !== undefined) await page.getByLabel("描述（可选）").fill(description);
  await page.getByRole("button", { name: "创建", exact: true }).click();
}

test("logged-in admin lands on the evaluation-set list", async ({ page }) => {
  await ensureLoggedIn(page);
  await expect(page.getByRole("heading", { name: "评测集", level: 1 })).toBeVisible();
});

test("creates an evaluation set without auto-issuing credentials", async ({ page }) => {
  await ensureLoggedIn(page);
  await createEvaluationSet(page, "媒体评测集", "用于媒体改写场景");

  // Lands on the detail page.
  await expect(page.getByRole("heading", { name: "媒体评测集" })).toBeVisible();
  // No credential was auto-issued: the panel shows the empty state.
  await expect(page.getByText("尚未签发凭证")).toBeVisible();
  await expect(page.getByText("未签发", { exact: true })).toBeVisible();
});

test("rejects a duplicate scene name with a real 409", async ({ page }) => {
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await createEvaluationSet(page, "媒体评测集");
  // The form surfaces the name conflict inline.
  await expect(page.getByText("同名评测集已经存在。")).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
});

test("issues a credential and shows the one-time prompt exactly once", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await page.getByRole("link", { name: /媒体评测集/ }).first().click();
  await expect(page.getByRole("heading", { name: "媒体评测集" })).toBeVisible();

  await page.getByRole("button", { name: "生成上传凭证" }).click();

  // The prompt dialog appears with the token-bearing text.
  const promptBox = page.getByRole("textbox", { name: "绑定提示词" });
  await expect(promptBox).toBeVisible();
  const promptText = await promptBox.inputValue();
  expect(promptText).toContain("ai-eval-push");
  expect(promptText).toContain("connection");

  // The token appears exactly once in the prompt.
  const tokenMatch = promptText.match(/sep_[A-Za-z0-9_-]+/);
  expect(tokenMatch).not.toBeNull();
  const token = tokenMatch![0];
  const occurrences = promptText.split(token).length - 1;
  expect(occurrences).toBe(1);

  // Copy succeeds (Chromium with granted permission).
  await page.getByRole("button", { name: "复制提示词" }).click();
  await expect(page.getByRole("button", { name: "已复制" })).toBeVisible();

  // Close the dialog: the plaintext is cleared and cannot be recovered.
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "绑定提示词" })).toHaveCount(0);

  // The token never lands in the URL, and the issued credential shows active.
  expect(page.url()).not.toContain(token);
  await expect(page.getByText("已签发待验证", { exact: true })).toBeVisible();

  // Capture the token for later rotate/external-upload tests via test info.
  test.info().annotations.push({ type: "issued_token", description: "present-once" });
});

test("renames an evaluation set", async ({ page }) => {
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await page.getByRole("link", { name: /媒体评测集/ }).first().click();
  await page.getByRole("button", { name: "编辑" }).click();
  await page.getByLabel("名称").fill("媒体评测集·改名");
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByRole("heading", { name: "媒体评测集·改名" })).toBeVisible();
});

test("rotate revokes old credentials; only the newest connects", async ({ page, context, request }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await page.getByRole("link", { name: /媒体评测集·改名/ }).first().click();

  // Issue a first credential and capture its token.
  await page.getByRole("button", { name: "生成上传凭证" }).click();
  const firstPrompt = await page.getByRole("textbox", { name: "绑定提示词" }).inputValue();
  const firstToken = firstPrompt.match(/sep_[A-Za-z0-9_-]+/)![0];
  await page.getByRole("button", { name: "复制提示词" }).click();
  await page.getByRole("button", { name: "关闭", exact: true }).click();

  // Rotate: confirm the destructive action.
  await page.getByRole("button", { name: "轮换凭证" }).click();
  await page.getByRole("button", { name: "轮换", exact: true }).click();
  const rotatedPrompt = await page.getByRole("textbox", { name: "绑定提示词" }).inputValue();
  const rotatedToken = rotatedPrompt.match(/sep_[A-Za-z0-9_-]+/)![0];
  expect(rotatedToken).not.toBe(firstToken);
  await page.getByRole("button", { name: "复制提示词" }).click();
  await page.getByRole("button", { name: "关闭", exact: true }).click();

  const conn = "http://127.0.0.1:3000/api/external/connection";
  // The old credential no longer connects.
  const oldResp = await request.get(conn, { headers: { Authorization: `Bearer ${firstToken}` } });
  expect(oldResp.status()).toBe(401);
  // The rotated credential connects.
  const newResp = await request.get(conn, { headers: { Authorization: `Bearer ${rotatedToken}` } });
  expect(newResp.status()).toBe(200);

  // Timeline shows one active and one revoked credential.
  await expect(page.getByText("已撤销", { exact: true }).first()).toBeVisible();
});

test("revokes a single active credential", async ({ page }) => {
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await page.getByRole("link", { name: /媒体评测集·改名/ }).first().click();
  await page.getByRole("button", { name: /撤销凭证/ }).first().click();
  await page.getByRole("dialog", { name: "撤销凭证" }).getByRole("button", { name: "撤销" }).click();
  // After revoking the last active credential the scene is disabled.
  await expect(page.getByText("已停用", { exact: true })).toBeVisible();
});

test("deletes an empty evaluation set", async ({ page }) => {
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await createEvaluationSet(page, "待删除评测集");
  await expect(page.getByRole("heading", { name: "待删除评测集" })).toBeVisible();
  await page.getByRole("button", { name: "删除" }).click();
  await page.getByRole("dialog", { name: "删除评测集" }).getByRole("button", { name: "删除" }).click();
  await expect(page).toHaveURL(/\/evaluation-sets$/);
  await expect(page.getByRole("link", { name: /待删除评测集/ })).toHaveCount(0);
});

test("a non-empty evaluation set cannot be deleted", async ({ page, context, request }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await ensureLoggedIn(page);
  await page.goto("/evaluation-sets");
  await createEvaluationSet(page, "含题评测集");
  await expect(page.getByRole("heading", { name: "含题评测集" })).toBeVisible();

  // Issue a credential, then push a question through the external endpoint so
  // the scene becomes non-empty.
  await page.getByRole("button", { name: "生成上传凭证" }).click();
  const prompt = await page.getByRole("textbox", { name: "绑定提示词" }).inputValue();
  const token = prompt.match(/sep_[A-Za-z0-9_-]+/)![0];
  await page.getByRole("button", { name: "复制提示词" }).click();
  await page.getByRole("button", { name: "关闭", exact: true }).click();

  const sceneId = page.url().split("/").pop();
  const upload = await request.post("http://127.0.0.1:3000/api/external/question-batches", {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      schema_version: "1.0",
      command_id: "e2e-nonempty-cmd",
      cases: [
        {
          client_case_id: "e2e-case-1",
          title: "E2E 用例",
          task_prompt: "请把提供的素材整理成一段正式说明。",
          reference_examples: [
            { client_ref_id: "ref-1", source_name: "素材", content_text: "这是老师提供并实际读取过的素材正文。" },
          ],
          bad_cases: [
            {
              content_text: "这是被否定的初稿。",
              teacher_feedback_texts: ["语气过于随意。"],
              reason_summary: "语体不符。",
            },
          ],
          reference_answer: "这是标准答案。",
          memory_materials: [
            { client_ref_id: "mem-1", source_label: "记忆", content_text: "本轮加载的相关记忆。" },
          ],
        },
      ],
    },
  });
  expect(upload.status()).toBe(201);

  // Reload the detail; the delete affordance is gone for a non-empty scene.
  await page.reload();
  await expect(page.getByRole("button", { name: "删除" })).toHaveCount(0);

  // The backend still refuses an authenticated direct delete with a 409.
  const cookieHeader = await page
    .context()
    .cookies()
    .then((cookies) => cookies.map((c) => `${c.name}=${c.value}`).join("; "));
  const del = await request.delete(`http://127.0.0.1:3000/api/scenes/${sceneId}`, {
    headers: { Cookie: cookieHeader },
  });
  expect(del.status()).toBe(409);
});

test("unauthenticated scene access is rejected (401)", async ({ request }) => {
  const resp = await request.get("http://127.0.0.1:3000/api/scenes");
  expect(resp.status()).toBe(401);
});

test("twenty evaluation-set folders render in a stable grid", async ({ page, request }) => {
  await ensureLoggedIn(page);
  // Seed scenes via the API for speed (the UI create path is covered above).
  const cookieHeader = await page
    .context()
    .cookies()
    .then((cookies) => cookies.map((c) => `${c.name}=${c.value}`).join("; "));
  for (let i = 0; i < 20; i += 1) {
    const resp = await request.post("http://127.0.0.1:3000/api/scenes", {
      headers: { Cookie: cookieHeader },
      data: { name: `批量评测集 ${String(i + 1).padStart(2, "0")}` },
    });
    expect([201, 409]).toContain(resp.status());
  }
  await page.goto("/evaluation-sets");
  const cards = page.locator('a[href^="/evaluation-sets/"]');
  await expect.poll(async () => cards.count(), { timeout: 10_000 }).toBeGreaterThanOrEqual(20);
  // No horizontal overflow at the desktop width.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});
