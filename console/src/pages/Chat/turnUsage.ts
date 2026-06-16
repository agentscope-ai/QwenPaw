import ReactDOM from "react-dom";
import type {
  IAgentScopeRuntimeWebUIRef,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";

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

function parseSseDataLines(buffer: string): {
  events: string[];
  rest: string;
} {
  const events: string[] = [];
  let rest = buffer;
  for (;;) {
    const sep = rest.indexOf("\n\n");
    if (sep < 0) break;
    const block = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    for (const line of block.split("\n")) {
      if (line.startsWith("data: ")) {
        events.push(line.slice(6));
      }
    }
  }
  return { events, rest };
}

function snapshotFromSsePayload(raw: string): TurnUsageSnapshot | null {
  try {
    return parseTurnUsageSsePayload(JSON.parse(raw) as Record<string, unknown>);
  } catch {
    return null;
  }
}

/**
 * Observe the SSE body and patch usage when the stream finishes.
 *
 * Trailing `turn_usage` SSE arrives after Completed response. The chat SDK
 * may drop it via isStillActive (session id drift after realId URL resolve),
 * so we capture it here and patch after the SDK has finished reading.
 */
export function wrapChatResponseUsageStream(
  response: Response,
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
): Response {
  if (!response.body) return response;

  const decoder = new TextDecoder();
  let buffer = "";
  let pendingUsage: TurnUsageSnapshot | null = null;

  const transformed = response.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        controller.enqueue(chunk);
        buffer += decoder.decode(chunk, { stream: true });
        const parsed = parseSseDataLines(buffer);
        buffer = parsed.rest;
        for (const raw of parsed.events) {
          const snap = snapshotFromSsePayload(raw);
          if (snap) pendingUsage = snap;
        }
      },
      flush() {
        buffer += decoder.decode();
        const parsed = parseSseDataLines(`${buffer}\n\n`);
        for (const raw of parsed.events) {
          const snap = snapshotFromSsePayload(raw);
          if (snap) pendingUsage = snap;
        }
        if (pendingUsage) {
          schedulePatchLastResponseCardUsage(chatRef, pendingUsage);
        }
      },
    }),
  );

  return new Response(transformed, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
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
