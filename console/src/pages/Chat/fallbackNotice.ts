export type ModelFallbackEvent = {
  type: "model_fallback";
  from_provider_id: string;
  from_model_id: string;
  to_provider_id: string;
  to_model_id: string;
  reason_kind: string;
};

export function parseModelFallbackEvents(
  payload: Record<string, unknown>,
): ModelFallbackEvent[] {
  const metadata = payload.metadata;
  const metadataRecord =
    metadata && typeof metadata === "object"
      ? (metadata as Record<string, unknown>)
      : null;
  const nestedMetadata = metadataRecord?.metadata;
  const eventSource =
    nestedMetadata && typeof nestedMetadata === "object"
      ? (nestedMetadata as Record<string, unknown>)
      : metadataRecord;
  const events = eventSource?.qwenpaw_model_fallbacks;
  if (!Array.isArray(events)) return [];
  return events.filter((event): event is ModelFallbackEvent => {
    if (!event || typeof event !== "object") return false;
    const record = event as Record<string, unknown>;
    return (
      record.type === "model_fallback" &&
      typeof record.from_provider_id === "string" &&
      typeof record.from_model_id === "string" &&
      typeof record.to_provider_id === "string" &&
      typeof record.to_model_id === "string" &&
      typeof record.reason_kind === "string"
    );
  });
}

export function modelFallbackEventKey(event: ModelFallbackEvent): string {
  return JSON.stringify(event);
}

export type FallbackSystemMessage = {
  type: "message";
  role: "system";
  content: Array<{ type: "text"; text: string }>;
  metadata: { qwenpaw_model_fallbacks: ModelFallbackEvent[] };
};

export function buildFallbackSystemMessage(
  events: ModelFallbackEvent[],
  formatNotice: (event: ModelFallbackEvent) => string,
): FallbackSystemMessage {
  return {
    type: "message",
    role: "system",
    content: [
      {
        type: "text",
        text: events.map(formatNotice).join("\n"),
      },
    ],
    metadata: { qwenpaw_model_fallbacks: events },
  };
}
