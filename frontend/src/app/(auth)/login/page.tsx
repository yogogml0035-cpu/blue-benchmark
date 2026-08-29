import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { AuthPanel } from "@/src/features/auth/components/AuthPanel";

export const metadata: Metadata = {
  title: "登录 · 审校台",
  description: "登录或注册后进入卷宗架，把真实案例校订成候选用例。",
};

export default function LoginPage() {
  return (
    <Suspense fallback={<PageFallback width="page-narrow" />}>
      <AuthPanel />
    </Suspense>
  );
}
