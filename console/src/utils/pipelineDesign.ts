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
  mdRelativePath?: string;
  flowMemoryRelativePath?: string;
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
    "如果当前会话已经绑定流程 Markdown 工作文件，请直接修改该 Markdown 文件，不要输出 JSON 草稿。",
    "如果当前会话尚未绑定 Markdown 工作文件，请先产出最小可用流程结构，并在进入编辑态后继续以 Markdown 为唯一事实来源。",
    "步骤信息至少要明确：id、name、kind；description 可按需补充。",
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
  mdRelativePath,
  flowMemoryRelativePath,
  steps,
}: BuildEditContextPromptParams): string {
  const safeDescription = (description || "").trim() || "-";
  const stepDigest = (steps || [])
    .slice(0, 8)
    .map((step, index) => {
      const id = (step.id || "").trim() || `step-${index + 1}`;
      const name = (step.name || "").trim() || "unnamed";
      const kind = (step.kind || "").trim() || "task";
      return `- ${id} (${kind}): ${name}`;
    });

  if ((steps || []).length > 8) {
    stepDigest.push(`- ... 其余 ${steps.length - 8} 个步骤省略`);
  }

  const guidance = [
    "继续在当前会话编辑流程。以下是当前流程的精简信息：",
    `pipeline_id: ${pipelineId}`,
    `pipeline_name: ${pipelineName}`,
    `version: ${version}`,
    `description: ${safeDescription}`,
    `scope: ${scope}`,
    `source: ${source}`,
    `agent_id: ${agentId || "unknown"}`,
    `steps_count: ${steps.length}`,
    "steps_digest:",
    stepDigest.length > 0 ? stepDigest.join("\n") : "- (empty)",
    "要求：当前是模板编辑模式，不要搜索真实文件或执行任务。",
    "后续如果你要落实流程改动，请优先直接修改流程 Markdown 工作文件，并以该文件作为唯一事实来源。",
  ];

  if (mdRelativePath && mdRelativePath.trim()) {
    guidance.push(
      `流程 Markdown 工作文件: ${mdRelativePath.trim()}。`,
      "请优先直接使用 write_file 或 edit_file 修改该 Markdown 文件，不必在对话中输出 JSON。",
      "文件格式约定：每个步骤使用 `## <步骤名称> [<步骤ID>] (<类型>)` 标题，标题下写该步骤描述。",
    );
  }

  if (flowMemoryRelativePath && flowMemoryRelativePath.trim()) {
    guidance.push(
      `流程临时记忆文件: ${flowMemoryRelativePath.trim()}。`,
      "请将当前流程的临时约束、未完成事项、决策备注写入该文件；此记忆仅对当前流程编辑有效。",
    );
  }

  return guidance.join("\n\n");
}

export function buildPipelineDesignChatPath(
  sessionId: string,
): string {
  return `/chat/${encodeURIComponent(sessionId)}`;
}
