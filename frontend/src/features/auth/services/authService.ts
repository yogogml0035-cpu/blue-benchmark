import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

type RegisterRequest = components["schemas"]["RegisterRequest"];
type LoginRequest = components["schemas"]["LoginRequest"];
export type User = components["schemas"]["User"];

export function register(input: RegisterRequest) {
  return apiFetch<{ user: User }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function login(input: LoginRequest) {
  return apiFetch<{ user: User }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getCurrentUser() {
  return apiFetch<{ user: User }>("/api/auth/me");
}

export function logout() {
  return apiFetch<void>("/api/auth/logout", { method: "POST" });
}

