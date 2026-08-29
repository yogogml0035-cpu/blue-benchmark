import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "审校台 · Skill Eval Platform", template: "%s" },
  description:
    "把一份真实业务案例校订成一条可复核的候选用例：AI 只提供带出处的草案，标准由业务老师确认。",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
