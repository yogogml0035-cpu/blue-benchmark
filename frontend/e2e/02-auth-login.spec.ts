import { expect, test, type Page } from "@playwright/test";

/**
 * Login / session flows. These assume an admin exists; the first test ensures
 * one is present so the suite is self-contained on any project (chromium runs
 * the registration spec first, webkit relies on this guarantee).
 */

test.describe.configure({ mode: "serial" });

const ADMIN = {
  username: "aura-admin",
  email: "aura-admin@example.com",
  password: "aura-admin-password-1",
};

async function ensureAdmin(page: Page): Promise<void> {
  await page.goto("/");
  // The entry router decides client-side; wait until it settles on either the
  // registration or the login surface before deciding whether to create one.
  await page.waitForURL(/\/(register|login)$/, { timeout: 15_000 });
  if (/\/register$/.test(page.url())) {
    await page.getByLabel("用户名").fill(ADMIN.username);
    await page.getByLabel("邮箱（可选）").fill(ADMIN.email);
    await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
    await page.getByLabel("确认密码").fill(ADMIN.password);
    await page.getByRole("button", { name: "创建管理员" }).click();
    await expect(page).toHaveURL(/\/evaluation-sets$/);
    await page.getByRole("button", { name: "退出登录" }).click();
    await expect(page).toHaveURL(/\/login$/);
  }
}

async function login(page: Page): Promise<void> {
  await page.getByLabel("用户名或邮箱").fill(ADMIN.username);
  await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "登录" }).click();
}

test("an admin exists so login is the entry surface", async ({ page }) => {
  await ensureAdmin(page);
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
});

test("rejects invalid credentials with an inline error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名或邮箱").fill(ADMIN.username);
  await page.getByLabel("密码", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "登录" }).click();

  // Scope to the inline error panel; Next also renders a route announcer with
  // role=alert, so filter by the panel's heading text.
  await expect(page.getByRole("alert").filter({ hasText: "登录未成功" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("logs in with username and password, then logs out", async ({ page }) => {
  await page.goto("/login");
  await login(page);
  await expect(page).toHaveURL(/\/evaluation-sets$/);

  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("logs in with the admin email as the identifier", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名或邮箱").fill(ADMIN.email);
  await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL(/\/evaluation-sets$/);
});

test("session persists across a full reload", async ({ page }) => {
  await page.goto("/login");
  await login(page);
  await expect(page).toHaveURL(/\/evaluation-sets$/);

  await page.reload();
  await expect(page).toHaveURL(/\/evaluation-sets$/);
});

test("a protected route bounces anonymous visitors to login with returnTo", async ({ page, context }) => {
  await context.clearCookies();
  await page.goto("/evaluation-sets");
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fevaluation-sets$/);

  await login(page);
  await expect(page).toHaveURL(/\/evaluation-sets$/);
});

test("an unsafe returnTo is never honored", async ({ page, context }) => {
  await context.clearCookies();
  await page.goto("/login?returnTo=%2F%2Fevil.example");
  await login(page);
  await expect(page).toHaveURL(/\/evaluation-sets$/);
});

test("login canvas paints a non-empty particle field", async ({ page }) => {
  await page.goto("/login");
  const canvas = page.locator("canvas[aria-hidden='true']");
  await expect(canvas).toBeVisible();

  const painted = await page.evaluate(() => {
    const el = document.querySelector("canvas");
    if (!el) return false;
    const ctx = el.getContext("2d");
    if (!ctx || el.width === 0 || el.height === 0) return false;
    const data = ctx.getImageData(0, 0, el.width, el.height).data;
    let nonZero = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] > 0 || data[i + 1] > 0 || data[i + 2] > 0) nonZero += 1;
    }
    return nonZero > 1000;
  });
  expect(painted).toBe(true);
});
