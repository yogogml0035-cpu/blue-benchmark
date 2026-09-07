/**
 * The single admin credential for E2E runs.
 *
 * global-setup.ts injects these exact values into the isolated backend as
 * ADMIN_USERNAME / ADMIN_PASSWORD; the API lifespan seeds the admin from them
 * on startup, so specs only ever log in — there is no registration surface.
 */
export const ADMIN = {
  username: "benchmark-admin",
  password: "benchmark-admin-password-1",
};
