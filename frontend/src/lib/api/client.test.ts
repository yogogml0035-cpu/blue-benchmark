import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, request, setAuthFailureHandler } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("request()", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    setAuthFailureHandler(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses a JSON success response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { registration_available: true }));
    const result = await request<{ registration_available: boolean }>("/api/auth/bootstrap");
    expect(result).toEqual({ registration_available: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/bootstrap",
      expect.objectContaining({ method: "GET", cache: "no-store", credentials: "same-origin" }),
    );
  });

  it("returns undefined for 204 responses", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const result = await request<void>("/api/auth/logout", { method: "POST" });
    expect(result).toBeUndefined();
  });

  it("serializes a JSON body and sets the content type", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await request("/api/auth/login", { method: "POST", body: { identifier: "a", password: "b" } });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(JSON.stringify({ identifier: "a", password: "b" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("throws an ApiError built from the backend error contract", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, { error: { code: "ADMIN_EXISTS", message: "已存在管理员。", details: null } }),
    );
    await expect(request("/api/auth/register", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 409,
      code: "ADMIN_EXISTS",
      message: "已存在管理员。",
    });
  });

  it("falls back to UNKNOWN when the error body is not the contract shape", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(500, { unexpected: true }));
    await expect(request("/api/scenes")).rejects.toMatchObject({ status: 500, code: "UNKNOWN" });
  });

  it("fires the auth handler exactly when a 401 occurs", async () => {
    const handler = vi.fn();
    setAuthFailureHandler(handler);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "AUTH_REQUIRED", message: "请先登录。", details: null } }),
    );
    await expect(request("/api/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not fire the auth handler for non-401 errors", async () => {
    const handler = vi.fn();
    setAuthFailureHandler(handler);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(404, { error: { code: "RESOURCE_NOT_FOUND", message: "不存在。", details: null } }),
    );
    await expect(request("/api/questions/nope")).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("maps network failures to a synthetic NETWORK error", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("failed to fetch"));
    await expect(request("/api/scenes")).rejects.toMatchObject({ status: 0, code: "NETWORK" });
  });

  it("does not fire the auth handler when authRedirect is opted out", async () => {
    const handler = vi.fn();
    setAuthFailureHandler(handler);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "INVALID_CREDENTIALS", message: "用户名或密码错误。", details: null } }),
    );
    await expect(
      request("/api/auth/login", { method: "POST", body: {}, authRedirect: false }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("rethrows AbortError without wrapping it", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValueOnce(abortError);
    await expect(request("/api/scenes")).rejects.toBe(abortError);
  });
});
