"use client";

import { Eye, EyeOff, Lock, User } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { useSession } from "@/features/auth/session-context";
import { login } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { resolvePostAuthPath } from "@/lib/redirect";
import styles from "@/features/auth/auth-form.module.css";

function LoginForm(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refresh } = useSession();
  const returnTo = searchParams.get("returnTo");

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await login({ identifier, password });
      // Refresh the shared session state so the protected layout recognizes
      // the new session before we navigate into the app.
      await refresh();
      router.replace(resolvePostAuthPath(returnTo));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("登录失败，请稍后重试。");
      }
      setSubmitting(false);
    }
  }

  return (
    <section className={[styles.panel, styles.panelHero].join(" ")} aria-labelledby="login-title">
      <h1 className={styles.title} id="login-title">
        欢迎回来
      </h1>
      <p className={styles.subtitle}>登录以继续</p>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="login-identifier">
            用户名
          </label>
          <div className={styles.inputWrap}>
            <User className={styles.leadingIcon} size={20} strokeWidth={1.7} aria-hidden="true" />
            <input
              id="login-identifier"
              name="identifier"
              type="text"
              autoComplete="username"
              placeholder="输入您的用户名"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
              disabled={submitting}
            />
          </div>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="login-password">
            密码
          </label>
          <div className={styles.inputWrap}>
            <Lock className={styles.leadingIcon} size={20} strokeWidth={1.7} aria-hidden="true" />
            <input
              id="login-password"
              name="password"
              type={revealed ? "text" : "password"}
              autoComplete="current-password"
              placeholder="输入您的密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={submitting}
            />
            <button
              type="button"
              className={styles.passwordToggle}
              aria-label={revealed ? "隐藏密码" : "显示密码"}
              aria-pressed={revealed}
              onClick={() => setRevealed((value) => !value)}
            >
              {revealed ? (
                <EyeOff size={20} strokeWidth={1.7} aria-hidden="true" />
              ) : (
                <Eye size={20} strokeWidth={1.7} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        <Button type="submit" loading={submitting} className={styles.submit}>
          登 录
        </Button>

        <p
          className={[styles.message, error ? styles.messageError : null].filter(Boolean).join(" ")}
          role={error ? "alert" : "status"}
          aria-live="polite"
        >
          {error ?? ""}
        </p>
      </form>
    </section>
  );
}

export default function LoginPage(): React.JSX.Element {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
