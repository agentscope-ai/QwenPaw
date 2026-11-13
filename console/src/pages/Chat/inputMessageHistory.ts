import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";
import {
  HISTORY_MESSAGE_WINDOW_CARD,
  type HistoryWindowSnapshot,
} from "./historyMessageWindowStore";
import { extractTextFromMessage } from "./utils";

/** Read full input text, never the truncated navigation index preview. */
export function getInputHistoryTexts(
  messages: IAgentScopeRuntimeWebUIMessage[],
  history: HistoryWindowSnapshot | null,
): string[] {
  const seen = new Set<string>();
  const texts: string[] = [];
  for (const message of messages) {
    const card = message.cards?.find(
      (item) => item.code === HISTORY_MESSAGE_WINDOW_CARD,
    );
    const rows = card
      ? history && card.data?.sessionId === history.sessionId
        ? history.turnRows.flat()
        : []
      : [message];
    for (const row of rows) {
      if (row.role !== "user" || seen.has(row.id)) continue;
      seen.add(row.id);
      const text = extractTextFromMessage(row);
      if (text.trim()) texts.push(text);
    }
  }
  return texts;
}
