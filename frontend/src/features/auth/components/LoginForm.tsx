"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/src/lib/api/client";
import { login, register } from "@/src/features/auth/services/authService";

export function LoginForm() {
  const router = useRouter();
  const [isRegistering, setIsRegistering] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function goToReturnPage() {
    const returnTo = new URLSearchParams(window.location.search).get("returnTo");
    router.replace(returnTo?.startsWith("/") ? returnTo : "/workspaces");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (isRegistering) {
        await register({ username, email: email || null, password });
      } else {
        await login({ identifier, password });
      }
      goToReturnPage();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "请求失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <section className="card auth-card stack">
        <div>
          <h1>{isRegistering ? "注册" : "登录"}</h1>
          <p className="muted">只用于本地 Walking Skeleton 验证。</p>
        </div>
        <form className="stack" onSubmit={submit}>
          {isRegistering ? (
            <>
              <label>用户名<input autoComplete="username" required minLength={2} maxLength={50} value={username} onChange={(event) => setUsername(event.target.value)} /></label>
              <label>邮箱（可选）<input autoComplete="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            </>
          ) : (
            <label>用户名或邮箱<input autoComplete="username" required value={identifier} onChange={(event) => setIdentifier(event.target.value)} /></label>
          )}
          <label>密码<input autoComplete={isRegistering ? "new-password" : "current-password"} required minLength={8} maxLength={128} type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error && <div className="error">{error}</div>}
          <button disabled={busy} type="submit">{busy ? "提交中…" : isRegistering ? "注册并进入" : "登录"}</button>
        </form>
        <button className="secondary" type="button" onClick={() => { setIsRegistering((value) => !value); setError(""); }}>
          {isRegistering ? "已有账号，去登录" : "没有账号，去注册"}
        </button>
      </section>
    </main>
  );
}
