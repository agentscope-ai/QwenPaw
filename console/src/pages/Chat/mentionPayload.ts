export interface MentionPayloadItem {
  value: string;
  type?: string;
}

export function withMentionPayload<T extends Record<string, unknown>>(
  payload: T,
  mentions?: readonly MentionPayloadItem[],
): T & { mentions?: MentionPayloadItem[] } {
  if (!mentions?.length) return payload;
  return { ...payload, mentions: [...mentions] };
}
