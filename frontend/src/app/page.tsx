import Link from "next/link";

export default function HomePage() {
  return (
    <main>
      <div className="card stack">
        <h1>Skill Eval Platform</h1>
        <p className="muted">Case Builder Walking Skeleton（FastAPI Stub）</p>
        <Link href="/login">进入登录</Link>
      </div>
    </main>
  );
}

