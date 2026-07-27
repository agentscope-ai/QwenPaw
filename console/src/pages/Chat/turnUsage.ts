import ReactDOM from "react-dom";
import type {
  IAgentScopeRuntimeWebUIRef,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import { useTurnUsageStore } from "./turnUsageStore";
import { shouldForwardReplayPayload } from "./replayRecovery";

export const TURN_USAGE_META_KEY = "qwenpaw_turn_usage";

export interface TurnUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  estimated?: boolean;
}

export interface ContextUsage {
  estimated_tokens: number;
  max_input_length: number;
  context_usage_ratio: number;
}

export interface TurnUsageSnapshot {
  usage: TurnUsage | null;
  context_usage: ContextUsage | null;
}

const readNumber = (obj: unknown, key: string): number => {
  if (!obj || typeof obj !== "object") return 0;
  const v = (obj as Record<string, unknown>)[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
};

function parseTurnUsagePayload(raw: unknown): TurnUsageSnapshot | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const usageRaw = obj.usage;
  const ctxRaw = obj.context_usage;
  const usage =
    usageRaw && typeof usageRaw === "object" ? (usageRaw as TurnUsage) : null;
  const context =
    ctxRaw && typeof ctxRaw === "object" ? (ctxRaw as ContextUsage) : null;
  const usageTotal =
    readNumber(usage, "total_tokens") ||
    readNumber(usage, "prompt_tokens") + readNumber(usage, "completion_tokens");
  const hasUsage = !!usage && usageTotal > 0;
  const hasCtx = !!context && readNumber(context, "estimated_tokens") > 0;
  if (!hasUsage && !hasCtx) return null;
  return {
    usage: hasUsage ? usage : null,
    context_usage: hasCtx ? context : null,
  };
}

/** Read ``qwenpaw_turn_usage`` from backend message metadata wrappers. */
export function extractTurnUsageFromBackendMetadata(
  meta: unknown,
): TurnUsageSnapshot | null {
  if (!meta || typeof meta !== "object") return null;
  const wrapper = meta as Record<string, unknown>;
  const direct = parseTurnUsagePayload(wrapper[TURN_USAGE_META_KEY]);
  if (direct) return direct;
  const inner = wrapper.metadata;
  if (inner && typeof inner === "object") {
    return parseTurnUsagePayload(
      (inner as Record<string, unknown>)[TURN_USAGE_META_KEY],
    );
  }
  return null;
}

export function extractTurnUsageFromOutputMessages(
  messages: Array<{ metadata?: unknown }>,
): TurnUsageSnapshot | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const snap = extractTurnUsageFromBackendMetadata(messages[i]?.metadata);
    if (snap) return snap;
  }
  return null;
}

export function readTurnUsageFromResponseCardData(
  data: Record<string, unknown> | null | undefined,
): TurnUsageSnapshot | null {
  if (!data) return null;
  const usage = data.usage;
  const context = data.context_usage;
  const hasUsage =
    usage &&
    typeof usage === "object" &&
    (readNumber(usage, "total_tokens") > 0 ||
      readNumber(usage, "prompt_tokens") +
        readNumber(usage, "completion_tokens") >
        0);
  const hasCtx =
    context &&
    typeof context === "object" &&
    readNumber(context, "estimated_tokens") > 0;
  if (!hasUsage && !hasCtx) return null;
  return {
    usage: hasUsage ? (usage as TurnUsage) : null,
    context_usage: hasCtx ? (context as ContextUsage) : null,
  };
}

function getResponseCardData(
  cards: IAgentScopeRuntimeWebUIMessage["cards"],
): Record<string, unknown> | null {
  const card = (
    cards as
      | Array<{ code?: string; data?: Record<string, unknown> }>
      | undefined
  )?.find((c) => c?.code === "AgentScopeRuntimeResponseCard");
  return card?.data ?? null;
}

/** Latest turn usage snapshot from assistant response cards (newest first). */
export function extractLatestSnapshotFromCards(
  messages: IAgentScopeRuntimeWebUIMessage[],
): TurnUsageSnapshot | null {
  const assistants = messages.filter((m) => m.role === "assistant");
  for (let i = assistants.length - 1; i >= 0; i--) {
    const data = getResponseCardData(assistants[i].cards);
    if (!data) continue;
    const snap = readTurnUsageFromResponseCardData(data);
    if (snap) return snap;
  }
  return null;
}

