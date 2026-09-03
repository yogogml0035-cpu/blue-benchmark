import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Stub the Next router before importing the provider.
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

// Controllable /auth/me results.
const getCurrentUserMock = vi.fn();
vi.mock("@/lib/api/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/auth")>("@/lib/api/auth");
  return {
    ...actual,
    getCurrentUser: (...args: unknown[]) => getCurrentUserMock(...args),
    logout: vi.fn().mockResolvedValue(undefined),
  };
});

import { ApiError } from "@/lib/api/client";
import { SessionProvider, useSession } from "./session-context";

function Probe(): React.JSX.Element {
  const { status, refresh, user } = useSession();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.username ?? "none"}</span>
      <button type="button" onClick={() => void refresh()}>
        refresh
      </button>
    </div>
  );
}

const AUTH_USER = { user: { id: "u1", username: "aura-admin", email: null, created_at: "2026-01-01T00:00:00Z" } };

describe("SessionProvider", () => {
  beforeEach(() => {
    replace.mockClear();
    getCurrentUserMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("discards a stale 401 that lands after a newer successful refresh", async () => {
    // First call: a slow promise that eventually rejects with 401.
    let rejectLate: (err: unknown) => void = () => {};
    const late401 = new Promise((_resolve, reject) => {
      rejectLate = reject;
    });
    // Second call: resolves quickly with an authenticated user.
    getCurrentUserMock
      .mockReturnValueOnce(late401)
      .mockResolvedValueOnce(AUTH_USER);

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    // Trigger a second refresh (as a login page would after signing in).
    await act(async () => {
      screen.getByRole("button", { name: "refresh" }).click();
    });

    // The fast success settles first.
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    // Now the late 401 from the initial probe arrives; it must be ignored.
    await act(async () => {
      rejectLate(new ApiError(401, "AUTH_REQUIRED", "请先登录。"));
    });

    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("aura-admin");
  });

  it("becomes anonymous when the session probe returns 401", async () => {
    getCurrentUserMock.mockRejectedValueOnce(new ApiError(401, "AUTH_REQUIRED", "请先登录。"));
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
  });
});
