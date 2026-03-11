import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, { type ChatSpec, type Message } from "../../../api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const DEFAULT_SESSION_NAME = "New Chat";
const ROLE_TOOL = "tool";
const ROLE_USER = "user";
const ROLE_ASSISTANT = "assistant";
const TYPE_PLUGIN_CALL_OUTPUT = "plugin_call_output";
// const CARD_REQUEST = "AgentScopeRuntimeRequestCard";
const CARD_RESPONSE = "AgentScopeRuntimeResponseCard";

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

/**
 * Convert message content to UI content format.
 * Preserves all content blocks (text, images, etc.) in original order.
 */
function convertContentToUIFormat(content: unknown): ContentItem[] {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content || ""), status: "created" }];
  }
  return (content as ContentItem[]).map((item) => {
    if (item.type === "text") {
      return { ...item, status: "created" };
    }
    if (item.type === "image") {
      // Handle image blocks - extract URL from various formats
      let imageUrl = "";
      // image_url can be string or object { url: "..." }
      const imgUrlField = item.image_url as string | { url?: string };
      if (typeof imgUrlField === "string") {
        imageUrl = imgUrlField;
      } else if (imgUrlField?.url) {
        imageUrl = imgUrlField.url;
      }
      // Handle source field
      if (!imageUrl && item.source) {
        const source = item.source as {
          type?: string;
          url?: string;
          media_type?: string;
          data?: string;
        };
        if (source.type === "url" && source.url) {
          imageUrl = source.url;
        } else if (source.type === "base64" && source.data) {
          // Convert base64 source to data URL for display
          const mediaType = source.media_type || "image/png";
          imageUrl = `data:${mediaType};base64,${source.data}`;
        }
      }
      return {
        type: "image",
        image_url: imageUrl || "",
        status: "created",
      };
    }
    // Preserve other block types as-is
    return { ...item, status: "created" };
  });
}

/**
 * Convert a backend message to a response output message.
 * Maps system + plugin_call_output → role "tool" and strips metadata.
 */
const toOutputMessage = (msg: Message): OutputMessage => ({
  ...msg,
  role:
    msg.type === TYPE_PLUGIN_CALL_OUTPUT && msg.role === "system"
      ? ROLE_TOOL
      : msg.role,
  metadata: null,
});

