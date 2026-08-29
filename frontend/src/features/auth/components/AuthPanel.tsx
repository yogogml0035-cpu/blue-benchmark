"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { ArrowRight, SealMark } from "@/src/components/ui/Glyph";
import { Note } from "@/src/components/ui/Note";
import { Segmented } from "@/src/components/ui/Segmented";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { login, logout, register } from "@/src/features/auth/services/authService";
import { toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

type Mode = "login" | "register";

const MODES = [
  { value: "login" as const, label: "登录" },
  { value: "register" as const, label: "注册" },
];

/** 追问阶段之前的整条链路，放在登录纸下沿，让老师知道自己将要进入哪一条流程。 */
const FLOW = ["卷宗", "收件", "起草", "追问", "校订", "落章"];

function fieldOf(fault: PageFault | null): "username" | "email" | null {
  if (fault?.code === "USERNAME_TAKEN") return "username";
  if (fault?.code === "EMAIL_TAKEN") return "email";
  return null;
}

export function AuthPanel() {
  const router = useRouter();
  const params = useSearchParams();
  const preview = usePreviewState();
  const session = useSession();

  const [mode, setMode] = useState<Mode>("login");
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [fault, setFault] = useState<PageFault | null>(null);

  const rawReturnTo = params.get("returnTo");
  const returnTo = rawReturnTo?.startsWith("/") ? rawReturnTo : null;

  // 状态预演：把页面钉在某一个状态上，便于逐项验收。
  const forcedLoading = preview === "loading";
  const forcedSuccess = preview === "success";
  const forcedError = preview === "error";
  const forcedUnauthorized = preview === "unauthorized";
  const pristine = preview === "empty";

  const shownFault: PageFault | null = forcedError
    ? { kind: "unauthorized", code: "INVALID_CREDENTIALS", message: "用户名或密码错误。" }
    : fault;
  const invalidField = fieldOf(shownFault);
  const credentialsRejected = shownFault?.code === "INVALID_CREDENTIALS";

  const alreadySignedIn = forcedSuccess || (!preview && session.status === "authenticated");
  const checking = forcedLoading || (!preview && session.status === "loading");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFault(null);
    try {
      if (mode === "register") {
        await register({ username: username.trim(), email: email.trim() || null, password });
      } else {
        await login({ identifier: identifier.trim(), password });
      }
      router.replace(returnTo ?? "/workspaces");
    } catch (cause) {
      setFault(toPageFault(cause));
      setBusy(false);
    }
  }

  async function switchAccount() {
    setBusy(true);
    await logout().catch(() => undefined);
    session.reload();
    setBusy(false);
  }

  return (
    <>
      <PreviewBar states={["loading", "empty", "success", "error", "unauthorized"]} />
      <main className="page page-narrow stack-lg">
        <div className="stack-sm" style={{ justifyItems: "start" }}>
          <span className="row" style={{ gap: "var(--s-2)", color: "var(--seal)" }}>
            <SealMark size={20} />
            <span style={{ color: "var(--ink)", fontWeight: 600, fontSize: "var(--t-16)" }}>
              审校台
            </span>
          </span>
          <p className="secondary">
            把一份真实案例校订成一条可复核的候选用例。标准由你确认，AI 只提供带出处的草案。
          </p>
        </div>

        {(forcedUnauthorized || returnTo) && (
          <Note code="AUTH_REQUIRED" title="需要登录才能打开这份卷宗" tone="gap">
            登录后会回到{" "}
            <span className="mono">{returnTo ?? "/workspaces/…/cases/…"}</span>。
          </Note>
        )}

        {checking ? (
          <section className="sheet sheet-pad stack" aria-busy="true">
            <SkeletonLine height={18} width="120px" />
            <SkeletonLine height={38} />
            <SkeletonLine height={38} />
            <SkeletonLine height={40} />
            <span className="mono faint">正在读取当前会话…</span>
          </section>
        ) : alreadySignedIn ? (
          <section className="sheet enter" style={{ borderTop: "2px solid var(--prov-cleared)" }}>
            <div className="sheet-pad stack">
              <div className="stack-sm">
                <span className="state state-cleared">
                  <span className="dot" />
                  已登录
                </span>
                <h1 className="doc-title-sm">
                  当前账号：
                  {session.status === "authenticated" ? session.user.username : "teacher-a"}
                </h1>
                <p className="secondary">
                  这个会话已经通过认证。直接进入卷宗架，或换一个账号验证越权分支。
                </p>
              </div>
              <div className="row">
                <Button
                  onClick={() => router.replace(returnTo ?? "/workspaces")}
                  size="lg"
                  variant="primary"
                >
                  进入卷宗架
                  <ArrowRight />
                </Button>
                <Button busy={busy} busyLabel="正在退出…" onClick={switchAccount} size="lg">
                  换个账号
                </Button>
              </div>
            </div>
          </section>
        ) : (
          <section className="sheet enter">
            <div className="sheet-head spread">
              <h1 className="doc-title-sm">{mode === "login" ? "登录" : "建立账号"}</h1>
              <Segmented
                disabled={busy}
                label="登录或注册"
                onChange={(next) => {
                  setMode(next);
                  setFault(null);
                }}
                options={MODES}
                value={mode}
              />
            </div>

            <form className="sheet-pad stack" onSubmit={submit}>
              {mode === "register" ? (
                <>
                  <Field
                    error={invalidField === "username" ? shownFault?.message : undefined}
                    hint="2–50 字"
                    htmlFor="username"
                    label="用户名"
                  >
                    <input
                      autoComplete="username"
                      className={`control${invalidField === "username" ? " control-invalid" : ""}`}
                      disabled={busy}
                      id="username"
                      maxLength={50}
                      minLength={2}
                      onChange={(event) => setUsername(event.target.value)}
                      placeholder="teacher-a"
                      required
                      value={username}
                    />
                  </Field>
                  <Field
                    error={invalidField === "email" ? shownFault?.message : undefined}
                    hint="可留空"
                    htmlFor="email"
                    label="邮箱"
                  >
                    <input
                      autoComplete="email"
                      className={`control${invalidField === "email" ? " control-invalid" : ""}`}
                      disabled={busy}
                      id="email"
                      onChange={(event) => setEmail(event.target.value)}
                      placeholder="teacher@example.com"
                      type="email"
                      value={email}
                    />
                  </Field>
                </>
              ) : (
                <Field htmlFor="identifier" label="用户名或邮箱">
                  <input
                    autoComplete="username"
                    className={`control${credentialsRejected ? " control-invalid" : ""}`}
                    disabled={busy}
                    id="identifier"
                    onChange={(event) => setIdentifier(event.target.value)}
                    placeholder="teacher-a"
                    required
                    value={identifier}
                  />
                </Field>
              )}

              <Field hint="8–128 字符" htmlFor="password" label="密码">
                <input
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  className={`control${credentialsRejected ? " control-invalid" : ""}`}
                  disabled={busy}
                  id="password"
                  maxLength={128}
                  minLength={8}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  type="password"
                  value={password}
                />
              </Field>

              {shownFault && (
                <Note
                  code={shownFault.code}
                  title={credentialsRejected ? "这一组凭证没有通过" : "提交没有被接受"}
                  tone="fail"
                >
                  {shownFault.message}
                  {credentialsRejected && " 用户不存在与密码错误共用同一条提示，不暴露账号是否存在。"}
                </Note>
              )}

              {pristine && !shownFault && (
                <Note tone="info" title="表单还是空的">
                  本地 Stub 不预置账号，第一次使用请切到「注册」建立一个。
                </Note>
              )}

              <Button
                block
                busy={busy}
                busyLabel={mode === "register" ? "正在建立账号…" : "正在登录…"}
                size="lg"
                type="submit"
                variant="primary"
              >
                {mode === "register" ? "注册并进入卷宗架" : "登录"}
              </Button>
            </form>

            <div className="sheet-foot">
              <div className="row mono faint" style={{ gap: "var(--s-2)" }}>
                {FLOW.map((step, index) => (
                  <span key={step} style={index === 0 ? { color: "var(--ink-secondary)" } : undefined}>
                    {index > 0 && <span style={{ paddingRight: "var(--s-2)" }}>·</span>}
                    {step}
                  </span>
                ))}
              </div>
            </div>
          </section>
        )}

        {!preview && session.status === "failed" && (
          <Note code={session.fault.code} title="无法确认当前会话" tone="fail">
            {session.fault.message}
          </Note>
        )}
      </main>
    </>
  );
}
