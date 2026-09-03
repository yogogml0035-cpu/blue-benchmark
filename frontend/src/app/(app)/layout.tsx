"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/features/auth/session-context";
import { buildAuthUrl } from "@/lib/redirect";
import styles from "./layout.module.css";

/**
 * Protected application layout.
 *
 * Shows a stable skeleton while the session is being restored. An anonymous
 * visitor is sent to the login route with a safe return position; a valid
 * session renders the AppShell around the page content.
 */
export default function AppLayout({ children }: { children: ReactNode }): React.JSX.Element {
  const { status, user, logout, loggingOut } = useSession();
  const router = useRouter();

  useEffect(() => {
    // A logout in flight already navigates to /login; only an unexpected
    // anonymous state (expired session, direct visit) needs the redirect.
    if (status === "anonymous" && !loggingOut) {
      const returnTo = typeof window !== "undefined" ? window.location.pathname : null;
      router.replace(buildAuthUrl("/login", returnTo));
    }
  }, [status, loggingOut, router]);

  if (status === "loading") {
    return (
      <div className={styles.loading} aria-busy="true">
        <div className={styles.loadingSidebar}>
          <Skeleton width="60%" height={24} />
          <Skeleton width="100%" height={40} />
          <Skeleton width="100%" height={40} />
        </div>
        <div className={styles.loadingContent}>
          <Skeleton width="40%" height={28} />
          <Skeleton variant="block" width="100%" height={220} />
        </div>
      </div>
    );
  }

  if (status === "anonymous" || !user) {
    // Momentarily render nothing while the redirect above takes effect.
    return <div className={styles.loading} aria-busy="true" />;
  }

  return (
    <AppShell username={user.username} onLogout={() => void logout()} loggingOut={loggingOut}>
      {children}
    </AppShell>
  );
}
