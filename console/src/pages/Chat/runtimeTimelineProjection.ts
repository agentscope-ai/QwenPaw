import type { Message } from "../../api";

type RuntimePayload = Record<string, unknown>;

function messageKey(message: Message, index: number): string {
  if (typeof message.id === "string" && message.id) return `id:${message.id}`;
  const metadata =
    message.metadata && typeof message.metadata === "object"
      ? (message.metadata as Record<string, unknown>)
      : {};
  const nested =
    metadata.metadata && typeof metadata.metadata === "object"
      ? (metadata.metadata as Record<string, unknown>)
      : metadata;
  const clientId = nested.qwenpaw_client_message_id;
  if (typeof clientId === "string" && clientId) return `client:${clientId}`;
  const originalId = metadata.original_id;
  if (typeof originalId === "string" && originalId) {
    return `original:${originalId}:${String(message.type || message.role)}`;
  }
  return `fallback:${index}:${String(message.role)}:${String(message.type)}`;
}

function mergeMessages(base: Message[], incoming: Message[]): Message[] {
  const result = [...base];
  const positions = new Map(
    result.map((message, index) => [messageKey(message, index), index]),
  );
  for (const message of incoming) {
    const key = messageKey(message, result.length);
    const existingIndex = positions.get(key);
    if (existingIndex === undefined) {
      positions.set(key, result.length);
      result.push(message);
      continue;
    }
    const existing = result[existingIndex];
    const incomingContent = Array.isArray(message.content)
      ? message.content
      : undefined;
    const existingContent = Array.isArray(existing.content)
      ? existing.content
      : undefined;
    result[existingIndex] = {
      ...existing,
      ...message,
      ...(!incomingContent?.length && existingContent?.length
        ? { content: existing.content }
        : {}),
    };
  }
  return result;
}

function mergeDeltaData(
  current: Record<string, unknown> | undefined,
  incoming: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!incoming) return current;
  const result = { ...(current ?? {}) };
  for (const [key, value] of Object.entries(incoming)) {
    result[key] =
      typeof value === "string" && typeof result[key] === "string"
        ? `${result[key]}${value}`
        : value;
  }
  return result;
}

/**
 * Accumulates the raw AgentScope Runtime protocol without imposing a visual
 * response-card boundary. QwenPaw's semantic timeline projector owns that
 * boundary because one runtime run may serve several queued Voice inputs.
 */
export class RuntimeTimelineAccumulator {
  private base: Message[] = [];
  private live: Message[] = [];

  reset(base: Message[] = []): void {
    this.base = [...base];
    this.live = [];
  }

  replaceBase(base: Message[]): void {
    // A Voice admission event may beat the initial history request. Seed from
    // canonical history while retaining those already-observed newer inputs.
    this.base = mergeMessages(base, this.base);
  }

  mergeBase(messages: Message[]): void {
    this.base = mergeMessages(this.base, messages);
  }

  ingest(payload: RuntimePayload): boolean {
    if (payload.object === "response") {
      const output = Array.isArray(payload.output)
        ? (payload.output as Message[])
        : [];
      this.live = mergeMessages(this.live, output);
      return true;
    }
    if (payload.object === "message") {
      if (payload.type === "heartbeat") return true;
      this.live = mergeMessages(this.live, [payload as Message]);
      return true;
    }
    if (payload.object !== "content") return false;

    const messageId = payload.msg_id;
    if (typeof messageId !== "string") return true;
    const message = this.live.find((item) => item.id === messageId);
    if (!message) return true;
    const content = Array.isArray(message.content)
      ? (message.content as Array<Record<string, unknown>>)
      : [];
    const incoming = payload as Record<string, unknown>;
    const last = content[content.length - 1];
    if (payload.delta) {
      if (last?.delta && last.type === incoming.type) {
        if (incoming.type === "text") {
          last.text = `${String(last.text ?? "")}${String(
            incoming.text ?? "",
          )}`;
        } else if (incoming.type === "image") {
          last.image_url = incoming.image_url;
        } else if (incoming.type === "data") {
          last.data = mergeDeltaData(
            last.data as Record<string, unknown> | undefined,
            incoming.data as Record<string, unknown> | undefined,
          );
        }
      } else {
        content.push({ ...incoming });
      }
    } else if (last) {
      Object.assign(last, incoming);
    } else {
      content.push({ ...incoming });
    }
    message.content = content;
    return true;
  }

  messages(): Message[] {
    return mergeMessages(this.base, this.live);
  }
}
