export const PIPELINE_DESIGN_INTENT = "create-pipeline";

const BOOTSTRAP_KEY_PREFIX = "copaw.pipeline.bootstrap.";
const STARTED_KEY_PREFIX = "copaw.pipeline.autostart.done.";
const FORCE_NEW_CHAT_KEY = "copaw.pipeline.force_new_chat";

export type PipelineDesignSource = "pipelines_page" | "chat_opportunity";

interface BuildPromptParams {
  agentId?: string;
  source: PipelineDesignSource;
  seedTask?: string;
}

export function buildPipelineDesignBootstrapPrompt({
  agentId,
  source,
  seedTask,
}: BuildPromptParams): string {
  const lines = [
    "我想创建一个新的 Pipeline，请你作为 pipeline-create-guide 来引导我。",
    `来源: ${source}`,
    `当前智能体: ${agentId || "unknown"}`,
    "请先用 5-8 个问题收集关键信息：目标、输入数据、步骤、质量指标、失败重试、产出物。",
    "然后给出一个 Draft 方案（步骤列表 + 参数建议 + 质量门槛），并确认是否需要创建测试项目并首跑。",
  ];

  if (seedTask && seedTask.trim()) {
    lines.push(`参考任务描述: ${seedTask.trim()}`);
  }

  return lines.join("\n");
}

export function buildPipelineDesignChatPath(
  sessionId: string,
  source: PipelineDesignSource,
): string {
  const search = new URLSearchParams({
    intent: PIPELINE_DESIGN_INTENT,
    autostart: "1",
    newChat: "1",
    source,
  }).toString();
  return `/chat/${encodeURIComponent(sessionId)}?${search}`;
}

export function queuePipelineDesignBootstrap(
  sessionId: string,
  prompt: string,
): void {
  sessionStorage.setItem(`${BOOTSTRAP_KEY_PREFIX}${sessionId}`, prompt);
}

export function readPipelineDesignBootstrap(sessionId: string): string | null {
  const key = `${BOOTSTRAP_KEY_PREFIX}${sessionId}`;
  return sessionStorage.getItem(key);
}

export function clearPipelineDesignBootstrap(sessionId: string): void {
  sessionStorage.removeItem(`${BOOTSTRAP_KEY_PREFIX}${sessionId}`);
}

export function hasPipelineDesignAutostarted(sessionId: string): boolean {
  return sessionStorage.getItem(`${STARTED_KEY_PREFIX}${sessionId}`) === "1";
}

export function markPipelineDesignAutostarted(sessionId: string): void {
  sessionStorage.setItem(`${STARTED_KEY_PREFIX}${sessionId}`, "1");
}

export function hasPipelineForceNewChat(): boolean {
  return sessionStorage.getItem(FORCE_NEW_CHAT_KEY) === "1";
}

export function clearPipelineForceNewChat(): void {
  sessionStorage.removeItem(FORCE_NEW_CHAT_KEY);
}
