import { request } from "./client";
import type { components } from "./generated";

export type BootstrapResponse = components["schemas"]["BootstrapResponse"];
export type UserResponse = components["schemas"]["UserResponse"];
export type User = components["schemas"]["User"];
export type RegisterRequest = components["schemas"]["RegisterRequest"];
export type LoginRequest = components["schemas"]["LoginRequest"];

/** Anonymous first-run probe: is registration still open? */
export function getBootstrap(signal?: AbortSignal): Promise<BootstrapResponse> {
  return request<BootstrapResponse>("/api/auth/bootstrap", { signal });
}

/** Resolve the current session, or throw a 401 ApiError. */
export function getCurrentUser(signal?: AbortSignal): Promise<UserResponse> {
  // Probing the session must not itself trigger the session-expired redirect.
  return request<UserResponse>("/api/auth/me", { signal, authRedirect: false });
}

export function registerAdmin(
  payload: RegisterRequest,
  signal?: AbortSignal,
): Promise<UserResponse> {
  return request<UserResponse>("/api/auth/register", { method: "POST", body: payload, signal });
}

export function login(payload: LoginRequest, signal?: AbortSignal): Promise<UserResponse> {
  // A failed login is an inline form error, not a session-expired redirect.
  return request<UserResponse>("/api/auth/login", {
    method: "POST",
    body: payload,
    signal,
    authRedirect: false,
  });
}

export function logout(signal?: AbortSignal): Promise<void> {
  return request<void>("/api/auth/logout", { method: "POST", signal });
}
