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
    "我想创建一个新的 Pipeline，请你作为 pipeline-create-guide 在模板设计模式下工作。",
    `来源: ${source}`,
    `当前智能体: ${agentId || "unknown"}`,
    "重要：这是模板设计，不是任务执行。不要搜索真实文件、不要扫描目录、不要要求立即运行。",
    "请先收集并回填 4 项上下文：流程用途、输入来源、期望产物、步骤线索。若用户已提供则不要重复追问。",
    "收到 4 项后直接返回一个完整 Pipeline JSON 草稿（不要 markdown 代码块）。",
    "JSON 必须包含字段：schema_version=1、id、name、version、description、steps。",
    "steps 中每个节点至少包含：id、name、kind；可选 description。",
    "如果信息仍有缺口，使用合理占位值并在 description 标注 assumptions，不要进入多轮发问。",
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
    "要求：当前是模板编辑模式，不要搜索真实文件或执行任务。",
    "后续如果你给出流程改造结果，请只返回一个 JSON 对象，且严格 schema_version=1 并包含完整 steps 数组。",
  ].join("\n\n");
}

export function buildPipelineDesignChatPath(
  sessionId: string,
): string {
  return `/chat/${encodeURIComponent(sessionId)}`;
}
