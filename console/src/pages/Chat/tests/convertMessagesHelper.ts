/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Test helper — extracts pure message-conversion logic from sessionApi
 * for isolated testing. This mirrors the internal implementation so tests
 * can verify the conversion contract without instantiating the full
 * SessionApiManager class.
 *
 * If the source implementation changes, this helper must be updated to match.
 */

const ROLE_USER = "user";
const ROLE_ASSISTANT = "assistant";
const ROLE_TOOL = "tool";
const TYPE_PLUGIN_CALL_OUTPUT = "plugin_call_output";
const CARD_RESPONSE = "AgentScopeRuntimeResponseCard";

interface ContentItem {
  type: string;
  text?: string;
  [key: string]: unknown;
}

interface Message {
  id?: string;
  role: string;
  content: unknown;
  type?: string;
  metadata: unknown;
  sequence_number?: number;
}

interface OutputMessage {
  role: string;
  content: unknown;
  metadata: unknown;
  sequence_number?: number;
}

interface UIMessage {
  id: string;
  role: string;
  cards?: Array<{ code: string; data: unknown }>;
  msgStatus?: string;
}

function toOutputMessage(msg: Message): OutputMessage {
  return {
    ...msg,
    role:
      msg.type === TYPE_PLUGIN_CALL_OUTPUT && msg.role === "system"
        ? ROLE_TOOL
        : msg.role,
    metadata: msg.metadata ?? null,
  };
}

function contentToRequestParts(
  content: unknown,
): Array<Record<string, unknown>> {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content || ""), status: "created" }];
  }
  const parts = (content as ContentItem[]).map((c) => ({
    ...c,
    status: "created",
  }));
  if (parts.length === 0) {
    return [{ type: "text", text: "", status: "created" }];
  }
  return parts;
}

function buildUserCard(msg: Message): UIMessage {
  const contentParts = contentToRequestParts(msg.content);
  return {
    id: (msg.id as string) || `user-${Date.now()}`,
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          created_at: 0,
          input: [
            {
              role: "user",
              type: "message",
              content: contentParts,
              metadata: msg.metadata ?? null,
            },
          ],
        },
      },
    ],
  };
}

function buildResponseCard(outputMessages: OutputMessage[]): UIMessage {
  return {
    id: `resp-${Date.now()}`,
    role: ROLE_ASSISTANT,
    cards: [
      {
        code: CARD_RESPONSE,
        data: {
          output: outputMessages,
          object: "response",
          status: "completed",
        },
      },
    ],
    msgStatus: "finished",
  };
}

export function convertMessages(messages: Message[]): UIMessage[] {
  const result: UIMessage[] = [];
  const len = messages.length;
  let i = 0;

  while (i < len) {
    if (messages[i].role === ROLE_USER) {
      result.push(buildUserCard(messages[i++]));
    } else {
      const startIdx = i;
      while (i < len && messages[i].role !== ROLE_USER) i++;
      const outputMsgs = messages.slice(startIdx, i).map(toOutputMessage);
      if (outputMsgs.length) result.push(buildResponseCard(outputMsgs));
    }
  }

  return result;
}

export function isGenerating(chatHistory: { status?: string }): boolean {
  return chatHistory.status === "running";
}
