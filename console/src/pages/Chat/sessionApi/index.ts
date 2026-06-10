import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, {
  type ChatSpec,
  type ChatHistory,
  type ChatStatus,
  type Message,
} from "../../../api";
import {
  toDisplayUrl,
  sessionKeyMatches,
  sessionIdMatchesKey,
  patchLastAssistantUsageNote,
} from "../utils";
import { TOKEN_BADGE_STORAGE_PREFIX } from "../components/TokenUsageBadge";

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
  metadata: unknown;
  sequence_number?: number;
}

/**
 * Extended session carrying extra fields that the library type does not define
 * but our backend / window globals require.
 */
interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  /** Session identifier (channel:user_id format) */
  sessionId: string;
  /** User identifier */
  userId: string;
  /** Channel name */
  channel: string;
  /** Additional metadata */
  meta: Record<string, unknown>;
  /** Real backend UUID, used when id is overridden with a local timestamp. */
  realId?: string;
  /** Conversation status from backend. */
  status?: ChatStatus;
  /** ISO 8601 creation timestamp from backend. */
  createdAt?: string | null;
  /** Whether the backend is still generating a response for this session. */
  generating?: boolean;
  /** Whether the chat is pinned to the top. */
  pinned?: boolean;
}

// ---------------------------------------------------------------------------
// Message conversion helpers: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

/** Parse metadata.timestamp string (e.g. "2026-05-27 10:44:53.362") to unix seconds. */
const parseTimestamp = (msg: Record<string, unknown>): number => {
  const ts = (msg.metadata as Record<string, unknown>)?.timestamp;
  if (!ts || typeof ts !== "string") return 0;
  const ms = new Date(ts.replace(" ", "T")).getTime();
  return Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
};

/** Extract plain text from a message's content array. */
const extractTextFromContent = (content: unknown): string => {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return String(content || "");
  return (content as ContentItem[])
    .filter((c) => c.type === "text")
    .map((c) => c.text || "")
    .filter(Boolean)
    .join("\n");
};

function resolveContentItemUrl(c: ContentItem): ContentItem {
  if (c.type === "image" && c.image_url) {
    return { ...c, image_url: toDisplayUrl(c.image_url as string) };
  }
  if (c.type === "audio" && c.data) {
    return { ...c, data: toDisplayUrl(c.data as string) };
  }
  if (c.type === "video" && c.video_url) {
    return { ...c, video_url: toDisplayUrl(c.video_url as string) };
  }
  if (c.type === "file" && (c.file_url || c.file_id)) {
    return {
      ...c,
      file_url: toDisplayUrl((c.file_url as string) || (c.file_id as string)),
      file_name: (c.filename as string) || (c.file_name as string) || "file",
    };
  }
  return c;
}

