"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ErrorPanel } from "@/components/ui/error-panel";
import { TextField } from "@/components/ui/text-field";
import { useSession } from "@/features/auth/session-context";
import { getBootstrap, login } from "@/lib/api/auth";
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
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registrationOpen, setRegistrationOpen] = useState<boolean | null>(null);

  // Show the first-run link only when registration is genuinely available.
  useEffect(() => {
    const controller = new AbortController();
    getBootstrap(controller.signal)
      .then((result) => setRegistrationOpen(result.registration_available))
      .catch(() => setRegistrationOpen(false));
    return () => controller.abort();
  }, []);

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
        // 409 ADMIN_EXISTS here means the registration entry raced; bounce to it.
        if (err.code === "ADMIN_EXISTS") {
          router.replace("/register");
          return;
        }
        setError(err.message);
      } else {
        setError("登录失败，请稍后重试。");
      }
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <h1 className={styles.title}>登录</h1>
      <p className={styles.subtitle}>使用管理员账号登录评测管理台。</p>

      {error ? <ErrorPanel title="登录未成功" message={error} /> : null}

      <TextField
        label="用户名或邮箱"
        name="identifier"
        autoComplete="username"
        value={identifier}
        onChange={(e) => setIdentifier(e.target.value)}
        required
        disabled={submitting}
      />
      <TextField
        label="密码"
        name="password"
        type="password"
        revealable
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        disabled={submitting}
      />

      <Button type="submit" loading={submitting} className={styles.submit}>
        登录
      </Button>

      <div className={styles.footnote}>
        {registrationOpen === true ? (
          <p className={styles.switch}>
            还没有管理员？<Link href="/register">创建首个管理员</Link>
          </p>
        ) : null}
      </div>
    </form>
  );
}

export default function LoginPage(): React.JSX.Element {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
