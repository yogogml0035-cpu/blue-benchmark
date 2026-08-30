import type { StudioProjection } from "@/src/features/workspaces/services/studioService";

export const PREVIEW_STUDIO_SUCCESS: StudioProjection = {
  workspace_id: "0f3a9c21-7c14-4e0a-9a0b-2f6b8d5a1e01",
  batch_id: "batch-1",
  batch_status: "ready_for_confirmation",
  files: [
    {
      id: "f-1",
      original_name: "客户A-Brief-2026.md",
      media_type: "text/markdown",
      size_bytes: 4096,
      sha256: "abc123sha256",
      parse_state: "parsed",
      role: "brief",
      required: true,
      ignored: false,
      visibility: "runtime",
    },
    {
      id: "f-2",
      original_name: "客户A-产品参数表.json",
      media_type: "application/json",
      size_bytes: 8192,
      sha256: "def456sha256",
      parse_state: "parsed",
      role: "runtime",
      required: true,
      ignored: false,
      visibility: "runtime",
    },
    {
      id: "f-3",
      original_name: "客户A-春季新品-终稿.md",
      media_type: "text/markdown",
      size_bytes: 6144,
      sha256: "ghi789sha256",
      parse_state: "parsed",
      role: "judge",
      required: true,
      ignored: false,
      visibility: "judge",
    },
  ],
  next_action: {
    kind: "confirm_file_roles",
    label: "确认资料用途",
  },
  active_operation: null,
  latest_receipt: {
    id: "receipt-1",
    status: "succeeded",
    message: "资料已解析完毕，共提取 3 个文件。",
    completed_at: "2026-08-30T10:00:00Z",
  },
  blocking_issues: [],
};

export const PREVIEW_STUDIO_PROCESSING: StudioProjection = {
  ...PREVIEW_STUDIO_SUCCESS,
  active_operation: {
    id: "op-1",
    kind: "batch_analysis",
    status: "running",
  },
};
