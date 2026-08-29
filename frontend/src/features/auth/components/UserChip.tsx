import type { Session } from "@/src/features/auth/hooks/useSession";

/**
 * 当前账号。会话没读完之前不显示任何身份信息——受保护页面在 `GET /api/auth/me`
 * 返回前不能先闪现一个猜的用户名。这里用普通文字而不是胶囊标签：它是身份，
 * 不是状态，也不该被做成一个需要辨认的徽记。
 */
export function UserChip({ session, previewName }: { session: Session; previewName?: string }) {
  const username =
    session.status === "authenticated" ? session.user.username : (previewName ?? null);

  if (!username) {
    return (
      <span
        aria-busy="true"
        className="skeleton"
        style={{ width: 72, height: 14, borderRadius: 2 }}
      />
    );
  }

  return (
    <span
      style={{
        fontSize: "var(--t-14)",
        fontWeight: 550,
        color: "var(--text)",
        letterSpacing: "-0.005em",
        whiteSpace: "nowrap",
      }}
      title="当前登录账号"
    >
      {username}
    </span>
  );
}
