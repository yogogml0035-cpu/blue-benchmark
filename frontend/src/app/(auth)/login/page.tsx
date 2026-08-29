import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { AuthPanel } from "@/src/features/auth/components/AuthPanel";

export const metadata: Metadata = {
  title: "登录 · 评测集平台",
  description: "登录或注册后进入场景列表，把真实交付沉淀成标准案例。",
};

export default function LoginPage() {
  return (
    <Suspense fallback={<PageFallback width="page-narrow" />}>
      <AuthPanel />
    </Suspense>
  );
}
