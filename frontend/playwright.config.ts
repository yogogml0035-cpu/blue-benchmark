import { defineConfig, devices } from "@playwright/test";

/**
 * Browser acceptance for the desktop admin console.
 *
 * Chromium runs the full flows; WebKit covers the core authentication path.
 * `e2e/global-setup.ts` boots an isolated FastAPI (fresh SQLite, fake AI
 * mode) on a dedicated port, and the Next.js webServer proxies to it via
 * BACKEND_URL, so browser tests never touch the real development database.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
      // First-run registration needs the empty database; it runs only here,
      // before any other project touches the isolated backend.
      testMatch: ["01-auth-register.spec.ts", "02-auth-login.spec.ts", "03-evaluation-sets.spec.ts"],
    },
    {
      name: "chromium-minimum",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
      },
      testMatch: ["02-auth-login.spec.ts"],
    },
    {
      name: "webkit",
      use: {
        ...devices["Desktop Safari"],
        viewport: { width: 1440, height: 900 },
      },
      testMatch: ["02-auth-login.spec.ts"],
    },
  ],
  webServer: {
    // Build and serve the production bundle: it exercises the real output and
    // avoids the dev-server HMR WebSocket path entirely. BACKEND_URL is read
    // by next.config.mjs at build time, so the same value must be present for
    // both the build and the server.
    command: "pnpm build && pnpm start",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: false,
    timeout: 240_000,
    env: {
      BACKEND_URL: "http://127.0.0.1:8123",
      NEXT_PUBLIC_AGENT_API_BASE_URL: "http://127.0.0.1:8000",
    },
  },
});
