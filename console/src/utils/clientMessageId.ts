export const QWENPAW_CLIENT_MESSAGE_ID_KEY = "qwenpaw_client_message_id";

function randomBase36(length: number): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let value = "";
  for (const byte of bytes) value += (byte % 36).toString(36);
  return value;
}

export function createClientMessageId(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${randomBase36(16)}`;
}

export function attachClientMessageId(
  message: Record<string, unknown>,
  clientMessageId: string,
): Record<string, unknown> {
  const metadata =
    typeof message.metadata === "object" && message.metadata !== null
      ? message.metadata
      : {};
  return {
    ...message,
    metadata: {
      ...metadata,
      [QWENPAW_CLIENT_MESSAGE_ID_KEY]: clientMessageId,
    },
  };
}
