import { createContext } from "react";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat";
import { setTextareaValue } from "./utils";
import { hasTruncatedModelOutput } from "./completionNotice";

export interface FollowupSource {
  agentId: string;
  chatId: string;
  responseCardId: string;
  responseId: string;
  messageId: string;
  contentIndex: number;
  sourceText: string;
}

export interface FollowupContextValue {
  agentId: string;
  chatId: string;
  blocked: boolean;
  invalidatedResponseId?: string;
  addFollowup(source: FollowupSource, prompt: string): boolean;
}

export const FollowupContext = createContext<FollowupContextValue | null>(null);

export const FollowupPlacementContext = createContext<
  HTMLDivElement | null | undefined
>(undefined);

/** A final media-only answer must not revive an earlier text suggestion. */
export function getFollowupText(response: IAgentScopeRuntimeResponse) {
  if (
    response.status !== "completed" ||
    response.error ||
    hasTruncatedModelOutput(response)
  )
    return;
  const message = [...response.output]
    .reverse()
    .find((item) => item.role === "assistant" && item.type === "message");
  if (!message) return;
  for (let index = message.content.length - 1; index >= 0; index--) {
    const item = message.content[index];
    if (item.type === "text" && item.text.trim()) {
      return {
        messageId: message.id,
        contentIndex: index,
        sourceText: item.text,
      };
    }
  }
}

export interface FollowupDraftState {
  agentId: string;
  chatId: string;
  blocked: boolean;
  invalidatedResponseId?: string;
  inputBusy: boolean;
  textarea: HTMLTextAreaElement | null;
  messages: Array<{
    id: string;
    role?: string;
    cards?: Array<{ code: string; data?: unknown }>;
  }>;
}

/** Recheck the live SDK snapshot immediately before touching the draft. */
export function addFollowupToDraft(
  source: FollowupSource,
  prompt: string,
  state: FollowupDraftState,
): boolean {
  const textarea = state.textarea;
  if (
    state.blocked ||
    state.inputBusy ||
    state.invalidatedResponseId === source.responseId ||
    state.agentId !== source.agentId ||
    state.chatId !== source.chatId ||
    !textarea?.isConnected ||
    textarea.disabled ||
    textarea.readOnly ||
    !prompt.trim() ||
    [...prompt].length > 100
  )
    return false;
  const latest = state.messages[state.messages.length - 1];
  if (latest?.id !== source.responseCardId || latest.role !== "assistant")
    return false;
  const response = latest.cards?.find(
    (card) => card.code === "AgentScopeRuntimeResponseCard",
  )?.data as IAgentScopeRuntimeResponse | undefined;
  if (!response || response.id !== source.responseId) return false;
  const text = getFollowupText(response);
  if (
    !text ||
    text.messageId !== source.messageId ||
    text.contentIndex !== source.contentIndex ||
    text.sourceText !== source.sourceText
  )
    return false;
  const draft = textarea.value;
  const separator =
    !draft || draft.endsWith("\n\n")
      ? ""
      : draft.endsWith("\n")
      ? "\n"
      : "\n\n";
  setTextareaValue(textarea, draft + separator + prompt);
  textarea.focus();
  return true;
}
