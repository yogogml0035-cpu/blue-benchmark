import { expect, test, type Page } from "@playwright/test";

/**
 * Login / session flows. These assume an admin exists; the first test ensures
 * one is present so the suite is self-contained on any project (chromium runs
 * the registration spec first, webkit relies on this guarantee).
 */

test.describe.configure({ mode: "serial" });

const ADMIN = {
  username: "benchmark-admin",
  email: "benchmark-admin@example.com",
  password: "benchmark-admin-password-1",
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
  await page.getByLabel("邮箱地址").fill(ADMIN.username);
  await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "登 录" }).click();
}

test("an admin exists so login is the entry surface", async ({ page }) => {
  await ensureAdmin(page);
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
});

test("rejects invalid credentials with an inline error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("邮箱地址").fill(ADMIN.username);
  await page.getByLabel("密码", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "登 录" }).click();

  // Scope to the form's status line; Next also renders a route announcer with
  // role=alert, so filter by the backend error text.
  await expect(page.getByRole("alert").filter({ hasText: "用户名或密码错误" })).toBeVisible();
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
  await page.getByLabel("邮箱地址").fill(ADMIN.email);
  await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "登 录" }).click();
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

test("login surface renders the live particle backdrop", async ({ page }) => {
  await page.goto("/login");

  // The artwork is painted by a decorative full-surface canvas stacked under
  // the panel; assert it is present, hidden from accessibility, and actually
  // painted (not a blank bitmap) once the client mounts.
  const canvas = page.locator("main").locator("..").locator("canvas[aria-hidden='true']");
  await expect(canvas).toBeVisible();

  await expect
    .poll(async () =>
      page.evaluate(() => {
        const el = document.querySelector("main")?.parentElement?.querySelector("canvas");
        if (!(el instanceof HTMLCanvasElement)) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        // Sample a quarter in from the top-left: the artwork's navy gradient
        // with dust; a blank bitmap is pure black.
        const data = el.getContext("2d")?.getImageData(Math.round(rect.width / 4), Math.round(rect.height / 4), 1, 1).data;
        return data ? data[0] > 8 || data[1] > 8 || data[2] > 8 : false;
      }),
    )
    .toBe(true);
});