/** Map backend message content to request card content (text + image + file). */
function contentToRequestParts(
  content: unknown,
): Array<Record<string, unknown>> {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content || ""), status: "created" }];
  }
  const parts = (content as ContentItem[])
    .map(resolveContentItemUrl)
    .map((c) => ({ ...c, status: "created" }));

  if (parts.length === 0) {
    return [{ type: "text", text: "", status: "created" }];
  }

  return parts;
}
function normalizeOutputMessageContent(content: unknown): unknown {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content;
  return (content as ContentItem[]).map((c) => {
    if (c.type === "file") {
      return {
        ...c,
        file_name: (c.filename as string) || (c.file_name as string) || "file",
      };
    }
    return c;
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
  metadata: msg.metadata ?? null,
});

/** Build a user card (AgentScopeRuntimeRequestCard) from a user message. */
function buildUserCard(msg: Message): IAgentScopeRuntimeWebUIMessage {
  const contentParts = contentToRequestParts(msg.content);
  return {
    id: (msg.id as string) || generateId(),
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          created_at: parseTimestamp(msg),
          input: [
            {
              role: "user",
              type: "message",
              content: contentParts,
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
  const fallbackNow = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );

  const firstTs = parseTimestamp(outputMessages[0]);
  const lastTs = parseTimestamp(outputMessages[outputMessages.length - 1]);

  const normalizedMessages = outputMessages.map((msg) => ({
    ...msg,
    content: normalizeOutputMessageContent(msg.content),
  }));

  return {
    id: generateId(),
    role: ROLE_ASSISTANT,
    cards: [
      {
        code: CARD_RESPONSE,
        data: {
          id: `response_${generateId()}`,
          output: normalizedMessages,
          object: "response",
          status: "completed",
          created_at: firstTs || fallbackNow,
          sequence_number: maxSeq + 1,
          error: null,
          completed_at: lastTs || fallbackNow,
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
    name: chat.name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
    status: chat.status ?? "idle",
    createdAt: chat.created_at ?? null,
    pinned: chat.pinned ?? false,
  }) as ExtendedSession;

/** Returns true when id is a pure numeric local timestamp (not a backend UUID). */
const isLocalTimestamp = (id: string): boolean => /^\d+$/.test(id);

/** Detect if backend is still generating content for this chat.
 *  Only trust the explicit `status` field from the backend.
 *  When status is missing (undefined) treat the chat as idle to avoid
 *  false-positive reconnects that cause infinite loading (issue #4903).
 */
const isGenerating = (chatHistory: ChatHistory): boolean => {
  return chatHistory.status === "running";
};

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
  // 1) Exact match: a session whose id already equals the temp timestamp
  //    (e.g. after applyChatsToSessionList merged it).
  const matchedByDisplayId = sessionList.find((s) => s.id === tempSessionId);
  if (matchedByDisplayId) {
    const ext = matchedByDisplayId as ExtendedSession;
    // Already merged — keep existing realId; never overwrite with id (timestamp).
    if (ext.realId && !isLocalTimestamp(ext.realId)) {
      return { list: sessionList, realId: ext.realId };
    }
  }

  // 2) Fallback: match by sessionId, but only consider sessions that have
  //    NOT yet been resolved (no realId) to avoid stealing another session's
  //    backend UUID — same class of bug as #3843.
  let realSession = sessionList.find((s) => {
    const ext = s as ExtendedSession;
    if (ext.realId) return false;
    return sessionIdMatchesKey(ext.sessionId, tempSessionId);
  });

  if (!realSession) return { list: sessionList, realId: null };

  const realUUID = realSession.id;
  if (isLocalTimestamp(realUUID)) {
    return { list: sessionList, realId: null };
  }

  (realSession as ExtendedSession).realId = realUUID;
  realSession.id = tempSessionId;
  return {
    list: [realSession, ...sessionList.filter((s) => s !== realSession)],
    realId: realUUID,
  };
};

// ---------------------------------------------------------------------------
// Per-session user message persistence (survives page refresh)
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = "qwenpaw_pending_user_msg_";
const STOP_USAGE_NOTE_PREFIX = "qwenpaw_stop_usage_note_";

function savePendingUserMessage(sessionId: string, text: string): void {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${sessionId}`, text);
  } catch {
    /* quota exceeded – ignore */
  }
}

function loadPendingUserMessage(sessionId: string): string {
  try {
    return sessionStorage.getItem(`${STORAGE_PREFIX}${sessionId}`) || "";
  } catch {
    return "";
  }
}

function clearPendingUserMessage(sessionId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${sessionId}`);
  } catch {
    /* ignore */
  }
}

function persistStopUsageNote(
  sessionId: string,
  markdown: string | null,
): void {
  try {
    const key = `${STOP_USAGE_NOTE_PREFIX}${sessionId}`;
    if (!markdown?.trim()) {
      sessionStorage.removeItem(key);
      return;
    }
    sessionStorage.setItem(key, markdown.trim());
  } catch {
    /* quota exceeded – ignore */
  }
}

function loadPendingStopUsageNote(sessionId: string): string {
  try {
    return (
      sessionStorage.getItem(`${STOP_USAGE_NOTE_PREFIX}${sessionId}`) || ""
    );
  } catch {
    return "";
  }
}

/** Drop all per-session sessionStorage entries we own for *ids*. */
function clearSessionStorageForIds(ids: Iterable<string>): void {
  const prefixes = [
    STORAGE_PREFIX,
    STOP_USAGE_NOTE_PREFIX,
    TOKEN_BADGE_STORAGE_PREFIX,
  ];
  try {
    for (const id of ids) {
      if (!id) continue;
      for (const prefix of prefixes)
        sessionStorage.removeItem(`${prefix}${id}`);
    }
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// SessionApi
// ---------------------------------------------------------------------------

class SessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private sessionList: IAgentScopeRuntimeWebUISession[] = [];

  /**
   * Pending resolvers waiting for a specific session's realId.
   * Used to replace setTimeout-based busy-wait with event-driven notification.
   */
  private realIdResolvers: Map<string, Array<() => void>> = new Map();

  /** Notify any pending waiters that a session's realId has been resolved. */
  private notifyRealIdResolved(sessionId: string): void {
    const resolvers = this.realIdResolvers.get(sessionId);
    if (resolvers) {
      this.realIdResolvers.delete(sessionId);
      for (const resolve of resolvers) resolve();
    }
  }

  /** Wait until a session's realId is available (set by updateSession). */
  private waitForRealId(sessionId: string): Promise<void> {
    if (this.resolveBackendChatId(sessionId)) return Promise.resolve();

    return new Promise<void>((resolve) => {
      const existing = this.realIdResolvers.get(sessionId) || [];
      existing.push(resolve);
      this.realIdResolvers.set(sessionId, existing);
    });
  }

  /**
   * When set, getSessionList will move the matching session to the front on the first call,
   * so the library's useMount auto-selects it instead of always defaulting to sessions[0].
   * Cleared after first use.
   */
  preferredChatId: string | null = null;

  // ---------------------------------------------------------------------------
  // Session switch lock (issue #4557)
  // Prevents rapid session switching from causing infinite loops by blocking
  // all clicks until the current switch completes (data loaded + URL updated).
  // ---------------------------------------------------------------------------

  /** Whether a session switch is currently in progress. */
  isSessionSwitching = false;

  /** Short-lived result cache so the library's subsequent getSession call
   *  (triggered by setCurrentSessionId → useAsyncEffect) can reuse the
   *  already-fetched session without making another network request. */
  private sessionResultCache: Map<string, IAgentScopeRuntimeWebUISession> =
    new Map();

  /** Match list row by display id, backend UUID, or runner session_id. */
  private findListEntry(sessionKey: string): ExtendedSession | undefined {
    if (!sessionKey) return undefined;
    for (const s of this.sessionList) {
      const ext = s as ExtendedSession;
      if (sessionKeyMatches(ext, sessionKey)) return ext;
    }
    return undefined;
  }

  /** Backend ChatSpec.id (UUID) used for GET /api/chats/{id}. */
  private resolveBackendChatId(sessionKey: string): string | null {
    const entry = this.findListEntry(sessionKey);
    if (entry?.realId && !isLocalTimestamp(entry.realId)) return entry.realId;
    if (entry && !isLocalTimestamp(entry.id)) return entry.id;
    if (!isLocalTimestamp(sessionKey)) return sessionKey;
    return null;
  }

  /**
   * Pre-load session data and warm the result cache for ChatSessionInitializer.
   */
  async preloadSession(sessionId: string): Promise<{
    session: IAgentScopeRuntimeWebUISession;
    realId: string | null;
  }> {
    const session = await this.getSession(sessionId);
    const extendedSession = session as ExtendedSession;
    const realId = extendedSession.realId || null;

    this.sessionResultCache.set(sessionId, session);
    if (realId) {
      this.sessionResultCache.set(realId, session);
    }
    setTimeout(() => {
      this.sessionResultCache.delete(sessionId);
      if (realId) this.sessionResultCache.delete(realId);
    }, 3000);

    return { session, realId };
  }

  /** Called after navigate + setCurrentSessionId are both done. */
  finishSessionSwitch(): void {
    this.isSessionSwitching = false;
  }

  /** Reset dedupe state so the next getSession is treated as a fresh selection. */
  clearLastSelectedIds(): void {
    this.lastSelectedIds.clear();
  }

  /**
   * Cache the latest user message for a chat so it can be patched into
   * history during reconnect (the backend only persists it after generation
   * completes). Persisted to sessionStorage so it survives page refresh.
   */
  setLastUserMessage(sessionId: string, text: string): void {
    if (!sessionId || !text) return;
    savePendingUserMessage(sessionId, text);
  }

  /**
   * Cache the latest usage note returned by stop API for this chat. This keeps
   * interrupted turn stats visible when backend history lags behind.
   */
  setLastStopUsageNote(sessionId: string, markdown: string | null): void {
    if (!sessionId) return;
    persistStopUsageNote(sessionId, markdown);
  }

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

  /**
   * Called when a session is selected from the session list.
   * Consumers can register here to update the URL when switching sessions.
   */
  onSessionSelected:
    | ((sessionId: string | null | undefined, realId: string | null) => void)
    | null = null;

  /**
   * The last chatId that onSessionSelected navigated to. ChatSessionInitializer
   * checks this to avoid re-triggering setCurrentSessionId for a URL change
   * that was already handled by onSessionSelected (issue #4557).
   */
  lastNavigatedChatId: string | null = null;

  /**
   * Set by createSession; consumed by ChatSessionInitializer to apply the new
   * local session id after URL clears to /chat (avoids reverting to old chatId).
   */
  pendingNewSessionId: string | null = null;

  /**
   * Called when a new session is created.
   * Consumers can register here to update the URL with the new session id.
   */
  onSessionCreated: ((sessionId: string) => void) | null = null;

  /**
   * When reconnecting to a running conversation, the backend history may not
   * include the latest user message (it's only persisted after generation
   * completes). If generating, look up the cached text from sessionStorage
   * and patch it into the message list.
   *
   * When not generating the conversation is done — clear the cached entry.
   */
  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): void {
    const cachedText = loadPendingUserMessage(backendSessionId);
    if (!cachedText) return;

    const hasCachedUserInHistory = messages.some((msg) => {
      if (msg?.role !== ROLE_USER) return false;
      const text = extractTextFromContent(
        msg?.cards?.[0]?.data?.input?.[0]?.content,
      );
      return text?.trim() === cachedText.trim();
    });

    if (hasCachedUserInHistory) {
      if (!generating) clearPendingUserMessage(backendSessionId);
      return;
    }
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === ROLE_USER) {
      const text = extractTextFromContent(
        lastMsg?.cards?.[0]?.data?.input?.[0]?.content,
      );
      if (!text) {
        lastMsg.cards = buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message).cards;
      }
    } else {
      messages.push(
        buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message),
      );
    }
  }

  private patchLastStopUsageNote(
    messages: IAgentScopeRuntimeWebUIMessage[],
    backendSessionId: string,
  ): void {
    const cachedNote = loadPendingStopUsageNote(backendSessionId).trim();
    if (!cachedNote) return;
    if (patchLastAssistantUsageNote(messages, cachedNote)) {
      this.setLastStopUsageNote(backendSessionId, null);
    }
  }

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
    const local = this.findListEntry(sessionId);
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
    return this.resolveBackendChatId(sessionId);
  }

  /** Apply listChats to sessionList; merge realId and generating by session_id. */
  private applyChatsToSessionList(
    chats: ChatSpec[],
  ): IAgentScopeRuntimeWebUISession[] {
    const newList = chats
      .filter((c) => c.id && c.id !== "undefined" && c.id !== "null")
      .map(chatSpecToSession)
      .reverse();

    // Track which existing sessions have already been matched so that
    // sessions sharing the same sessionId (channel:user_id) don't all
    // resolve to the same existing entry — the root cause of #3843.
    const matchedExistingIds = new Set<string>();

    this.sessionList = newList.map((s) => {
      const sExt = s as ExtendedSession;

      // 1) Exact match by backend UUID: s.id matches existing.id or existing.realId
      let existing = this.sessionList.find((e) => {
        if (matchedExistingIds.has(e.id)) return false;
        const eExt = e as ExtendedSession;
        return e.id === s.id || (eExt.realId != null && eExt.realId === s.id);
      }) as ExtendedSession | undefined;

      // 2) Fallback: match by sessionId, but only claim the first unmatched one
      if (!existing) {
        existing = this.sessionList.find((e) => {
          if (matchedExistingIds.has(e.id)) return false;
          return (e as ExtendedSession).sessionId === sExt.sessionId;
        }) as ExtendedSession | undefined;
      }

      if (!existing) return s;

      matchedExistingIds.add(existing.id);

      const next = { ...s } as ExtendedSession;
      const existingExt = existing as ExtendedSession;
      if (isLocalTimestamp(existingExt.id)) {
        next.id = existingExt.id;
        next.realId = s.id;
        if (!existingExt.realId) {
          queueMicrotask(() => this.notifyRealIdResolved(existingExt.id));
        }
      } else if (existingExt.realId) {
        next.id = existingExt.id;
        next.realId = existingExt.realId;
      }
      // Only carry over generating=true from the old session when the
      // backend hasn't explicitly reported the chat as idle.  Previously
      // the flag was inherited unconditionally, so once set it could never
      // be cleared — causing a permanent spinner in the session list
      // (issue #4903).
      if (existing.generating && sExt.status !== "idle") {
        next.generating = existing.generating;
      }
      return next as IAgentScopeRuntimeWebUISession;
    });
    if (this.preferredChatId) {
      const preferredId = this.preferredChatId;
      this.preferredChatId = null;
      const idx = this.sessionList.findIndex((s) => s.id === preferredId);
      if (idx > 0) {
        const [preferred] = this.sessionList.splice(idx, 1);
        this.sessionList.unshift(preferred);
      }
    }
    return [...this.sessionList];
  }

  async getSessionList() {
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        const chats = await api.listChats();
        return this.applyChatsToSessionList(chats);
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  /**
   * Track both displayId and realId of the last selected session to avoid
   * duplicate onSessionSelected calls when the same session is loaded via
   * either its displayId or realId (issue #4557).
   */
  private lastSelectedIds: Set<string> = new Set();

  async getSession(sessionId: string) {
    // Check short-lived result cache first (populated by preloadSession).
    const cached = this.sessionResultCache.get(sessionId);
    if (cached) {
      this.updateWindowVariables(cached as ExtendedSession);
      return cached;
    }

    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) return existingRequest;

    const requestPromise = this._doGetSession(sessionId);
    this.sessionRequests.set(sessionId, requestPromise);

    try {
      const session = await requestPromise;
      const extendedSession = session as ExtendedSession;
      const realId = extendedSession.realId || null;

      // Only trigger onSessionSelected if neither the displayId nor the
      // realId has already been selected. This prevents the infinite loop
      // where displayId and realId alternate triggering onSessionSelected.
      if (!this.lastSelectedIds.has(sessionId)) {
        this.lastSelectedIds.clear();
        this.lastSelectedIds.add(sessionId);
        if (realId) this.lastSelectedIds.add(realId);
        this.onSessionSelected?.(sessionId, realId);
      }
      return session;
    } finally {
      this.sessionRequests.delete(sessionId);
    }
  }

  /**
   * Fetch chat history from backend and build an ExtendedSession.
   * Centralises the repeated fetch-convert-patch-build pattern used by
   * _doGetSession in multiple branches.
   */
  private async fetchAndBuildSession(
    displayId: string,
    backendId: string,
    listEntry: ExtendedSession | undefined,
  ): Promise<ExtendedSession> {
    const chatHistory = await api.getChat(backendId);
    const generating = isGenerating(chatHistory);
    const messages = convertMessages(chatHistory.messages || []);
    this.patchLastUserMessage(messages, generating, backendId);
    this.patchLastStopUsageNote(messages, backendId);

    const session: ExtendedSession = {
      id: displayId,
      name: listEntry?.name || DEFAULT_SESSION_NAME,
      sessionId: listEntry?.sessionId || displayId,
      userId: listEntry?.userId || DEFAULT_USER_ID,
      channel: listEntry?.channel || DEFAULT_CHANNEL,
      messages,
      meta: listEntry?.meta || {},
      realId:
        listEntry?.realId ??
        (isLocalTimestamp(displayId) ? backendId : undefined),
      generating,
    };
    this.updateWindowVariables(session);
    return session;
  }

  private async _doGetSession(
    sessionId: string,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    // --- No session selected (e.g. after delete) ---
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return this.createEmptySession(Date.now().toString());
    }

    // --- Local timestamp (new chat before backend UUID exists) ---
    if (isLocalTimestamp(sessionId)) {
      const fromList = this.findListEntry(sessionId);

      if (fromList?.realId) {
        return this.fetchAndBuildSession(sessionId, fromList.realId, fromList);
      }

      // Not tracked in the list yet (brand-new chat) — empty local session.
      if (!fromList) {
        return this.getLocalSession(sessionId);
      }

      // In list but UUID not resolved yet (first message in flight).
      await this.waitForRealId(sessionId);
      const refreshed = this.findListEntry(sessionId);
      if (refreshed?.realId) {
        return this.fetchAndBuildSession(
          sessionId,
          refreshed.realId,
          refreshed,
        );
      }
      return this.getLocalSession(sessionId);
    }

    let entry = this.findListEntry(sessionId);
    let backendId = this.resolveBackendChatId(sessionId);

    if (backendId) {
      const displayId = entry?.id ?? sessionId;
      return this.fetchAndBuildSession(displayId, backendId, entry);
    }

    return this.getLocalSession(sessionId);
  }

  /**
   * After fetching the latest session list, try to resolve a local timestamp
   * session to its real backend UUID and notify listeners.
   */
  private resolveAndNotify(tempId: string): void {
    const { list, realId } = resolveRealId(this.sessionList, tempId);
    this.sessionList = list;
    if (realId) {
      this.notifyRealIdResolved(tempId);
      this.onSessionIdResolved?.(tempId, realId);
    }
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.messages = [];
    const index = this.sessionList.findIndex((s) => s.id === session.id);

    if (index > -1) {
      this.sessionList[index] = { ...this.sessionList[index], ...session };

      const existing = this.sessionList[index] as ExtendedSession;
      if (isLocalTimestamp(existing.id) && !existing.realId) {
        const tempId = existing.id;
        this.getSessionList().then(() => this.resolveAndNotify(tempId));
      }
    } else {
      const tempId = session.id!;
      await this.getSessionList().then(() => this.resolveAndNotify(tempId));
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

    this.pendingNewSessionId = session.id;
    this.updateWindowVariables(extended);
    this.onSessionCreated?.(session.id);
    return this.sessionList;
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this.sessionList];

    const { id: sessionId } = session;

    const existing = this.sessionList.find((s) => s.id === sessionId) as
      | ExtendedSession
      | undefined;

    const deleteId =
      existing?.realId ?? (isLocalTimestamp(sessionId) ? null : sessionId);

    if (deleteId) await api.deleteChat(deleteId);

    this.sessionList = this.sessionList.filter((s) => s.id !== sessionId);

    const resolvedId = existing?.realId ?? sessionId;
    // Clear sessionStorage under every id alias we may have written under.
    clearSessionStorageForIds(
      [sessionId, existing?.realId, existing?.sessionId].filter(
        (s): s is string => Boolean(s),
      ),
    );
    this.onSessionRemoved?.(resolvedId);

    return [...this.sessionList];
  }
}

export default new SessionApi();
