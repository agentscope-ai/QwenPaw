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
  private revision = 0;
  private baseVersions = new Map<string, number>();
  private liveVersions = new Map<string, number>();

  reset(base: Message[] = []): void {
    this.base = [...base];
    this.live = [];
    this.revision += 1;
    this.baseVersions.clear();
    this.liveVersions.clear();
  }

  replaceBase(base: Message[]): void {
    // A Voice admission event may beat the initial history request. Seed from
    // canonical history while retaining those already-observed newer inputs.
    this.base = mergeMessages(base, this.base);
  }

  mergeBase(messages: Message[]): void {
    this.base = mergeMessages(this.base, messages);
    this.markChanged(messages, this.baseVersions);
  }

  historyCheckpoint(): number {
    return this.revision;
  }

  mergeHistory(messages: Message[], checkpoint: number): void {
    const keys = new Set(messages.map(messageKey));
    // Canonical history replaces the captured live copies. Output received
    // while the request was in flight and newer tail commits still win.
    const accepted = messages.filter(
      (message, index) =>
        (this.baseVersions.get(messageKey(message, index)) ?? 0) <= checkpoint,
    );
    this.base = mergeMessages(this.base, accepted);
    this.markChanged(accepted, this.baseVersions);
    this.live = this.live.filter((message, index) => {
      const key = messageKey(message, index);
      return !keys.has(key) || (this.liveVersions.get(key) ?? 0) > checkpoint;
    });
  }

  private markChanged(
    messages: Message[],
    versions: Map<string, number>,
  ): void {
    const revision = ++this.revision;
    messages.forEach((message, index) =>
      versions.set(messageKey(message, index), revision),
    );
  }

  ingest(payload: RuntimePayload): boolean {
    if (payload.object === "response") {
      const output = Array.isArray(payload.output)
        ? (payload.output as Message[])
        : [];
      this.live = mergeMessages(this.live, output);
      this.markChanged(output, this.liveVersions);
      return true;
    }
    if (payload.object === "message") {
      if (payload.type === "heartbeat") return true;
      this.live = mergeMessages(this.live, [payload as Message]);
      this.markChanged([payload as Message], this.liveVersions);
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
    this.markChanged([message], this.liveVersions);
    return true;
  }

  messages(): Message[] {
    return mergeMessages(this.base, this.live);
  }
}
