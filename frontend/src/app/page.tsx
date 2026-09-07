"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { getCurrentUser } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import styles from "./page.module.css";

/**
 * Entry router.
 *
 * Resolves the session, then sends the visitor to the app with a valid
 * session or to the login page otherwise. The single admin account comes
 * from the backend environment; there is no registration surface.
 */
export default function RootPage(): React.JSX.Element {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function decide(): Promise<void> {
      try {
        await getCurrentUser(controller.signal);
        if (!cancelled) router.replace("/evaluation-sets");
      } catch (err) {
        if (cancelled) return;
        // A 401 from the session probe simply means "not logged in".
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        } else {
          setFailed(true);
        }
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
