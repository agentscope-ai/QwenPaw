import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";
import { extractClientMessageId } from "../../utils/clientMessageId";

type Bubble = IAgentScopeRuntimeWebUIMessage;

function userReceipt(bubble: Bubble): string | undefined {
  if (bubble.role !== "user") return;
  const card = bubble.cards?.find(
    ({ code }) => code === "AgentScopeRuntimeRequestCard",
  );
  return extractClientMessageId(card?.data?.input?.[0]?.metadata);
}

/** Keep the SDK's visible bubble IDs when a live turn becomes history. */
export function preserveLiveBubbleIds(
  previous: Bubble[],
  history: Bubble[],
): Bubble[] {
  const historyIds = new Set<string>();
  const userByReceipt = new Map<string, number>();
  history.forEach((bubble, index) => {
    historyIds.add(bubble.id);
    const receipt = userReceipt(bubble);
    // A stored user message can contain multiple bubbles; its reply follows
    // the last one. Keep their existing canonical IDs when already present.
    if (receipt) userByReceipt.set(receipt, index);
  });

  const replacements = new Map<number, string>();
  previous.forEach((bubble, index) => {
    const receipt = userReceipt(bubble);
    const savedIndex = receipt ? userByReceipt.get(receipt) : undefined;
    if (savedIndex === undefined) return;
    if (!historyIds.has(bubble.id)) replacements.set(savedIndex, bubble.id);

    const reply = previous[index + 1];
    if (
      reply?.role === "assistant" &&
      history[savedIndex + 1]?.role === "assistant" &&
      !historyIds.has(reply.id)
    ) {
      replacements.set(savedIndex + 1, reply.id);
    }
  });

  return history.map((bubble, index) => {
    const id = replacements.get(index);
    return id ? { ...bubble, id } : bubble;
  });
}
