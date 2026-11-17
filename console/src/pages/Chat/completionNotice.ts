import {
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
  type IAgentScopeRuntimeMessage,
  type IAgentScopeRuntimeResponse,
} from "@agentscope-ai/chat";

export type CompletionResponse = IAgentScopeRuntimeResponse & {
  metadata?: unknown;
  output: Array<IAgentScopeRuntimeMessage & { metadata?: unknown }>;
};

function completionMetadata(metadata: unknown): Record<string, unknown> | null {
  if (!metadata || typeof metadata !== "object") return null;
  const record = metadata as Record<string, unknown>;
  const source =
    record.metadata && typeof record.metadata === "object"
      ? (record.metadata as Record<string, unknown>)
      : record;
  const completion = source.qwenpaw_model_completion;
  return completion && typeof completion === "object"
    ? (completion as Record<string, unknown>)
    : null;
}

/** Live responses carry top-level metadata; history carries message metadata. */
export function hasTruncatedModelOutput(response: CompletionResponse): boolean {
  if (response.status !== AgentScopeRuntimeRunStatus.Completed) return false;
  const live = completionMetadata(response.metadata);
  if (live) return live.truncated === true;
  const lastAnswer = [...response.output]
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        message.type === AgentScopeRuntimeMessageType.MESSAGE,
    );
  return completionMetadata(lastAnswer?.metadata)?.truncated === true;
}
