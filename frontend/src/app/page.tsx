"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { getBootstrap, getCurrentUser } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import styles from "./page.module.css";

/**
 * Entry router.
 *
 * Resolves the session and the anonymous bootstrap flag in parallel, then
 * sends the visitor to the right surface: the app with a valid session, the
 * first-run registration when no admin exists, or the login page otherwise.
 */
export default function RootPage(): React.JSX.Element {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function decide(): Promise<void> {
      try {
        const [meResult, bootstrapResult] = await Promise.allSettled([
          getCurrentUser(controller.signal),
          getBootstrap(controller.signal),
        ]);

        if (cancelled) return;

        // A valid session always wins, regardless of bootstrap state.
        if (meResult.status === "fulfilled") {
          router.replace("/evaluation-sets");
          return;
        }

        const registrationOpen =
          bootstrapResult.status === "fulfilled" &&
          bootstrapResult.value.registration_available;

        router.replace(registrationOpen ? "/register" : "/login");
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    void decide();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [router]);

  return (
    <div className={styles.deciding} aria-busy="true">
      <div className={styles.card}>
        <Skeleton width={120} height={20} />
        <Skeleton width="100%" height={14} />
        <Skeleton width="70%" height={14} />
        {failed ? <p className={styles.error}>无法连接服务，请刷新重试。</p> : null}
      </div>
    </div>
  );
}
