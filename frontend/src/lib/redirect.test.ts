import { describe, expect, it } from "vitest";
import { buildAuthUrl, isSafeReturnPath, resolvePostAuthPath, sanitizeReturnPath } from "./redirect";

describe("isSafeReturnPath", () => {
  it("accepts plain relative paths", () => {
    expect(isSafeReturnPath("/evaluation-sets")).toBe(true);
    expect(isSafeReturnPath("/evaluation-sets/abc/questions/def")).toBe(true);
    expect(isSafeReturnPath("/")).toBe(true);
  });

  it("rejects protocol-relative and absolute URLs", () => {
    expect(isSafeReturnPath("//evil.com")).toBe(false);
    expect(isSafeReturnPath("https://evil.com")).toBe(false);
    expect(isSafeReturnPath("http://evil.com/x")).toBe(false);
    expect(isSafeReturnPath("evil.com")).toBe(false);
  });

  it("rejects backslash and control-character tricks", () => {
    expect(isSafeReturnPath("/\\evil.com")).toBe(false);
    expect(isSafeReturnPath("/\u0000evil")).toBe(false);
    expect(isSafeReturnPath("/a\u001fb")).toBe(false);
  });

  it("rejects empty, null and non-string values", () => {
    expect(isSafeReturnPath("")).toBe(false);
    expect(isSafeReturnPath(null)).toBe(false);
    expect(isSafeReturnPath(undefined)).toBe(false);
  });
});

describe("resolvePostAuthPath", () => {
  it("honors a safe returnTo", () => {
    expect(resolvePostAuthPath("/evaluation-sets")).toBe("/evaluation-sets");
  });

  it("falls back to the app root for unsafe values", () => {
    expect(resolvePostAuthPath("//evil.com")).toBe("/evaluation-sets");
    expect(resolvePostAuthPath(null)).toBe("/evaluation-sets");
    expect(resolvePostAuthPath(undefined)).toBe("/evaluation-sets");
  });

  it("drops query strings and fragments from the return path", () => {
    expect(resolvePostAuthPath("/evaluation-sets?tab=1")).toBe("/evaluation-sets");
  });
});

describe("sanitizeReturnPath", () => {
  it("keeps only the pathname", () => {
    expect(sanitizeReturnPath("/a/b?c=1#d")).toBe("/a/b");
  });
});

describe("buildAuthUrl", () => {
  it("appends an encoded safe returnTo", () => {
    expect(buildAuthUrl("/login", "/evaluation-sets")).toBe(
      "/login?returnTo=%2Fevaluation-sets",
    );
  });

  it("omits returnTo when unsafe", () => {
    expect(buildAuthUrl("/login", "https://evil.com")).toBe("/login");
    expect(buildAuthUrl("/login", null)).toBe("/login");
  });
});
