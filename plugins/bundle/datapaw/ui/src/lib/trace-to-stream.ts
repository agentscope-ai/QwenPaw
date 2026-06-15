import type { StreamEvent } from "@/pages/Chat/components/TaskGraphPanel/types";
import type { TaskNode, TraceItem } from "@/pages/Chat/components/TaskGraphPanel/types";

function stringifyValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function normalizeToolOutput(output: unknown): string {
  if (output === undefined || output === null) return "";
  if (typeof output === "string") return output;
  return stringifyValue(output);
}

function pushToolCall(
  events: StreamEvent[],
  data: Record<string, unknown>,
): void {
  const callId = String(data.call_id || data.id || `tool-${events.length}`);
  const name = String(data.name || "");
  const argsRaw = data.arguments ?? data.input;
  const argsStr =
    argsRaw !== undefined && argsRaw !== null && argsRaw !== ""
      ? stringifyValue(argsRaw)
      : undefined;
  const hasOutput = data.output !== undefined && data.output !== null;

  const existing = events.find(
    (event) => event.type === "tool_call" && event.call_id === callId,
  );
  if (existing && existing.type === "tool_call") {
    if (argsStr && argsStr.length >= (existing.arguments?.length || 0)) {
      existing.arguments = argsStr;
    }
    if (hasOutput) {
      existing.output = normalizeToolOutput(data.output);
    }
    if (name && !existing.name) {
      existing.name = name;
    }
    return;
  }

  events.push({
    type: "tool_call",
    call_id: callId,
    name,
    arguments: argsStr ?? "",
    ...(hasOutput ? { output: normalizeToolOutput(data.output) } : {}),
  });
}

function appendContentBlock(
  events: StreamEvent[],
  block: Record<string, unknown>,
): void {
  const blockType = block.type;
  if (blockType === "text" && typeof block.text === "string") {
    events.push({ type: "text", text: block.text });
    return;
  }
  if (blockType === "thinking" && typeof block.thinking === "string") {
    events.push({ type: "thinking", thinking: block.thinking });
    return;
  }
  if (blockType === "data" && block.data) {
    pushToolCall(events, block.data as Record<string, unknown>);
    return;
  }
  if (blockType === "tool_use") {
    pushToolCall(events, {
      call_id: block.id,
      name: block.name,
      arguments: block.input ?? block.arguments,
    });
    return;
  }
  if (blockType === "tool_result") {
    pushToolCall(events, {
      call_id: block.id ?? block.tool_use_id,
      name: block.name,
      output: block.output,
    });
  }
}

function appendTraceItem(events: StreamEvent[], item: TraceItem): void {
  if (!item) return;

  if (item.type === "thinking" && item.data) {
    events.push({ type: "thinking", thinking: String(item.data) });
    return;
  }
  if (item.type === "text" && item.data) {
    events.push({ type: "text", text: String(item.data) });
    return;
  }

  const content = item.content as unknown;
  if (Array.isArray(content)) {
    for (const block of content) {
      if (!block || typeof block !== "object") continue;
      appendContentBlock(events, block as Record<string, unknown>);
    }
    return;
  }

  if (typeof content === "string" && content.trim()) {
    events.push({ type: "text", text: content });
  }
}

/** Build drawer stream events from persisted node trace returned by /api/tasks. */
export function traceToStreamEvents(node: TaskNode): StreamEvent[] {
  const trace = node.trace ?? node.output?.trace ?? [];
  if (!Array.isArray(trace) || trace.length === 0) {
    return [];
  }

  const events: StreamEvent[] = [];
  for (const item of trace) {
    appendTraceItem(events, item as TraceItem);
  }
  return events;
}

function backfillLiveEvents(
  live: StreamEvent[],
  persisted: StreamEvent[],
): StreamEvent[] {
  const persistedByCallId = new Map<string, Extract<StreamEvent, { type: "tool_call" }>>();
  for (const event of persisted) {
    if (event.type === "tool_call" && event.call_id) {
      persistedByCallId.set(event.call_id, event);
    }
  }

  return live.map((event) => {
    if (event.type !== "tool_call") return event;
    const saved = persistedByCallId.get(event.call_id);
    if (!saved) return event;
    return {
      ...event,
      name: event.name || saved.name,
      arguments:
        event.arguments && event.arguments !== "{}" && event.arguments.trim()
          ? event.arguments
          : saved.arguments || event.arguments,
      output: event.output ?? saved.output,
    };
  });
}

export function mergeStreamEvents(
  persisted: StreamEvent[],
  live: StreamEvent[],
  isStreaming = false,
): StreamEvent[] {
  if (live.length === 0) return persisted;
  if (persisted.length === 0) return live;

  if (isStreaming) {
    return live.length >= persisted.length ? live : [...persisted, ...live];
  }

  // Completed: keep the same live stream snapshot used during execution
  // (FetchDataBlock / TextBlock), only backfill missing fields.
  return backfillLiveEvents(live, persisted);
}

/** Resolve drawer stream events from live SSE + persisted trace. */
export function resolveDrawerStreamEvents(
  node: TaskNode,
  live: StreamEvent[],
  isStreaming: boolean,
): StreamEvent[] {
  const persisted = traceToStreamEvents(node);
  return mergeStreamEvents(persisted, live, isStreaming);
}
