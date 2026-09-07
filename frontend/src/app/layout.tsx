import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SessionProvider } from "@/features/auth/session-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "蓝标汽车事业 BenchMark 平台",
  description: "本地单管理员评测题管理台",
};

export default function RootLayout({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <html lang="zh-CN">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
