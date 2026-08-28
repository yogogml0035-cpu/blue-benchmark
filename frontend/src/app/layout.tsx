import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Skill Eval Platform",
  description: "Case Builder walking skeleton",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
