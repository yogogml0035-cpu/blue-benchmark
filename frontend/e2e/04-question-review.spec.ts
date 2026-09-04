import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Question review workbench flows against the real backend + a fake-mode
 * worker (deterministic generation). Real-AI acceptance happens in the final
 * integration task; here we verify the workbench mechanics end to end.
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

async function cookieHeader(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

/** Create a scene, issue a credential, and upload one question; return ids. */
async function seedQuestion(page: Page, request: APIRequestContext, sceneName: string): Promise<{ sceneId: string; questionId: string; token: string }> {
  await page.goto("/evaluation-sets");
  await page.getByRole("button", { name: "创建评测集" }).first().click();
  await page.getByLabel("名称").fill(sceneName);
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await expect(page.getByRole("heading", { name: sceneName })).toBeVisible();
  const sceneId = page.url().split("/").pop()!;

  await page.getByRole("button", { name: "生成上传凭证" }).click();
  const prompt = await page.getByRole("textbox", { name: "绑定提示词" }).inputValue();
  const token = prompt.match(/sep_[A-Za-z0-9_-]+/)![0];
  await page.getByRole("button", { name: "关闭", exact: true }).click();

  const upload = await request.post("http://127.0.0.1:3000/api/external/question-batches", {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      schema_version: "1.0",
      command_id: `e2e-${Date.now()}`,
      cases: [
        {
          client_case_id: "workbench-case",
          title: "工作台测试用例",
          task_prompt: "请把提供的素材整理成一段正式说明。",
          reference_examples: [
            { client_ref_id: "ref-1", source_name: "素材", content_text: "老师提供并实际读取过的素材正文。" },
          ],
          bad_cases: [
            { content_text: "被否定的初稿。", teacher_feedback_texts: ["语气太随意。"], reason_summary: "语体不符。" },
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
  const questionId = (await upload.json()).cases[0].question_id;

  // Wait for the fake worker to finish generation (polling -> pending_review).
  const cookie = await cookieHeader(page);
  await expect
    .poll(
      async () => {
        const r = await request.get(`http://127.0.0.1:3000/api/questions/${questionId}`, {
          headers: { Cookie: cookie },
        });
        return r.status() === 200 ? (await r.json()).status : "unknown";
      },
      { timeout: 30_000 },
    )
    .toBe("pending_review");

  return { sceneId, questionId, token };
}

test("workbench shows AI candidates unselected and blocks premature publish/save", async ({ page, request }) => {
  await ensureLoggedIn(page);
  const { sceneId, questionId } = await seedQuestion(page, request, "审改评测集A");

  await page.goto(`/evaluation-sets/${sceneId}/questions/${questionId}`);
  await expect(page.getByRole("heading", { name: "工作台测试用例" })).toBeVisible();

  // AI candidates are all unselected initially.
  const checkboxes = page.locator('input[type="checkbox"][aria-label^="选择维度"]');
  await expect(checkboxes).toHaveCount(3);
  for (const cb of await checkboxes.all()) {
    expect(await cb.isChecked()).toBe(false);
  }

  // No publish button while unconfirmed.
  await expect(page.getByRole("button", { name: "发布" })).toHaveCount(0);

  // Saving with zero selected fails validation inline.
  await page.getByRole("button", { name: "保存维度" }).click();
  await expect(page.getByText("至少选择 1 个评分维度。")).toBeVisible();
});

test("teacher selects candidates, saves, then publishes", async ({ page, request }) => {
  await ensureLoggedIn(page);
  const { sceneId, questionId } = await seedQuestion(page, request, "审改评测集B");

  await page.goto(`/evaluation-sets/${sceneId}/questions/${questionId}`);
  const checkboxes = page.locator('input[type="checkbox"][aria-label^="选择维度"]');
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  await page.getByRole("button", { name: "保存维度" }).click();
  await page.getByRole("button", { name: "确认保存" }).click();

  // Now confirmed: publish button appears.
  await expect(page.getByRole("button", { name: "发布" })).toBeVisible();
  await page.getByRole("button", { name: "发布" }).click();
  await expect(page.getByText("已发布", { exact: true }).first()).toBeVisible();
});

test("published question reopens, keeps criteria, and requires title to delete", async ({ page, request }) => {
  await ensureLoggedIn(page);
  const { sceneId, questionId } = await seedQuestion(page, request, "审改评测集C");

  await page.goto(`/evaluation-sets/${sceneId}/questions/${questionId}`);
  // Select + save + publish.
  const checkboxes = page.locator('input[type="checkbox"][aria-label^="选择维度"]');
  await checkboxes.nth(0).check();
  await page.getByRole("button", { name: "保存维度" }).click();
  await page.getByRole("button", { name: "确认保存" }).click();
  await page.getByRole("button", { name: "发布" }).click();
  await expect(page.getByText("已发布", { exact: true }).first()).toBeVisible();

  // Published: no direct delete; reopen is offered.
  await expect(page.getByRole("button", { name: "删除题目" })).toHaveCount(0);
  await page.getByRole("button", { name: "重新打开审改" }).click();
  await expect(page.getByText("待审改", { exact: true }).first()).toBeVisible();
  // Criteria survived the reopen.
  await expect(page.locator('input[type="checkbox"][aria-label^="选择维度"]').first()).toBeChecked();

  // Delete now requires typing the full title.
  await page.getByRole("button", { name: "删除题目" }).click();
  await page.getByLabel("题目标题").fill("工作台测试用例");
  await page.getByRole("dialog", { name: "删除题目" }).getByRole("button", { name: "删除" }).click();
  await expect(page).toHaveURL(/\/evaluation-sets\/.+$/);
});
