"use client";

import { useCallback, useEffect, useState } from "react";

import { getCurrentUser, type User } from "@/src/features/auth/services/authService";
import { toPageFault, type PageFault } from "@/src/lib/api/pageFault";

export type Session =
  | { status: "loading" }
  | { status: "authenticated"; user: User }
  | { status: "anonymous"; fault: PageFault }
  | { status: "failed"; fault: PageFault };

/**
 * 受保护页面在 GET /api/auth/me 完成前只能显示加载态，不能先闪现私有内容，
 * 所以会话读取独立成一个钩子，由页面据此决定渲染骨架、未授权还是内容。
 */
export function useSession(): Session & { reload: () => void } {
  const [session, setSession] = useState<Session>({ status: "loading" });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setSession({ status: "loading" });
    getCurrentUser()
      .then((result) => {
        if (active) setSession({ status: "authenticated", user: result.user });
      })
      .catch((cause: unknown) => {
        if (!active) return;
        const fault = toPageFault(cause);
        setSession(
          fault.kind === "unauthorized"
            ? { status: "anonymous", fault }
            : { status: "failed", fault },
        );
      });
    return () => {
      active = false;
    };
  }, [nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { ...session, reload };
}
