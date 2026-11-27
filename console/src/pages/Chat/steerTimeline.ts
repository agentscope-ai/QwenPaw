export type SteerContent = Array<{ type: string; [key: string]: unknown }>;

export interface SteerReceipt {
  turn_id: string;
  client_message_id: string;
  user_message_id: string;
  content: SteerContent;
  append_seq: number;
  revision: number;
  status: string;
  reason?: string;
  message?: TimelineMessage;
}
export interface TimelineMessage {
  id: string;
  role?: string;
  metadata?: Record<string, unknown>;
  content?: unknown[];
}
export interface TimelineRow<T> {
  kind: "assistant" | "user";
  key: string;
  messages: T[];
  content?: unknown[];
  status?: string;
  messageId?: string;
  reason?: string;
}
const position = (m: TimelineMessage) =>
  (m.metadata?.qwenpaw_transcript_position as { ordinal?: number } | undefined)
    ?.ordinal;

export function projectTurnTimeline<T extends TimelineMessage>(
  messages: T[],
  receipts: SteerReceipt[],
  turnId: string,
): TimelineRow<T>[] {
  const rows: TimelineRow<T>[] = [];
  const segments = new Map<string, TimelineRow<T>>();
  const seen = new Set<string>();
  const present = new Set(messages.map((m) => m.id));
  const recovered = receipts.flatMap((r) =>
    r.message && !present.has(r.message.id) ? [r.message as T] : [],
  );
  if (recovered.length) messages = [...messages, ...recovered];
  const rank = (m: TimelineMessage) => position(m) ?? Number.MAX_SAFE_INTEGER;
  const ordered = messages.some(
    (m, i) => i > 0 && rank(m) < rank(messages[i - 1]),
  )
    ? [...messages].sort((a, b) => rank(a) - rank(b))
    : messages;
  for (const msg of ordered) {
    if (msg.role === "user") {
      seen.add(msg.id);
      rows.push({
        kind: "user",
        key: String(msg.metadata?.client_message_id || msg.id),
        messageId: msg.id,
        messages: [msg],
        status: "applied",
        content: msg.content || [],
      });
      continue;
    }
    const anchor = String(msg.metadata?.after_user_message_id || "initial");
    const key = `${turnId}:${anchor}`;
    let row = segments.get(key);
    if (!row) {
      if (
        segments.size > 0 &&
        !seen.has(anchor) &&
        !receipts.some((r) => r.user_message_id === anchor)
      ) {
        rows.push({
          kind: "user",
          key: `sync:${anchor}`,
          messageId: anchor,
          messages: [],
          status: "syncing",
        });
      }
      row = { kind: "assistant", key, messages: [] };
      segments.set(key, row);
      rows.push(row);
    }
    row.messages.push(msg);
  }
  const orderedReceipts = [...receipts].sort(
    (a, b) => a.append_seq - b.append_seq,
  );
  for (const [index, receipt] of orderedReceipts.entries()) {
    if (seen.has(receipt.user_message_id)) continue;
    const row: TimelineRow<T> = {
      kind: "user",
      key: receipt.client_message_id,
      messageId: receipt.user_message_id,
      messages: [],
      content: receipt.content,
      status: receipt.status === "applied" ? "syncing" : receipt.status,
      reason: receipt.reason,
    };
    const laterIds = new Set(
      orderedReceipts.slice(index).map((r) => r.user_message_id),
    );
    const segmentIndex = rows.findIndex(
      (r) =>
        (r.kind === "user" && laterIds.has(r.messageId || "")) ||
        (r.kind === "assistant" &&
          orderedReceipts
            .slice(index)
            .some((later) => r.key === `${turnId}:${later.user_message_id}`)),
    );
    if (segmentIndex >= 0) rows.splice(segmentIndex, 0, row);
    else rows.push(row);
  }
  const last = rows[rows.length - 1];
  if (last?.kind === "user" && last.status === "applied") {
    rows.push({
      kind: "assistant",
      key: `${turnId}:${last.messageId}`,
      messages: [],
    });
  }
  return rows;
}