function findPatchTargetAssistant(
  messages: IAgentScopeRuntimeWebUIMessage[],
): IAgentScopeRuntimeWebUIMessage | undefined {
  const assistants = messages.filter((m) => m.role === "assistant");
  if (!assistants.length) return undefined;
  // Prefer the latest assistant card that still lacks usage (current turn).
  for (let i = assistants.length - 1; i >= 0; i--) {
    const data = getResponseCardData(assistants[i].cards);
    if (!data) continue;
    const snap = readTurnUsageFromResponseCardData(data);
    if (!snap || !snap.context_usage) {
      return assistants[i];
    }
  }
  for (let i = assistants.length - 1; i >= 0; i--) {
    if (getResponseCardData(assistants[i].cards)) {
      return assistants[i];
    }
  }
  return undefined;
}

export function patchLastResponseCardUsage(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  snapshot: TurnUsageSnapshot,
): boolean {
  const messagesApi = chatRef.current?.messages;
  if (!messagesApi) return false;

  const lastAssistantMsg = findPatchTargetAssistant(
    messagesApi.getMessages() ?? [],
  );
  if (!lastAssistantMsg) return false;

  const data = getResponseCardData(lastAssistantMsg.cards);
  if (!data) return false;

  const prev = readTurnUsageFromResponseCardData(data);
  if (
    prev &&
    readNumber(prev.usage, "total_tokens") ===
      readNumber(snapshot.usage, "total_tokens") &&
    readNumber(prev.context_usage, "estimated_tokens") ===
      readNumber(snapshot.context_usage, "estimated_tokens")
  ) {
    return true;
  }

  const updatedMsg = JSON.parse(
    JSON.stringify(lastAssistantMsg),
  ) as IAgentScopeRuntimeWebUIMessage;
  const updatedData = getResponseCardData(updatedMsg.cards);
  if (!updatedData) return false;
  if (snapshot.usage) updatedData.usage = snapshot.usage;
  if (snapshot.context_usage) {
    updatedData.context_usage = snapshot.context_usage;
  }
  ReactDOM.flushSync(() => {
    messagesApi.updateMessage(updatedMsg);
  });
  return true;
}

const PATCH_RETRY_MS = 50;
const PATCH_MAX_ATTEMPTS = 40;

export function schedulePatchLastResponseCardUsage(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  snapshot: TurnUsageSnapshot,
): void {
  const tryPatch = () => patchLastResponseCardUsage(chatRef, snapshot);
  if (tryPatch()) return;
  let attempt = 0;
  const retry = () => {
    if (tryPatch() || attempt >= PATCH_MAX_ATTEMPTS) return;
    attempt += 1;
    window.setTimeout(retry, PATCH_RETRY_MS);
  };
  window.setTimeout(retry, 0);
}

/** Re-calculate context ring denominator after model switch. */
export function patchContextMaxInputLength(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  newMaxInputLength: number,
): void {
  const messagesApi = chatRef.current?.messages;
  if (!messagesApi || newMaxInputLength <= 0) return;

  const allMessages = messagesApi.getMessages() ?? [];
  for (let i = allMessages.length - 1; i >= 0; i--) {
    const msg = allMessages[i];
    if (msg.role !== "assistant") continue;
    const data = getResponseCardData(msg.cards);
    if (!data) continue;
    const snap = readTurnUsageFromResponseCardData(data);
    if (!snap?.context_usage) continue;

    const estimatedTokens = readNumber(snap.context_usage, "estimated_tokens");
    if (
      readNumber(snap.context_usage, "max_input_length") === newMaxInputLength
    ) {
      return;
    }

    const newRatio = Math.min((estimatedTokens / newMaxInputLength) * 100, 100);
    const updatedMsg = JSON.parse(
      JSON.stringify(msg),
    ) as IAgentScopeRuntimeWebUIMessage;
    const updatedData = getResponseCardData(updatedMsg.cards);
    if (!updatedData) return;
    const updatedContext: ContextUsage = {
      estimated_tokens: estimatedTokens,
      max_input_length: newMaxInputLength,
      context_usage_ratio: newRatio,
    };
    updatedData.context_usage = updatedContext;
    ReactDOM.flushSync(() => {
      messagesApi.updateMessage(updatedMsg);
    });
    useTurnUsageStore.getState().setSnapshot({
      usage: snap.usage,
      context_usage: updatedContext,
    });
    return;
  }

  const storeSnap = useTurnUsageStore.getState().snapshot;
  if (
    storeSnap?.context_usage &&
    readNumber(storeSnap.context_usage, "max_input_length") !==
      newMaxInputLength
  ) {
    const estimatedTokens = readNumber(
      storeSnap.context_usage,
      "estimated_tokens",
    );
    const newRatio = Math.min((estimatedTokens / newMaxInputLength) * 100, 100);
    useTurnUsageStore.getState().setSnapshot({
      usage: storeSnap.usage,
      context_usage: {
        estimated_tokens: estimatedTokens,
        max_input_length: newMaxInputLength,
        context_usage_ratio: newRatio,
      },
    });
  }
}

