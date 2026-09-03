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
1. 先定位 ai-eval-push 的真实安装位置或项目内调用路径，不要臆测。
2. 使用下面的服务地址与长期凭证为该评测集建立配置：
   - API 地址：${agentApiBaseUrl}
   - 评测集 ID：${sceneId}
   - 上传凭证：${token}
3. 凭证属于敏感信息：不要在任何回复、日志、提交记录或仓库文件中回显或提交它。
4. 把配置写入仓库之外的私有位置（例如用户主目录下的私有配置文件），并设置当前宿主可持续读取的 AI_EVAL_CONFIG 指向该配置。
5. 运行一次 connection 检查确认连通。
6. 完成后只报告非敏感结果：连接状态、评测集名称与 ID、以及配置文件的存放位置。不要输出凭证本身。`;
}

/** Default external API base URL for prompts (no secret involved). */
export function resolveAgentApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://127.0.0.1:8000";
}
