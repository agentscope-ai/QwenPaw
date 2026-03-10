import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, { type ChatSpec, type Message } from "../../../api";

// ---------------------------------------------------------------------------
// Window globals
// ---------------------------------------------------------------------------

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

// ---------------------------------------------------------------------------
// Local helper types
// ---------------------------------------------------------------------------

/** A single item inside a message's content array. */
interface ContentItem {
  type: string;
  text?: string;
  [key: string]: unknown;
}

/** A backend message after role-normalisation (output of toOutputMessage). */
interface OutputMessage extends Omit<Message, "role"> {
  role: string;
  metadata: null;
  sequence_number?: number;
}

/**
 * Extended session carrying extra fields that the library type does not define
 * but our backend / window globals require.
 */
interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  sessionId: string;
  userId: string;
  channel: string;
  meta: Record<string, unknown>;
  /** Real backend UUID, used when id is overridden with a local timestamp. */
  realId?: string;
}

// ---------------------------------------------------------------------------
// Message conversion helpers: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/** Extract plain text from a message's content array. */
function extractTextFromContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return String(content || "");
  return (content as ContentItem[])
    .filter((c) => c.type === "text")
    .map((c) => c.text || "")
    .filter(Boolean)
    .join("\n");
}

/**
 * Convert a backend message to a response output message.
 * Maps system + plugin_call_output → role "tool" and strips metadata.
 */
function toOutputMessage(msg: Message): OutputMessage {
  const role =
    msg.type === "plugin_call_output" && msg.role === "system"
      ? "tool"
      : msg.role;
  return { ...msg, role, metadata: null };
}

/** Build a user card (AgentScopeRuntimeRequestCard) from a user message. */
function buildUserCard(msg: Message): IAgentScopeRuntimeWebUIMessage {
  const text = extractTextFromContent(msg.content);
  return {
    id: (msg.id as string) || generateId(),
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          input: [
            {
              role: "user",
              type: "message",
              content: [{ type: "text", text, status: "created" }],
            },
          ],
        },
      },
    ],
  };
}

/**
 * Build an assistant response card (AgentScopeRuntimeResponseCard)
 * wrapping a group of consecutive non-user output messages.
 */
function buildResponseCard(
  outputMessages: OutputMessage[],
): IAgentScopeRuntimeWebUIMessage {
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );
  return {
    id: generateId(),
    role: "assistant",
    cards: [
      {
        code: "AgentScopeRuntimeResponseCard",
        data: {
          id: `response_${generateId()}`,
          output: outputMessages,
          object: "response",
          status: "completed",
          created_at: now,
          sequence_number: maxSeq + 1,
          error: null,
          completed_at: now,
          usage: null,
        },
      },
    ],
    msgStatus: "finished",
  };
}

/**
 * Convert flat backend messages into the card-based format expected by
 * the @agentscope-ai/chat component.
 *
 * - User messages → AgentScopeRuntimeRequestCard
 * - Consecutive non-user messages (assistant / system / tool) → grouped
 *   into a single AgentScopeRuntimeResponseCard with all output messages.
 */
function convertMessages(
  messages: Message[],
): IAgentScopeRuntimeWebUIMessage[] {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let i = 0;

  while (i < messages.length) {
    if (messages[i].role === "user") {
      result.push(buildUserCard(messages[i++]));
    } else {
      const outputMsgs: OutputMessage[] = [];
      while (i < messages.length && messages[i].role !== "user") {
        outputMsgs.push(toOutputMessage(messages[i++]));
      }
      if (outputMsgs.length > 0) result.push(buildResponseCard(outputMsgs));
    }
  }

  return result;
}

function chatSpecToSession(chat: ChatSpec): ExtendedSession {
  return {
    id: chat.id,
    name: (chat as ChatSpec & { name?: string }).name || "New Chat",
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
  } as ExtendedSession;
}

/** Returns true when id is a pure numeric local timestamp (not a backend UUID). */
function isLocalTimestamp(id: string): boolean {
  return /^\d+$/.test(id);
}

/**
 * Resolve and persist the real backend UUID for a local timestamp session.
 * Searches the refreshed session list for a backend record whose session_id
 * matches the timestamp, then stores realId and keeps the timestamp as id.
 */
function resolveRealId(
  sessionList: IAgentScopeRuntimeWebUISession[],
  tempSessionId: string,
): IAgentScopeRuntimeWebUISession[] {
  const realSession = sessionList.find(
    (s) => (s as ExtendedSession).sessionId === tempSessionId,
  );
  if (!realSession) return sessionList;

  (realSession as ExtendedSession).realId = realSession.id;
  realSession.id = tempSessionId;
  return [realSession, ...sessionList.filter((s) => s !== realSession)];
}

// ---------------------------------------------------------------------------
// SessionApi
// ---------------------------------------------------------------------------

class SessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private sessionList: IAgentScopeRuntimeWebUISession[] = [];

  /**
   * Deduplicates concurrent getSessionList calls so that two parallel
   * invocations share one network request and write sessionList only once,
   * preserving any realId mappings that were already resolved.
   */
  private sessionListRequest: Promise<IAgentScopeRuntimeWebUISession[]> | null =
    null;

  constructor() {}

  private createEmptySession(sessionId: string): ExtendedSession {
    window.currentSessionId = sessionId;
    window.currentUserId = "default";
    window.currentChannel = "console";
    return {
      id: sessionId,
      name: "New Chat",
      sessionId,
      userId: "default",
      channel: "console",
      messages: [],
      meta: {},
    } as ExtendedSession;
  }

  private updateWindowVariables(session: ExtendedSession): void {
    window.currentSessionId = session.sessionId || "";
    window.currentUserId = session.userId || "default";
    window.currentChannel = session.channel || "console";
  }

  private getLocalSession(sessionId: string): IAgentScopeRuntimeWebUISession {
    const local = this.sessionList.find((s) => s.id === sessionId);
    if (local) {
      this.updateWindowVariables(local as ExtendedSession);
      return local;
    }
    return this.createEmptySession(sessionId);
  }

  async getSessionList() {
    // Deduplicate: reuse the in-flight request if one is already running so
    // concurrent calls don't overwrite sessionList and lose realId mappings.
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        const chats = await api.listChats();
        const newList = chats
          .filter((c) => c.id && c.id !== "undefined" && c.id !== "null")
          .map(chatSpecToSession)
          .reverse();

        // Merge: preserve realId mappings (timestamp → UUID) stored in memory
        this.sessionList = newList.map((s) => {
          const existing = this.sessionList.find(
            (e) =>
              (e as ExtendedSession).sessionId ===
              (s as ExtendedSession).sessionId,
          ) as ExtendedSession | undefined;
          return existing?.realId
            ? { ...s, id: existing.id, realId: existing.realId }
            : s;
        });

        return [...this.sessionList];
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  async getSession(sessionId: string) {
    // --- Local timestamp ID (New Chat / post-delete) ---
    if (isLocalTimestamp(sessionId)) {
      const fromList = this.sessionList.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;
      const { realId } = fromList ?? {};

      if (realId) {
        // Already has a backend record — fetch full history
        const chatHistory = await api.getChat(realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: fromList?.name || "New Chat",
          sessionId: fromList?.sessionId || sessionId,
          userId: fromList?.userId || "default",
          channel: fromList?.channel || "console",
          messages: convertMessages(chatHistory.messages || []),
          meta: fromList?.meta || {},
          realId,
        };
        this.updateWindowVariables(session);
        return session;
      }

      // Pure local session: block until this session gets a realId, meaning
      // updateSession has resolved the backend UUID. At that point the
      // streaming response is done, realId is set, and we can safely fetch
      // the full history without racing against setMessages([]).
      await new Promise<void>((resolve) => {
        const check = () => {
          const s = this.sessionList.find((x) => x.id === sessionId) as
            | ExtendedSession
            | undefined;
          if (s?.realId) {
            resolve();
          } else {
            setTimeout(check, 100);
          }
        };
        setTimeout(check, 100);
      });

      // Re-read after realId is available and fall through to the realId branch
      const refreshed = this.sessionList.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;
      if (refreshed?.realId) {
        const chatHistory = await api.getChat(refreshed.realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: refreshed.name || "New Chat",
          sessionId: refreshed.sessionId || sessionId,
          userId: refreshed.userId || "default",
          channel: refreshed.channel || "console",
          messages: convertMessages(chatHistory.messages || []),
          meta: refreshed.meta || {},
          realId: refreshed.realId,
        };
        this.updateWindowVariables(session);
        return session;
      }

      return this.getLocalSession(sessionId);
    }

    // --- No session selected (e.g. after delete) ---
    // Return a transient empty session; it is NOT added to sessionList so it
    // never appears as a list item. The component will call createSession on
    // the next submit via ensureSession.
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return this.createEmptySession(Date.now().toString());
    }

    // --- Regular backend UUID ---
    const fromList = this.sessionList.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    const chatHistory = await api.getChat(sessionId);
    const session: ExtendedSession = {
      id: sessionId,
      name: fromList?.name || sessionId,
      sessionId: fromList?.sessionId || sessionId,
      userId: fromList?.userId || "default",
      channel: fromList?.channel || "console",
      messages: convertMessages(chatHistory.messages || []),
      meta: fromList?.meta || {},
    };

    this.updateWindowVariables(session);
    return session;
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.messages = [];
    const index = this.sessionList.findIndex((s) => s.id === session.id);

    if (index > -1) {
      this.sessionList[index] = { ...this.sessionList[index], ...session };

      // Timestamp session without realId yet — resolve in the background
      const existing = this.sessionList[index] as ExtendedSession;
      if (isLocalTimestamp(existing.id) && !existing.realId) {
        const tempId = existing.id;
        this.getSessionList().then(() => {
          this.sessionList = resolveRealId(this.sessionList, tempId);
        });
      }
    } else {
      // Session not found locally — refresh and resolve via session_id
      const tempId = session.id!;
      await this.getSessionList().then(() => {
        this.sessionList = resolveRealId(this.sessionList, tempId);
      });
    }

    return [...this.sessionList];
  }

  async createSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.id = Date.now().toString();

    const extended: ExtendedSession = {
      ...session,
      sessionId: session.id,
      userId: "default",
      channel: "console",
    } as ExtendedSession;

    this.updateWindowVariables(extended);
    this.sessionList.unshift(extended);
    return [...this.sessionList];
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this.sessionList];

    const { id: sessionId } = session;
    const existing = this.sessionList.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    // Use realId (UUID) when available; skip backend call for pure local sessions
    const deleteId =
      existing?.realId ?? (isLocalTimestamp(sessionId) ? null : sessionId);

    if (deleteId) await api.deleteChat(deleteId);

    this.sessionList = this.sessionList.filter((s) => s.id !== sessionId);

    return [...this.sessionList];
  }
}

export default new SessionApi();
