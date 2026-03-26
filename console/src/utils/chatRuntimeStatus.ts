import type {
  ActiveModelsInfo,
  AgentsRunningConfig,
  ChatHistory,
  ChatRuntimeStatus,
  Message,
  ProviderInfo,
} from "../api/types";

export type RuntimeStatusBreakdownItem = ChatRuntimeStatus["breakdown"][number];

export type RuntimeStatusSnapshot = ChatRuntimeStatus;

type RuntimeStatusInput = {
  providers?: ProviderInfo[];
  activeModels?: ActiveModelsInfo | null;
  runningConfig?: AgentsRunningConfig | null;
  chatHistory?: ChatHistory | null;
};

type RuntimeStatusMergeGuard = {
  expectedAgentId?: string | null;
  expectedChatId?: string | null;
  expectedSnapshotStage?: string;
};

const DEFAULT_TOKEN_DIVISOR = 3.75;
const DEFAULT_CONTEXT_WINDOW = 32768;

function getActiveProvider(
  providers: ProviderInfo[] | undefined,
  activeModels: ActiveModelsInfo | null | undefined,
): ProviderInfo | undefined {
  const providerId = activeModels?.active_llm?.provider_id;
  return providers?.find((item) => item.id === providerId);
}

function getNumberRecordValue(
  record: Record<string, unknown> | undefined,
  keys: string[],
): number | undefined {
  for (const key of keys) {
    const raw = record?.[key];
    if (typeof raw === "number" && Number.isFinite(raw)) {
      return raw;
    }
    if (typeof raw === "string") {
      const parsed = Number(raw);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return undefined;
}

function estimateTokensFromString(text: string, divisor: number): number {
  if (!text) return 0;
  return Math.max(1, Math.round(new TextEncoder().encode(text).length / divisor));
}

function estimateTokensFromUnknown(value: unknown, divisor: number): number {
  if (typeof value === "string") {
    return estimateTokensFromString(value, divisor);
  }
  if (Array.isArray(value)) {
    return value.reduce((total, item) => total + estimateTokensFromUnknown(item, divisor), 0);
  }
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).reduce<number>(
      (total, item) => total + estimateTokensFromUnknown(item, divisor),
      0,
    );
  }
  return 0;
}

function messageContainsFilePayload(message: Message): boolean {
  const lower = JSON.stringify(message.content || "").toLowerCase();
  return /(file|image|video|audio|attachment|upload|console\/files)/.test(lower);
}

function messageContainsToolPayload(message: Message): boolean {
  if (String(message.role || "").toLowerCase() === "tool") {
    return true;
  }
  const lower = JSON.stringify(message.content || "").toLowerCase();
  return /tool_result|tool_use|tool call|tool_call|function_call/.test(lower);
}

function estimateChatHistoryBuckets(
  history: ChatHistory | null | undefined,
  divisor: number,
): { messages: number; toolResults: number; files: number } {
  const result = { messages: 0, toolResults: 0, files: 0 };
  for (const message of history?.messages || []) {
    const estimate = estimateTokensFromUnknown(message.content, divisor);
    if (messageContainsToolPayload(message)) {
      result.toolResults += estimate;
      continue;
    }
    if (messageContainsFilePayload(message)) {
      result.files += Math.max(estimate, 64);
      continue;
    }
    result.messages += estimate;
  }
  return result;
}

function inferContextWindowTokens(
  provider: ProviderInfo | undefined,
  runningConfig: AgentsRunningConfig | null | undefined,
  reservedResponseTokens: number,
): number {
  const generateKwargs = (provider?.generate_kwargs || {}) as Record<string, unknown>;
  const configured = getNumberRecordValue(generateKwargs, [
    "context_length",
    "context_window",
    "max_context_tokens",
    "num_ctx",
    "n_ctx",
    "ctx_len",
  ]);
  if (configured && configured > 0) {
    return configured;
  }

  const maxInputLength = runningConfig?.max_input_length;
  if (typeof maxInputLength === "number" && maxInputLength > 0) {
    const safetyMargin = Math.max(1024, Math.round(maxInputLength * 0.1));
    return maxInputLength + reservedResponseTokens + safetyMargin;
  }

  return DEFAULT_CONTEXT_WINDOW;
}

function clampRatio(tokens: number, windowTokens: number): number {
  if (windowTokens <= 0) return 0;
  return Math.min(1, Math.max(0, tokens / windowTokens));
}

