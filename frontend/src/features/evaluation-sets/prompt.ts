/**
 * One-time Agent binding prompt.
 *
 * Built only at issue/rotate time from the one-time plaintext response. The
 * token appears exactly once in the template. The prompt is never persisted —
 * it lives only in the dialog's transient state and the user's clipboard.
 */

export interface AgentBindingPromptInput {
  /** Base URL of the FastAPI external endpoints (no secret). */
  agentApiBaseUrl: string;
  sceneId: string;
  sceneName: string;
  /** One-time plaintext credential token. */
  token: string;
}

/**
 * Neutralize newlines and control characters in user-supplied text before it
 * is embedded in the Agent prompt, so a scene name cannot break out of its
 * line and inject extra instructions to the receiving Agent.
 */
function sanitizePromptText(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
}

export function buildAgentBindingPrompt(input: AgentBindingPromptInput): string {
  const { agentApiBaseUrl, sceneId, token } = input;
  const sceneName = sanitizePromptText(input.sceneName);
  return `请把本机上传 Skill（ai-eval-push）绑定到评测集「${sceneName}」。

要求：
1. 先定位 ai-eval-push 的部署副本（例如 ~/.agents/skills/ai-eval-push），不要臆测。
2. 在该部署副本的 scripts/push_eval_cases.py 顶部，把两个占位符常量替换为真实值：
   - BASE_URL 设为「${agentApiBaseUrl}」（评测集 ID：${sceneId}）
   - ACCESS_TOKEN 设为「${token}」
3. 凭证属于敏感信息：不要在任何回复或日志中回显；绑定后的脚本绝不能提交进任何仓库——仓库中的脚本保持占位符，只绑定部署副本。
4. 运行一次 connection 检查确认连通。
5. 完成后只报告非敏感结果：连接状态、评测集名称与 ID。不要输出凭证本身。`;
}

/** Default external API base URL for prompts (no secret involved). */
export function resolveAgentApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://127.0.0.1:8000";
}
