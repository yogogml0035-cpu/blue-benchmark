"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getCurrentUser, logout as logoutRequest, type User } from "@/lib/api/auth";
import { setAuthFailureHandler } from "@/lib/api/client";
import { buildAuthUrl } from "@/lib/redirect";

export type SessionStatus = "loading" | "authenticated" | "anonymous";

export interface SessionContextValue {
  status: SessionStatus;
  user: User | null;
  /** Re-reads the current session from the backend. */
  refresh: () => Promise<void>;
  /** Signs out and returns to the login flow. */
  logout: () => Promise<void>;
  loggingOut: boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return value;
}

/**
 * Owns the client session lifecycle.
 *
 * On mount it resolves `/api/auth/me`. A 401 anywhere in the app triggers the
 * registered auth-failure handler exactly once, sending the user to the login
 * route with a safe return position — never in a redirect loop.
 */
export function SessionProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const router = useRouter();
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const redirected = useRef(false);
  // Monotonic sequence so a slow /auth/me response can never overwrite the
  // outcome of a newer refresh (e.g. a late 401 landing after a fresh login).
  const refreshSeq = useRef(0);

  const refresh = useCallback(async () => {
    const seq = ++refreshSeq.current;
    try {
      const response = await getCurrentUser();
      if (seq !== refreshSeq.current) return;
      setUser(response.user);
      setStatus("authenticated");
      // A live session re-arms the one-shot session-expired redirect and clears
      // any in-flight logout state; without this the second expiry in one SPA
      // lifetime would never redirect and the logout button would stay disabled.
      redirected.current = false;
      setLoggingOut(false);
    } catch {
      if (seq !== refreshSeq.current) return;
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setAuthFailureHandler(() => {
      if (redirected.current) return;
      redirected.current = true;
      setUser(null);
      setStatus("anonymous");
      const returnTo = typeof window !== "undefined" ? window.location.pathname : null;
      router.replace(buildAuthUrl("/login", returnTo));
    });
    return () => setAuthFailureHandler(null);
  }, [router]);

  const logout = useCallback(async () => {
    setLoggingOut(true);
    try {
      await logoutRequest();
    } catch {
      // Even if the revoke call fails, drop the local session and go to login.
    }
    // Re-arm the one-shot auth redirect for the next session.
    redirected.current = false;
    setUser(null);
    setStatus("anonymous");
    // Keep loggingOut=true through the navigation so the protected layout does
    // not race with its own anonymous redirect (which would append returnTo).
    router.replace("/login");
  }, [router]);

  const value = useMemo<SessionContextValue>(
    () => ({ status, user, refresh, logout, loggingOut }),
    [status, user, refresh, logout, loggingOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
