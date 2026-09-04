import { expect, test } from "@playwright/test";

/**
 * First-run registration flows. These require an empty database, so they run
 * only in the first project (chromium) before any admin exists.
 */

test.describe.configure({ mode: "serial" });

const ADMIN = {
  username: "benchmark-admin",
  email: "benchmark-admin@example.com",
  password: "benchmark-admin-password-1",
};

test("root redirects an anonymous visitor to registration on an empty platform", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole("heading", { name: "创建管理员" })).toBeVisible();
});

test("creates the first admin and lands in the app", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("用户名").fill(ADMIN.username);
  await page.getByLabel("邮箱（可选）").fill(ADMIN.email);
  await page.getByLabel("密码", { exact: true }).fill(ADMIN.password);
  await page.getByLabel("确认密码").fill(ADMIN.password);
  await page.getByRole("button", { name: "创建管理员" }).click();

  await expect(page).toHaveURL(/\/evaluation-sets$/);
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();

  // Sign out so the following login suite starts from a clean session.
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("registration closes once an admin exists", async ({ page }) => {
  await page.goto("/register");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
});
