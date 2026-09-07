import { expect, test, type Page } from "@playwright/test";
import { ADMIN } from "./admin";

/**
 * Login / session flows. The single admin is seeded by the isolated backend
 * from ADMIN_USERNAME / ADMIN_PASSWORD (see global-setup.ts), so every spec
 * only ever logs in — there is no registration surface.
 */

test.describe.configure({ mode: "serial" });

async function login(page: Page): Promise<void> {
  await page.getByLabel("用户名").fill(ADMIN.username);
  await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "登 录" }).click();
}

test("the entry surface is login (no registration exists)", async ({ page }) => {
  await page.goto("/");
  // The entry router resolves the (absent) session and lands on login.
  await page.waitForURL(/\/login$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  // Negative regression: the old first-run entries are gone.
  await page.goto("/register");
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole("button", { name: "创建管理员" })).toHaveCount(0);
});

test("rejects invalid credentials with an inline error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(ADMIN.username);
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