/** Build a user card (AgentScopeRuntimeRequestCard) from a user message. */
function buildUserCard(msg: Message): IAgentScopeRuntimeWebUIMessage {
  const content = convertContentToUIFormat(msg.content);
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
              content,
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
const buildResponseCard = (
  outputMessages: OutputMessage[],
): IAgentScopeRuntimeWebUIMessage => {
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );
  return {
    id: generateId(),
    role: ROLE_ASSISTANT,
    cards: [
      {
        code: CARD_RESPONSE,
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
};

/**
 * Convert flat backend messages into the card-based format expected by
 * the @agentscope-ai/chat component.
 *
 * - User messages → AgentScopeRuntimeRequestCard
 * - Consecutive non-user messages (assistant / system / tool) → grouped
 *   into a single AgentScopeRuntimeResponseCard with all output messages.
 */
const convertMessages = (
  messages: Message[],
): IAgentScopeRuntimeWebUIMessage[] => {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let i = 0;

  while (i < messages.length) {
    if (messages[i].role === ROLE_USER) {
      result.push(buildUserCard(messages[i++]));
    } else {
      const outputMsgs: OutputMessage[] = [];
      while (i < messages.length && messages[i].role !== ROLE_USER) {
        outputMsgs.push(toOutputMessage(messages[i++]));
      }
      if (outputMsgs.length) result.push(buildResponseCard(outputMsgs));
    }
  }

  return result;
};

const chatSpecToSession = (chat: ChatSpec): ExtendedSession =>
  ({
    id: chat.id,
    name: (chat as ChatSpec & { name?: string }).name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
  }) as ExtendedSession;

/** Returns true when id is a pure numeric local timestamp (not a backend UUID). */
const isLocalTimestamp = (id: string): boolean => /^\d+$/.test(id);

/**
 * Resolve and persist the real backend UUID for a local timestamp session.
 * Stores the real UUID as realId while keeping the timestamp as id, so the
 * library's internal currentSessionId (timestamp) remains valid.
 * Returns the resolved real UUID, or null if not found.
 */
const resolveRealId = (
  sessionList: IAgentScopeRuntimeWebUISession[],
  tempSessionId: string,
): { list: IAgentScopeRuntimeWebUISession[]; realId: string | null } => {
  const realSession = sessionList.find(
    (s) => (s as ExtendedSession).sessionId === tempSessionId,
  );
  if (!realSession) return { list: sessionList, realId: null };

  const realUUID = realSession.id;
  // Keep the timestamp as id (so the library's currentSessionId still matches),
  // and store the real UUID in realId for backend requests.
  (realSession as ExtendedSession).realId = realUUID;
  realSession.id = tempSessionId;
  return {
    list: [realSession, ...sessionList.filter((s) => s !== realSession)],
    realId: realUUID,
  };
};

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

  /**
   * Deduplicates concurrent getSession calls for the same sessionId.
   * Key: sessionId, Value: in-flight promise for getSession.
   */
  private sessionRequests: Map<
    string,
    Promise<IAgentScopeRuntimeWebUISession>
  > = new Map();

  /**
   * Called when a temporary timestamp session id is resolved to a real backend
   * UUID. Consumers (e.g. Chat/index.tsx) can register here to update the URL.
   */
  onSessionIdResolved: ((tempId: string, realId: string) => void) | null = null;

  /**
   * Called after a session is removed. Consumers can register here to clear
   * the session id from the URL.
   */
  onSessionRemoved: ((removedId: string) => void) | null = null;

  private createEmptySession(sessionId: string): ExtendedSession {
    window.currentSessionId = sessionId;
    window.currentUserId = DEFAULT_USER_ID;
    window.currentChannel = DEFAULT_CHANNEL;
    return {
      id: sessionId,
      name: DEFAULT_SESSION_NAME,
      sessionId,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    } as ExtendedSession;
  }

  private updateWindowVariables(session: ExtendedSession): void {
    window.currentSessionId = session.sessionId || "";
    window.currentUserId = session.userId || DEFAULT_USER_ID;
    window.currentChannel = session.channel || DEFAULT_CHANNEL;
  }

  private getLocalSession(sessionId: string): IAgentScopeRuntimeWebUISession {
    const local = this.sessionList.find((s) => s.id === sessionId);
    if (local) {
      this.updateWindowVariables(local as ExtendedSession);
      return local;
    }
    return this.createEmptySession(sessionId);
  }

  /**
   * Returns the real backend UUID for a session identified by id (which may be
   * a local timestamp). Returns null when not yet resolved or not found.
   */
  getRealIdForSession(sessionId: string): string | null {
    const s = this.sessionList.find((x) => x.id === sessionId) as
      | ExtendedSession
      | undefined;
    return s?.realId ?? null;
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
    // Deduplicate: reuse the in-flight request if one is already running
    // for the same sessionId so concurrent calls share one network request.
    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) return existingRequest;

    const requestPromise = this._doGetSession(sessionId);
    this.sessionRequests.set(sessionId, requestPromise);

    try {
      return await requestPromise;
    } finally {
      this.sessionRequests.delete(sessionId);
    }
  }

  private async _doGetSession(
    sessionId: string,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    // --- Local timestamp ID (New Chat before first reply) ---
    if (isLocalTimestamp(sessionId)) {
      const fromList = this.sessionList.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;

      // If realId is already resolved, use it directly to fetch history.
      if (fromList?.realId) {
        const chatHistory = await api.getChat(fromList.realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: fromList.name || DEFAULT_SESSION_NAME,
          sessionId: fromList.sessionId || sessionId,
          userId: fromList.userId || DEFAULT_USER_ID,
          channel: fromList.channel || DEFAULT_CHANNEL,
          messages: convertMessages(chatHistory.messages || []),
          meta: fromList.meta || {},
          realId: fromList.realId,
        };
        this.updateWindowVariables(session);
        return session;
      }

      // Pure local session (not yet sent to backend): wait until updateSession
      // resolves the realId, then fetch history with the real UUID.
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

      const refreshed = this.sessionList.find((s) => s.id === sessionId) as
        | ExtendedSession
        | undefined;
      if (refreshed?.realId) {
        const chatHistory = await api.getChat(refreshed.realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: refreshed.name || DEFAULT_SESSION_NAME,
          sessionId: refreshed.sessionId || sessionId,
          userId: refreshed.userId || DEFAULT_USER_ID,
          channel: refreshed.channel || DEFAULT_CHANNEL,
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
      userId: fromList?.userId || DEFAULT_USER_ID,
      channel: fromList?.channel || DEFAULT_CHANNEL,
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
          const { list, realId } = resolveRealId(this.sessionList, tempId);
          this.sessionList = list;
          if (realId) {
            this.onSessionIdResolved?.(tempId, realId);
          }
        });
      }
    } else {
      // Session not found locally — refresh and resolve via session_id
      const tempId = session.id!;
      await this.getSessionList().then(() => {
        const { list, realId } = resolveRealId(this.sessionList, tempId);
        this.sessionList = list;
        if (realId) {
          this.onSessionIdResolved?.(tempId, realId);
        }
      });
    }

    return [...this.sessionList];
  }

  async createSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.id = Date.now().toString();

    const extended: ExtendedSession = {
      ...session,
      sessionId: session.id,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
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

    // Notify consumers (e.g. to clear the URL) with both the list id and the
    // real backend UUID so callers can match either form.
    const resolvedId = existing?.realId ?? sessionId;
    this.onSessionRemoved?.(resolvedId);

    return [...this.sessionList];
  }
}

export default new SessionApi();