function splitSseBlocks(buffer: string): {
  blocks: string[];
  rest: string;
} {
  const blocks: string[] = [];
  const separator = /\r?\n\r?\n/g;
  let start = 0;
  let match = separator.exec(buffer);
  while (match) {
    blocks.push(buffer.slice(start, match.index));
    start = separator.lastIndex;
    match = separator.exec(buffer);
  }
  return { blocks, rest: buffer.slice(start) };
}

function readSseData(block: string): string | null {
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line.startsWith("data:")) continue;
    const value = line.slice(5);
    dataLines.push(value.startsWith(" ") ? value.slice(1) : value);
  }
  return dataLines.length > 0 ? dataLines.join("\n") : null;
}

/**
 * Filter private SSE control frames before the chat SDK reads the body.
 *
 * Trailing `turn_usage` is captured here and patched after the SDK finishes.
 * On replay truncation, intermediate events are dropped until a canonical
 * completed response or terminal error arrives.
 */
export function wrapChatResponseUsageStream(
  response: Response,
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
): Response {
  if (!response.body) return response;

  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";
  let pendingUsage: TurnUsageSnapshot | null = null;
  let streamTruncated = false;

  const processBlock = (
    block: string,
    controller: TransformStreamDefaultController<Uint8Array>,
  ) => {
    const raw = readSseData(block);
    if (raw === null) {
      controller.enqueue(encoder.encode(`${block}\n\n`));
      return;
    }

    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      controller.enqueue(encoder.encode(`${block}\n\n`));
      return;
    }

    if (payload.type === "turn_usage") {
      const snapshot = parseTurnUsageSsePayload(payload);
      if (snapshot) pendingUsage = snapshot;
    }

    const replayDecision = shouldForwardReplayPayload(payload, streamTruncated);
    streamTruncated = replayDecision.streamTruncated;
    if (replayDecision.forward) {
      controller.enqueue(encoder.encode(`${block}\n\n`));
    }
  };

  const transformed = response.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        buffer += decoder.decode(chunk, { stream: true });
        const parsed = splitSseBlocks(buffer);
        buffer = parsed.rest;
        for (const block of parsed.blocks) {
          processBlock(block, controller);
        }
      },
      flush(controller) {
        buffer += decoder.decode();
        if (buffer.trim()) {
          processBlock(buffer, controller);
        }
        if (pendingUsage) {
          useTurnUsageStore.getState().setSnapshot(pendingUsage);
          schedulePatchLastResponseCardUsage(chatRef, pendingUsage);
        }
      },
    }),
  );

  const headers = new Headers(response.headers);
  headers.delete("content-length");

  return new Response(transformed, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function parseTurnUsageSsePayload(
  payload: Record<string, unknown>,
): TurnUsageSnapshot | null {
  if (payload.type !== "turn_usage") {
    return null;
  }
  const usage = payload.usage;
  const ctx = payload.context_usage;
  const usageTotal =
    readNumber(usage, "total_tokens") ||
    readNumber(usage, "prompt_tokens") + readNumber(usage, "completion_tokens");
  const hasUsage = usage && typeof usage === "object" && usageTotal > 0;
  const hasCtx =
    ctx && typeof ctx === "object" && readNumber(ctx, "estimated_tokens") > 0;
  if (!hasUsage && !hasCtx) return null;

  return {
    usage: hasUsage ? (usage as TurnUsage) : null,
    context_usage: hasCtx ? (ctx as ContextUsage) : null,
  };
}
