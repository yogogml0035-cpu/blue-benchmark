import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "评测集平台", template: "%s" },
  description:
    "把一次真实交付沉淀成一条白纸黑字的题：AI 只整理带出处的题稿，定稿权在业务老师。",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
