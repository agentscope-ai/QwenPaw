import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";
import type { HistoryUserMessage } from "./historyMessageWindowStore";

export function activeUserAtScrollPosition(
  users: Array<{ id: string; top: number }>,
  visibleTop: number,
  atBottom: boolean,
): string | undefined {
  const ordered = [...users].sort((left, right) => left.top - right.top);
  if (atBottom) return ordered[ordered.length - 1]?.id;
  return (
    [...ordered].reverse().find((item) => item.top <= visibleTop)?.id ??
    ordered[0]?.id
  );
}

export function getNavigationUsers(
  messages: IAgentScopeRuntimeWebUIMessage[],
): HistoryUserMessage[] {
  return messages
    .filter((item) => item.role === "user")
    .map((item) => {
      const request = item.cards?.find(
        (card) => card.code === "AgentScopeRuntimeRequestCard",
      )?.data as
        | {
            created_at?: number;
            input?: Array<{
              metadata?: { qwenpaw_client_message_id?: string };
              content?: Array<{ text?: string; filename?: string }>;
            }>;
          }
        | undefined;
      const timestamp = request?.created_at;
      return {
        messageId: item.id,
        clientMessageId:
          request?.input?.[0]?.metadata?.qwenpaw_client_message_id,
        preview: (request?.input ?? [])
          .flatMap((input) => input.content ?? [])
          .map((content) => content.text || content.filename || "")
          .join(" ")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 160),
        createdAt: timestamp
          ? new Date(
              timestamp < 1e10 ? timestamp * 1000 : timestamp,
            ).toISOString()
          : "",
        anchor: "",
      };
    });
}

// Persisted IDs and optimistic SDK IDs can differ for the same user input.
export function mergeNavigationUsers(
  persisted: HistoryUserMessage[],
  visible: HistoryUserMessage[],
): HistoryUserMessage[] {
  const result = [...persisted];
  const identities = new Set(
    persisted
      .flatMap((item) => [item.messageId, item.clientMessageId])
      .filter(Boolean),
  );
  for (const item of visible) {
    if (
      identities.has(item.messageId) ||
      (item.clientMessageId && identities.has(item.clientMessageId))
    )
      continue;
    result.push(item);
    identities.add(item.messageId);
    if (item.clientMessageId) identities.add(item.clientMessageId);
  }
  return result;
}
