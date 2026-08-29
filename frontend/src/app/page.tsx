import { redirect } from "next/navigation";

/** 本闭环没有首页大盘；根路径直接进场景列表，未登录时由该页跳登录。 */
export default function RootPage() {
  redirect("/workspaces");
}
