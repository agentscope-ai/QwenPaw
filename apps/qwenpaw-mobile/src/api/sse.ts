export interface SseEvent {
  event?: string;
  data: string;
}

export interface StreamDelta {
  messageId: string;
  kind: "message" | "reasoning" | "tool";
  text: string;
}

export function streamError(event: SseEvent): string | null {
  const payload = jsonPayload(event.data);
  if (!payload) return null;
  if (typeof payload.error === "string") {
    return payload.error.trim() || "模型调用失败";
  }
  if (payload.object !== "response" || payload.status !== "failed") {
    return null;
  }
  const error = payload.error;
  if (error && typeof error === "object" && !Array.isArray(error)) {
    const detail = error as Record<string, unknown>;
    const message = detail.message ?? detail.detail ?? detail.code;
    if (typeof message === "string" && message.trim()) return message.trim();
  }
  return "模型调用失败";
}

export class StreamEventClassifier {
  private readonly messageTypes = new Map<string, StreamDelta["kind"]>();

  consume(event: SseEvent): StreamDelta | null {
    const payload = jsonPayload(event.data);
    if (!payload) return null;
    if (payload.object === "message") {
      const id = typeof payload.id === "string" ? payload.id : "";
      const kind = messageKind(payload.type);
      if (id) this.messageTypes.set(id, kind);
      const text = messageDeltaText(payload.content);
      return text ? { messageId: id || "stream", kind, text } : null;
    }
    if (payload.object !== "content" || payload.delta !== true) return null;
    const messageId = typeof payload.msg_id === "string"
      ? payload.msg_id
      : "stream";
    const text = typeof payload.text === "string" ? payload.text : "";
    if (!text) return null;
    return {
      messageId,
      kind: this.messageTypes.get(messageId) ?? "message",
      text,
    };
  }
}

export class SseParser {
  private buffer = "";

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const blocks = this.buffer.split("\n\n");
    this.buffer = blocks.pop() ?? "";
    return blocks.flatMap(parseBlock);
  }

  finish(): SseEvent[] {
    const block = this.buffer;
    this.buffer = "";
    return block.trim() ? parseBlock(block) : [];
  }
}

function parseBlock(block: string): SseEvent[] {
  let event: string | undefined;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const value = separator < 0
      ? ""
      : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  return data.length ? [{ event, data: data.join("\n") }] : [];
}

export function eventText(event: SseEvent): string {
  if (event.data === "[DONE]") return "";
  try {
    const payload = JSON.parse(event.data) as Record<string, unknown>;
    if (payload.object === "content" && payload.delta === true) {
      return typeof payload.text === "string" ? payload.text : "";
    }
    if (payload.object === "message" && payload.status === "in_progress") {
      return messageDeltaText(payload.content);
    }
    return "";
  } catch {
    return event.data;
  }
}

function jsonPayload(value: string): Record<string, unknown> | null {
  if (value === "[DONE]") return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function messageKind(value: unknown): StreamDelta["kind"] {
  if (value === "reasoning") return "reasoning";
  if (
    typeof value === "string" &&
    (value.includes("call") || value.includes("tool") || value.includes("plugin"))
  ) return "tool";
  return "message";
}

function messageDeltaText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content.map((item) => {
    if (!item || typeof item !== "object") return "";
    const part = item as Record<string, unknown>;
    return part.delta === true && typeof part.text === "string"
      ? part.text
      : "";
  }).join("");
}
