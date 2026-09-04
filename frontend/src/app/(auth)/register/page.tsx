"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ErrorPanel } from "@/components/ui/error-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { TextField } from "@/components/ui/text-field";
import { useSession } from "@/features/auth/session-context";
import { getBootstrap, registerAdmin } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import styles from "@/features/auth/auth-form.module.css";

export default function RegisterPage(): React.JSX.Element {
  const router = useRouter();
  const { refresh } = useSession();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Field-level error so the mismatch is programmatically associated with the
  // confirm-password input, not only announced at the form level.
  const [confirmError, setConfirmError] = useState<string | null>(null);

  // Gate the page on the real bootstrap state; an existing admin means this
  // surface is closed and the visitor goes to login.
  useEffect(() => {
    const controller = new AbortController();
    getBootstrap(controller.signal)
      .then((result) => {
        setAllowed(result.registration_available);
        if (!result.registration_available) router.replace("/login");
      })
      .catch(() => router.replace("/login"))
      .finally(() => setChecking(false));
    return () => controller.abort();
  }, [router]);

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    if (password !== confirm) {
      setError(null);
      setConfirmError("两次输入的密码不一致。");
      return;
    }

    setSubmitting(true);
    setError(null);
    setConfirmError(null);
    try {
      await registerAdmin({ username, email: email || null, password });
      // Establish the shared session state before entering the protected app.
      await refresh();
      router.replace("/evaluation-sets");
    } catch (err) {
      if (err instanceof ApiError && err.code === "ADMIN_EXISTS") {
        // Someone created the admin first; close this surface and go to login.
        router.replace("/login");
        return;
      }
      setError(err instanceof ApiError ? err.message : "创建失败，请稍后重试。");
      setSubmitting(false);
    }
  }

  if (checking) {
    return (
      <section className={[styles.panel, styles.panelFlow].join(" ")}>
        <div className={styles.form} aria-busy="true">
          <Skeleton width={160} height={24} />
          <Skeleton width="100%" height={40} />
          <Skeleton width="100%" height={40} />
          <Skeleton width="100%" height={40} />
        </div>
      </section>
    );
  }

  if (!allowed) {
    return (
      <section className={[styles.panel, styles.panelFlow].join(" ")}>
        <div className={styles.form}>
          <Skeleton width="100%" height={40} />
        </div>
      </section>
    );
  }

  return (
    <section className={[styles.panel, styles.panelFlow].join(" ")} aria-labelledby="register-title">
      <h1 className={styles.title} id="register-title">
        创建管理员
      </h1>
      <p className={styles.subtitle}>平台还没有管理员。创建后将作为唯一管理员使用。</p>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        {error ? <ErrorPanel title="创建未成功" message={error} /> : null}

        <TextField
          label="用户名"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          disabled={submitting}
          hint="2–50 个字符"
        />
        <TextField
          label="邮箱（可选）"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={submitting}
        />
        <TextField
          label="密码"
          name="new-password"
          type="password"
          revealable
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={submitting}
          hint="8–128 个字符"
        />
        <TextField
          label="确认密码"
          name="confirm-password"
          type="password"
          revealable
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value);
            if (confirmError) setConfirmError(null);
          }}
          error={confirmError}
          required
          disabled={submitting}
        />

        <Button type="submit" loading={submitting} className={styles.submit}>
          创建管理员
        </Button>

        <div className={styles.footnote}>
          <p className={styles.signup}>
            已有管理员？ <Link href="/login">去登录</Link>
          </p>
        </div>
      </form>
    </section>
  );
}
