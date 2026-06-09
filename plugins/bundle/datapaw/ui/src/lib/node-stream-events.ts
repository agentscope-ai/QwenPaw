import type { StreamEvent } from "@/pages/Chat/components/TaskGraphPanel/types";

type Listener = () => void;

const eventsMap: Record<string, StreamEvent[]> = {};
const listeners = new Set<Listener>();
let streamRevision = 0;

/** Stable empty snapshot — must not allocate a new [] on each getSnapshot call. */
export const EMPTY_NODE_STREAM_EVENTS: StreamEvent[] = [];

function notify(): void {
  streamRevision += 1;
  listeners.forEach((listener) => listener());
}

/** Monotonic revision for useSyncExternalStore (events mutate in place). */
export function getNodeStreamRevision(): number {
  return streamRevision;
}

export function subscribeNodeStreamEvents(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Return the store array reference (mutated in place). Required for useSyncExternalStore. */
export function getNodeStreamEvents(nodeId: string): StreamEvent[] {
  return eventsMap[nodeId] ?? EMPTY_NODE_STREAM_EVENTS;
}

export function resetNodeStreamEvents(): void {
  for (const key of Object.keys(eventsMap)) {
    delete eventsMap[key];
  }
  notify();
}

function ensureEvents(nodeId: string): StreamEvent[] {
  if (!eventsMap[nodeId]) {
    eventsMap[nodeId] = [];
  }
  return eventsMap[nodeId];
}

function appendNewlineToTrailingThinking(events: StreamEvent[]): void {
  const last = events[events.length - 1];
  if (last?.type === "thinking" && !last.thinking.endsWith("\n")) {
    last.thinking += "\n";
  }
}

export function handleLiveText(
  text: string,
  metadata?: { node_id?: string; graph_id?: string },
  msgId?: string,
): void {
  const key = metadata?.node_id;
  if (!key) return;
  const events = ensureEvents(key);
  const last = events[events.length - 1];
  if (last?.type === "text" && last.msg_id === msgId) {
    last.text += text;
  } else {
    if (last?.type === "text" && !last.text.endsWith("\n")) {
      last.text += "\n";
    }
    appendNewlineToTrailingThinking(events);
    events.push({ type: "text", text, msg_id: msgId });
  }
  notify();
}

export function handleToolCall(
  data: { call_id: string; name: string; arguments: string },
  metadata?: { node_id?: string; graph_id?: string },
): void {
  const key = metadata?.node_id;
  if (!key) return;
  const events = ensureEvents(key);
  const existing =
    data.call_id &&
    events.find(
      (event) => event.type === "tool_call" && event.call_id === data.call_id,
    );
  if (existing && existing.type === "tool_call") {
    if (
      data.arguments &&
      data.arguments.length >= (existing.arguments?.length || 0)
    ) {
      existing.arguments = data.arguments;
      notify();
    }
    return;
  }
  appendNewlineToTrailingThinking(events);
  events.push({ type: "tool_call", ...data });
  notify();
}

export function handleThinking(
  thinking: string,
  metadata?: { node_id?: string; graph_id?: string },
): void {
  const key = metadata?.node_id;
  if (!key) return;
  const events = ensureEvents(key);
  const last = events[events.length - 1];
  if (last?.type === "thinking") {
    last.thinking += thinking;
  } else {
    events.push({ type: "thinking", thinking });
  }
  notify();
}

export function handleToolResult(
  data: { call_id: string; name: string; output: string },
  metadata?: { node_id?: string; graph_id?: string },
): void {
  const key = metadata?.node_id;
  if (!key) return;
  const events = ensureEvents(key);
  if (key) {
    const matched = events.find(
      (event) =>
        event.type === "tool_call" &&
        data.call_id &&
        event.call_id === data.call_id,
    );
    if (matched && matched.type === "tool_call") {
      matched.output = data.output;
      notify();
      return;
    }
  }
  for (const nodeKey of Object.keys(eventsMap)) {
    const nodeEvents = eventsMap[nodeKey];
    const matched = nodeEvents.find(
      (event) =>
        event.type === "tool_call" &&
        data.call_id &&
        event.call_id === data.call_id,
    );
    if (matched && matched.type === "tool_call") {
      matched.output = data.output;
      notify();
      return;
    }
  }
}
