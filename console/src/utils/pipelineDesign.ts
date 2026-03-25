export type PipelineDesignSource = "pipelines_page" | "chat_opportunity";

export type PipelineDesignScope = "independent" | "project";

interface BuildBindingKeyParams {
  pipelineId: string;
  version: string;
}

interface BuildPromptParams {
  agentId?: string;
  source: PipelineDesignSource;
  seedTask?: string;
}

interface BuildEditContextPromptParams {
  agentId?: string;
  source: PipelineDesignSource;
  scope: PipelineDesignScope;
  pipelineId: string;
  pipelineName: string;
  version: string;
  description?: string;
  steps: Array<{
    id: string;
    name: string;
    kind: string;
    description?: string;
  }>;
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

export function buildPipelineDesignBindingKey({
  pipelineId,
  version,
}: BuildBindingKeyParams): string {
  return `${pipelineId}@${version.trim() || "0"}`;
}

export function buildPipelineDesignEditContextPrompt({
  agentId,
  source,
  scope,
  pipelineId,
  pipelineName,
  version,
  description,
  steps,
}: BuildEditContextPromptParams): string {
  const safeDescription = (description || "").trim() || "-";
  const payload = {
    pipeline_id: pipelineId,
    pipeline_name: pipelineName,
    version,
    description: safeDescription,
    scope,
    source,
    agent_id: agentId || "unknown",
    steps,
  };

  return [
    "继续在当前会话编辑流程。请基于以下当前流程信息继续工作：",
    JSON.stringify(payload, null, 2),
    "要求：后续如果你给出流程改造结果，请严格返回 schema_version=1 且包含完整 steps 数组。",
  ].join("\n\n");
}

export function buildPipelineDesignChatPath(
  sessionId: string,
): string {
  return `/chat/${encodeURIComponent(sessionId)}`;
}