export function formatTokenCount(tokens: number): string {
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}K`;
  }
  return String(tokens);
}

export function deriveRuntimeStatusSnapshot(
  input: RuntimeStatusInput,
): RuntimeStatusSnapshot {
  const provider = getActiveProvider(input.providers, input.activeModels);
  const providerId = input.activeModels?.active_llm?.provider_id;
  const modelId = input.activeModels?.active_llm?.model;
  const reservedResponseTokens =
    getNumberRecordValue(provider?.generate_kwargs as Record<string, unknown> | undefined, ["max_tokens"]) ||
    2048;
  const divisor =
    input.runningConfig?.token_count_estimate_divisor || DEFAULT_TOKEN_DIVISOR;
  const contextWindowTokens = inferContextWindowTokens(
    provider,
    input.runningConfig,
    reservedResponseTokens,
  );
  const systemInstructionsTokens = Math.max(1200, Math.round(contextWindowTokens * 0.017));
  const toolDefinitionsTokens = Math.max(2400, Math.round(contextWindowTokens * 0.037));
  const buckets = estimateChatHistoryBuckets(input.chatHistory, divisor);

  const breakdown: RuntimeStatusBreakdownItem[] = [
    {
      key: "system-instructions",
      label: "System Instructions",
      tokens: systemInstructionsTokens,
      ratio: clampRatio(systemInstructionsTokens, contextWindowTokens),
      section: "system",
    },
    {
      key: "tool-definitions",
      label: "Tool Definitions",
      tokens: toolDefinitionsTokens,
      ratio: clampRatio(toolDefinitionsTokens, contextWindowTokens),
      section: "system",
    },
    {
      key: "messages",
      label: "Messages",
      tokens: buckets.messages,
      ratio: clampRatio(buckets.messages, contextWindowTokens),
      section: "user",
    },
    {
      key: "tool-results",
      label: "Tool Results",
      tokens: buckets.toolResults,
      ratio: clampRatio(buckets.toolResults, contextWindowTokens),
      section: "user",
    },
    {
      key: "files",
      label: "Files",
      tokens: buckets.files,
      ratio: clampRatio(buckets.files, contextWindowTokens),
      section: "user",
    },
  ];

  const usedTokens = breakdown.reduce((total, item) => total + item.tokens, 0);
  const profileLabel = provider?.is_local ? "Local runtime" : "Cloud/runtime";

  return {
    scope_level: "chat",
    snapshot_source: "frontend_estimate",
    snapshot_stage: "client_live",
    agent_id: null,
    session_id: null,
    user_id: null,
    chat_id: null,
    context_window_tokens: contextWindowTokens,
    used_tokens: usedTokens,
    used_ratio: clampRatio(usedTokens, contextWindowTokens),
    reserved_response_tokens: reservedResponseTokens,
    remaining_tokens: Math.max(0, contextWindowTokens - usedTokens - reservedResponseTokens),
    model_id: modelId,
    provider_id: providerId,
    profile_label: profileLabel,
    breakdown,
  };
}

function matchesRuntimeStatusScope(
  snapshot: RuntimeStatusSnapshot,
  guard?: RuntimeStatusMergeGuard,
): boolean {
  if (!guard) {
    return true;
  }

  if (guard.expectedSnapshotStage && snapshot.snapshot_stage !== guard.expectedSnapshotStage) {
    return false;
  }

  if (guard.expectedAgentId && snapshot.agent_id && snapshot.agent_id !== guard.expectedAgentId) {
    return false;
  }

  if (guard.expectedChatId && snapshot.chat_id && snapshot.chat_id !== guard.expectedChatId) {
    return false;
  }

  return true;
}

export function mergeRuntimeStatusSnapshot(
  baseSnapshot: RuntimeStatusSnapshot | null | undefined,
  input: RuntimeStatusInput,
  guard?: RuntimeStatusMergeGuard,
): RuntimeStatusSnapshot {
  if (!baseSnapshot) {
    return deriveRuntimeStatusSnapshot(input);
  }

  if (baseSnapshot.snapshot_source === "empty_baseline") {
    return deriveRuntimeStatusSnapshot(input);
  }

  if (!matchesRuntimeStatusScope(baseSnapshot, guard)) {
    return deriveRuntimeStatusSnapshot(input);
  }

  const divisor =
    input.runningConfig?.token_count_estimate_divisor || DEFAULT_TOKEN_DIVISOR;
  const transientBuckets = estimateChatHistoryBuckets(input.chatHistory, divisor);
  const transientUsedTokens =
    transientBuckets.messages +
    transientBuckets.toolResults +
    transientBuckets.files;

  if (transientUsedTokens <= 0) {
    return baseSnapshot;
  }

  const nextBreakdown = baseSnapshot.breakdown.map((item) => {
    let tokens = item.tokens;
    if (item.key === "messages") {
      tokens += transientBuckets.messages;
    } else if (item.key === "tool-results") {
      tokens += transientBuckets.toolResults;
    } else if (item.key === "files") {
      tokens += transientBuckets.files;
    }

    return {
      ...item,
      tokens,
      ratio: clampRatio(tokens, baseSnapshot.context_window_tokens),
    };
  });

  const usedTokens = baseSnapshot.used_tokens + transientUsedTokens;
  return {
    ...baseSnapshot,
    used_tokens: usedTokens,
    used_ratio: clampRatio(usedTokens, baseSnapshot.context_window_tokens),
    remaining_tokens: Math.max(
      0,
      baseSnapshot.context_window_tokens -
        usedTokens -
        baseSnapshot.reserved_response_tokens,
    ),
    breakdown: nextBreakdown,
  };
}