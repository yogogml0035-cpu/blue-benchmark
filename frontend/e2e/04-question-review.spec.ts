import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { ADMIN } from "./admin";

/**
 * Question review workbench flows against the real backend + a fake-mode
 * worker (deterministic generation). Real-AI acceptance (live streaming
 * during an actual long generation, PostgreSQL checkpoints) happens in the
 * real-acceptance runner; here we verify the workbench mechanics end to end:
 * complete-criterion editing, anchors/basis UI, regeneration confirmation,
 * process replay and the accepted-deletion flow.
 */

test.describe.configure({ mode: "serial" });

async function ensureLoggedIn(page: Page): Promise<void> {
  await page.goto("/");
  // The admin is seeded from ADMIN_USERNAME / ADMIN_PASSWORD by the backend
  // lifespan, so the entry router can only land on login (or the app when a
  // session already exists).
  await page.waitForURL(/\/(login|evaluation-sets)$/, { timeout: 15_000 });
  if (/\/login$/.test(page.url())) {
    await page.getByLabel("用户名").fill(ADMIN.username);
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
async function seedQuestion(
  page: Page,
  request: APIRequestContext,
  sceneNameBase: string,
  opts: { waitSettled?: boolean } = {},
): Promise<{ sceneId: string; questionId: string; token: string }> {
  // Unique per attempt so serial-group retries never collide with the
  // previous run's scene (uq_scene_name).
  const sceneName = `${sceneNameBase}-${Date.now().toString(36)}`;
  await page.goto("/evaluation-sets");
  await page.getByRole("button", { name: "创建评测集" }).first().click();
  await page.getByLabel("名称").fill(sceneName);
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await expect(page.getByRole("heading", { name: sceneName })).toBeVisible();
  const sceneId = page.url().split("/").pop()!;

  // 1:1 credential model: one create button, then the one-time handoff prompt
  // dialog. Copying is not needed here, so closing asks for confirmation.
  await page.getByRole("button", { name: "创建凭证" }).click();
  const promptBox = page.getByRole("textbox", { name: "绑定提示词" });
  await expect(promptBox).toBeVisible();
  const token = (await promptBox.inputValue()).match(/sep_[A-Za-z0-9_-]+/)![0];
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "不复制并关闭" }).click();

  const upload = await request.post("/api/external/question-batches", {
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

  if (opts.waitSettled !== false) {
    // Wait for the fake worker to finish generation (polling -> pending_review).
    const cookie = await cookieHeader(page);
    await expect
      .poll(
        async () => {
          const r = await request.get(`/api/questions/${questionId}`, {
            headers: { Cookie: cookie },
          });
          return r.status() === 200 ? (await r.json()).status : "unknown";
        },
        { timeout: 30_000 },
      )
      .toBe("pending_review");
  }

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

  // Complete contract is visible: anchors and a basis disclosure per criterion.
  await expect(page.getByRole("button", { name: "查看依据" }).first()).toBeVisible();
  await page.getByRole("button", { name: "查看依据" }).first().click();
  await expect(page.getByText("为什么设这个维度").first()).toBeVisible();
  await expect(page.getByText("老师明确要求").first()).toBeVisible();
  await expect(page.getByText("AI 推定").first()).toBeVisible();

  // No publish button while unconfirmed.
  await expect(page.getByRole("button", { name: "发布" })).toHaveCount(0);

  // Saving with zero selected fails validation inline.
  await page.getByRole("button", { name: "保存维度" }).click();
  await expect(page.getByText("至少选择 1 个评分维度。")).toBeVisible();
});

test("teacher saves an unanchored integer score with a stale-basis hint", async ({ page, request }) => {
  await ensureLoggedIn(page);
  const { sceneId, questionId } = await seedQuestion(page, request, "审改评测集D");

  await page.goto(`/evaluation-sets/${sceneId}/questions/${questionId}`);
  const checkboxes = page.locator('input[type="checkbox"][aria-label^="选择维度"]');
  await checkboxes.nth(0).check();

  // Fake anchors are {4,7,9} for the first criterion: 5 is deliberately
  // unanchored. Saving it must succeed (anchors are not a whitelist) and the
  // stale-explanation hint must appear without rewriting anything.
  const scoreInput = page.locator('input[aria-label$="的通过分"]').first();
  await scoreInput.fill("5");
  await expect(page.getByText(/原通过分依据对应 \d+ 分，当前通过分为 5 分/)).toBeVisible();

  await page.getByRole("button", { name: "保存维度" }).click();
  await page.getByRole("button", { name: "确认保存" }).click();

  // Saved: publish becomes available and the score survived the round trip.
  await expect(page.getByRole("button", { name: "发布" })).toBeVisible();
  const cookie = await cookieHeader(page);
  const detail = await (
    await request.get(`/api/questions/${questionId}`, { headers: { Cookie: cookie } })
  ).json();
  expect(detail.criteria[0].pass_score).toBe(5);
  expect(detail.criteria[0].pass_score_basis.explained_score).not.toBe(5);
  expect(detail.criteria[0].score_anchors.map((a: { score: number }) => a.score)).not.toContain(5);
});

test("completed run keeps a full public process replay", async ({ page, request }) => {
  await ensureLoggedIn(page);
  const { sceneId, questionId } = await seedQuestion(page, request, "审改评测集E");

  await page.goto(`/evaluation-sets/${sceneId}/questions/${questionId}`);
  await page.getByRole("button", { name: "查看完整生成过程" }).click();
  const body = page.getByTestId("timeline-body");
  await expect(body).toBeVisible();
  // The replay shows real stage events and the authoritative completion —
  // not a single final summary line.
  await expect(body.getByTestId("timeline-stage").first()).toBeVisible();
  await expect(body.getByTestId("timeline-completed")).toBeVisible();
});

test("material edit requires explicit replace-everything confirmation", async ({ page, request }) => {
  await ensureLoggedIn(page);
  const { sceneId, questionId } = await seedQuestion(page, request, "审改评测集F");

  await page.goto(`/evaluation-sets/${sceneId}/questions/${questionId}`);
  await page.getByRole("button", { name: "编辑材料" }).click();

  const prompt = page.getByRole("textbox", { name: "题目", exact: true });
  await prompt.fill("请把提供的素材整理成一段正式说明，并补充审核要点。");

  // Cancel first: no write request, no generation, draft dialog just closes.
  await page.getByRole("button", { name: "保存并重新生成" }).click();
  await expect(page.getByTestId("regen-confirm-text")).toBeVisible();
  const cookie = await cookieHeader(page);
  const before = await (
    await request.get(`/api/questions/${questionId}`, { headers: { Cookie: cookie } })
  ).json();
  await page.getByRole("dialog", { name: "重新生成将整套替换" }).getByRole("button", { name: "取消" }).click();
  const afterCancel = await (
    await request.get(`/api/questions/${questionId}`, { headers: { Cookie: cookie } })
  ).json();
  expect(afterCancel.content_revision).toBe(before.content_revision);
  expect(afterCancel.status).toBe("pending_review");

  // Confirm: exactly one regeneration is started.
  await page.getByRole("button", { name: "保存并重新生成" }).click();
  await page.getByTestId("regen-confirm").click();
  await expect
    .poll(
      async () => {
        const r = await request.get(`/api/questions/${questionId}`, { headers: { Cookie: cookie } });
        return r.status() === 200 ? (await r.json()).status : "unknown";
      },
      { timeout: 30_000 },
    )
    .toBe("pending_review");
  const after = await (
    await request.get(`/api/questions/${questionId}`, { headers: { Cookie: cookie } })
  ).json();
  expect(after.content_revision).toBe(before.content_revision + 1);
  expect(after.criteria_confirmed).toBe(false);
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

  // Delete now requires typing the full title; navigation happens only after
  // the durable cleanup finished (authoritative 404), not on acceptance.
  await page.getByRole("button", { name: "删除题目" }).click();
  await page.getByLabel("题目标题").fill("工作台测试用例");
  await page.getByTestId("delete-confirm").click();
  await expect(page).toHaveURL(/\/evaluation-sets\/[^/]+$/, { timeout: 20_000 });

  // The question and its run history are really gone from the API.
  const cookie = await cookieHeader(page);
  const gone = await request.get(`/api/questions/${questionId}`, { headers: { Cookie: cookie } });
  expect(gone.status()).toBe(404);
});
