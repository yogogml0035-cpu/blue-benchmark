import type { Workspace } from "@/src/features/workspaces/services/workspaceService";

/**
 * 状态预演用的场景，只用 OpenAPI 生成的 Workspace 类型构造，
 * 字段一旦和后端合同漂移就会在 typecheck 阶段报错。
 */
export const PREVIEW_WORKSPACES: Workspace[] = [
  {
    id: "0f3a9c21-7c14-4e0a-9a0b-2f6b8d5a1e01",
    name: "客户 A 新闻稿",
    description: "单一客户的新闻稿撰写与审核：Brief 合规、事实准确、品牌禁用项。",
    visibility: "private",
    owner_user_id: "9c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
    created_at: "2026-08-27T02:10:00Z",
    updated_at: "2026-08-27T02:10:00Z",
  },
  {
    id: "1b7e4d52-3f88-4b2c-8d19-6a4c7e2b9f02",
    name: "媒体名单与 RSVP 衍生表",
    description: "依据冻结原始数据核验人员、数量、航班、酒店，重点是重复与遗漏。",
    visibility: "private",
    owner_user_id: "9c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
    created_at: "2026-08-25T09:42:00Z",
    updated_at: "2026-08-25T09:42:00Z",
  },
  {
    id: "2c9f5e63-4a99-4c3d-9e2a-7b5d8f3c0a03",
    name: "客户 B 活动通稿",
    description: null,
    visibility: "private",
    owner_user_id: "9c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
    created_at: "2026-08-21T11:05:00Z",
    updated_at: "2026-08-21T11:05:00Z",
  },
];
