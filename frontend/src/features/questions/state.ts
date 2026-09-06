/**
 * Pure presentation helpers for question status and next action.
 */

import type { StatusTone } from "@/components/ui/status-badge";
import type { NextAction, QuestionStatus } from "./api";

export const STATUS_LABEL: Record<QuestionStatus, string> = {
  generating: "生成中",
  pending_review: "待审改",
  generation_failed: "生成失败",
  published: "已发布",
  deleting: "删除处理中",
};

export const STATUS_TONE: Record<QuestionStatus, StatusTone> = {
  generating: "info",
  pending_review: "warning",
  generation_failed: "danger",
  published: "success",
  deleting: "info",
};

export const NEXT_ACTION_LABEL: Record<NextAction, string> = {
  wait_for_generation: "等待生成",
  retry_generation: "重试生成",
  review_criteria: "选择维度",
  publish: "发布",
  published: "已发布",
  wait_for_deletion: "等待删除清理完成",
};
