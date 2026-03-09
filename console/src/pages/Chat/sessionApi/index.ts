import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, { type ChatSpec, type Message } from "../../../api";

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
}

// ---------------------------------------------------------------------------
// Message conversion: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Extract plain text from a message's content array.
 */
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
 * - Maps system + plugin_call_output → role "tool"
 * - Strips metadata (not used in card rendering)
 */
function toOutputMessage(msg: Message): OutputMessage {
  let role = msg.role;
  if (msg.type === "plugin_call_output" && role === "system") {
    role = "tool";
  }
  return {
    ...msg,
    role,
    metadata: null,
  };
}

/**
 * Build a user card (AgentScopeRuntimeRequestCard) from a user message.
 */
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
    (max: number, m: OutputMessage) => Math.max(max, m.sequence_number || 0),
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
 *   into a single AgentScopeRuntimeResponseCard with all messages in
 *   the `output` array, supporting plugin_call & plugin_call_output.
 */
function convertMessages(
  messages: Message[],
): IAgentScopeRuntimeWebUIMessage[] {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let i = 0;

  while (i < messages.length) {
    const msg = messages[i];

    if (msg.role === "user") {
      result.push(buildUserCard(msg));
      i++;
    } else {
      // Group consecutive non-user messages into one response card
      const outputMsgs: OutputMessage[] = [];
      while (i < messages.length && messages[i].role !== "user") {
        outputMsgs.push(toOutputMessage(messages[i]));
        i++;
      }
      if (outputMsgs.length > 0) {
        result.push(buildResponseCard(outputMsgs));
      }
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

class SessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private lsKey: string;
  private currentSessionKey: string;
  private sessionList: IAgentScopeRuntimeWebUISession[];
  private fetchPromise: Promise<IAgentScopeRuntimeWebUISession[]> | null = null;
  private lastFetchTime: number = 0;
  private cacheTimeout: number = 5000;

  private sessionCache: Map<
    string,
    { session: IAgentScopeRuntimeWebUISession; timestamp: number }
  > = new Map();
  private sessionFetchPromises: Map<
    string,
    Promise<IAgentScopeRuntimeWebUISession>
  > = new Map();
  private sessionCacheTimeout: number = 5000;

  constructor() {
    this.lsKey = "agent-scope-runtime-webui-sessions";
    this.currentSessionKey = "agent-scope-current-session-id";
    this.sessionList = [];
  }

  // Persist current session ID to LocalStorage with error handling
  private saveCurrentSessionId(sessionId: string): void {
    try {
      localStorage.setItem(this.currentSessionKey, sessionId);
    } catch (e) {
      // Silent fail in private mode or quota exceeded
      console.warn("Failed to save session ID to localStorage:", e);
    }
  }

  // Retrieve persisted session ID with error handling
  private getCurrentSessionId(): string | null {
    try {
      return localStorage.getItem(this.currentSessionKey);
    } catch (e) {
      // Silent fail in private mode
      console.warn("Failed to read session ID from localStorage:", e);
      return null;
    }
  }

  private createEmptySession(sessionId: string): ExtendedSession {
    window.currentSessionId = sessionId;
    window.currentUserId = "default";
    window.currentChannel = "console";

    return {
      id: sessionId,
      name: "New Chat",
      sessionId: sessionId,
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
    const localSession = this.sessionList.find((s) => s.id === sessionId);
    if (localSession) {
      this.updateWindowVariables(localSession as ExtendedSession);
      // Update persisted session ID when switching sessions
      this.saveCurrentSessionId(sessionId);
      return localSession;
    }
    return this.createEmptySession(sessionId);
  }

  async getSessionList() {
    if (this.fetchPromise) {
      return this.fetchPromise;
    }

    const now = Date.now();
    if (
      this.sessionList.length > 0 &&
      now - this.lastFetchTime < this.cacheTimeout
    ) {
      return [...this.sessionList];
    }

    this.fetchPromise = this.fetchSessionListFromBackend();

    try {
      const result = await this.fetchPromise;
      return result;
    } finally {
      this.fetchPromise = null;
    }
  }

  private async fetchSessionListFromBackend(): Promise<
    IAgentScopeRuntimeWebUISession[]
  > {
    try {
      const chats = await api.listChats();
      const validChats = chats.filter(
        (chat) => chat.id && chat.id !== "undefined" && chat.id !== "null",
      );
      this.sessionList = validChats.map(chatSpecToSession).reverse();
      localStorage.setItem(this.lsKey, JSON.stringify(this.sessionList));
      this.lastFetchTime = Date.now();
      return [...this.sessionList];
    } catch (error) {
      this.sessionList = JSON.parse(localStorage.getItem(this.lsKey) || "[]");
      return [...this.sessionList];
    }
  }

  async getSession(sessionId: string) {
    try {
      // If no valid sessionId provided, try to restore from LocalStorage
      if (!sessionId || sessionId === "undefined" || sessionId === "null") {
        const persistedId = this.getCurrentSessionId();
        if (persistedId) {
          // Try to find session in local list
          const persistedSession = this.sessionList.find(
            (s) => s.id === persistedId,
          );
          if (persistedSession) {
            this.updateWindowVariables(persistedSession as ExtendedSession);
            return persistedSession;
          }
          // Session not in local list - check if it's a local timestamp ID
          if (/^\d+$/.test(persistedId)) {
            return this.getLocalSession(persistedId);
          }
          // Otherwise try to fetch from backend
          sessionId = persistedId;
        } else {
          return this.createEmptySession(`temp-${Date.now()}`);
        }
      }

      const isLocalTimestampId = /^\d+$/.test(sessionId);

      if (isLocalTimestampId) {
        return this.getLocalSession(sessionId);
      }

      const cached = this.sessionCache.get(sessionId);
      const now = Date.now();

      if (cached && now - cached.timestamp < this.sessionCacheTimeout) {
        this.updateWindowVariables(cached.session as ExtendedSession);
        return cached.session;
      }

      const existingPromise = this.sessionFetchPromises.get(sessionId);
      if (existingPromise) {
        return existingPromise;
      }

      const fetchPromise = this.fetchSessionFromBackend(sessionId);
      this.sessionFetchPromises.set(sessionId, fetchPromise);

      try {
        const result = await fetchPromise;
        return result;
      } finally {
        this.sessionFetchPromises.delete(sessionId);
      }
    } catch (error) {
      const fallbackSession = this.sessionList.find(
        (session) => session.id === sessionId,
      );
      if (fallbackSession) {
        return fallbackSession;
      }
      return this.createEmptySession(sessionId);
    }
  }

  private async fetchSessionFromBackend(
    sessionId: string,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    const chatHistory = await api.getChat(sessionId);

    const chatSpec = this.sessionList.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    const session = {
      id: sessionId,
      name: chatSpec?.name || sessionId,
      sessionId: chatSpec?.sessionId || sessionId,
      userId: chatSpec?.userId || "default",
      channel: chatSpec?.channel || "console",
      messages: convertMessages(chatHistory.messages || []),
      meta: chatSpec?.meta || {},
    } as ExtendedSession;

    this.updateWindowVariables(session);

    this.sessionCache.set(sessionId, {
      session,
      timestamp: Date.now(),
    });

    return session;
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.messages = [];
    const index = this.sessionList.findIndex((item) => item.id === session.id);
    if (index > -1) {
      this.sessionList[index] = {
        ...this.sessionList[index],
        ...session,
      };
      localStorage.setItem(this.lsKey, JSON.stringify(this.sessionList));
    }

    // Persist current session ID
    if (session.id) {
      this.saveCurrentSessionId(session.id);
    }

    return [...this.sessionList];
  }

  async createSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.id = Date.now().toString();

    const extendedSession = {
      ...session,
      sessionId: session.id,
      userId: "default",
      channel: "console",
    } as ExtendedSession;

    this.updateWindowVariables(extendedSession);

    // Persist current session ID
    this.saveCurrentSessionId(session.id!);

    this.sessionList.unshift(extendedSession as IAgentScopeRuntimeWebUISession);
    localStorage.setItem(this.lsKey, JSON.stringify(this.sessionList));
    this.lastFetchTime = Date.now();
    return [...this.sessionList];
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    try {
      if (!session.id) {
        return [...this.sessionList];
      }

      const sessionId = session.id;

      await api.deleteChat(sessionId);

      this.sessionList = this.sessionList.filter(
        (item) => item.id !== sessionId,
      );

      localStorage.setItem(this.lsKey, JSON.stringify(this.sessionList));
      this.lastFetchTime = Date.now();
      return [...this.sessionList];
    } catch (error) {
      if (session.id) {
        this.sessionList = this.sessionList.filter(
          (item) => item.id !== session.id,
        );
        localStorage.setItem(this.lsKey, JSON.stringify(this.sessionList));
        this.lastFetchTime = Date.now();
      }
      return [...this.sessionList];
    }
  }
}

export default new SessionApi();
