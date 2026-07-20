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
import { toDisplayUrl } from "../utils";
import { extractTurnUsageFromOutputMessages } from "../turnUsage";

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
  /** ISO 8601 last-updated timestamp from backend. */
  updatedAt?: string | null;
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

  const turnUsage = extractTurnUsageFromOutputMessages(outputMessages);

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
          usage: turnUsage?.usage ?? null,
          context_usage: turnUsage?.context_usage ?? null,
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
  const len = messages.length;
  let i = 0;

  while (i < len) {
    if (messages[i].role === ROLE_USER) {
      result.push(buildUserCard(messages[i++]));
    } else {
      // Collect consecutive non-user messages via slice
      const startIdx = i;
      while (i < len && messages[i].role !== ROLE_USER) i++;
      const outputMsgs = messages.slice(startIdx, i).map(toOutputMessage);
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
    updatedAt: chat.updated_at ?? null,
    pinned: chat.pinned ?? false,
    archived: chat.archived ?? false,
    archivedAt: chat.archived_at ?? null,
  }) as ExtendedSession;

/** Returns true when id is a local session id (timestamp-random, not a backend UUID). */
const isLocalTimestamp = (id: string): boolean => /^\d+-[a-z0-9]+$/.test(id);

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
  // 1) Local display entry already linked to a backend UUID.
  const alreadyResolved = sessionList.find(
    (s) => s.id === tempSessionId && (s as ExtendedSession).realId,
  ) as ExtendedSession | undefined;
  if (alreadyResolved?.realId) {
    return { list: sessionList, realId: alreadyResolved.realId };
  }

  // 2) Backend chat from listChats (UUID id + matching session_id).
  //    Skip the local placeholder whose id equals the timestamp — using that
  //    id as realId causes GET /api/chats/{timestamp} → 404.
  let realSession = sessionList.find(
    (s) =>
      (s as ExtendedSession).sessionId === tempSessionId &&
      !(s as ExtendedSession).realId &&
      s.id !== tempSessionId,
  );

  // 3) Fallback: only local placeholder exists (backend list not merged yet).
  if (!realSession) {
    realSession = sessionList.find(
      (s) => s.id === tempSessionId && !(s as ExtendedSession).realId,
    );
  }

  if (!realSession) return { list: sessionList, realId: null };

  // Never treat a numeric local id as the backend UUID.
  if (isLocalTimestamp(realSession.id)) {
    return { list: sessionList, realId: null };
  }

  const realUUID = realSession.id;
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

/** Shape stored in sessionStorage. Backward compat: old format was plain text. */
interface PendingUserMsg {
  text: string;
  /** Full content array (stored-name format) for rebuilding the user card
   *  with attachments. When absent, only text is displayed. */
  content?: Array<{ type: string; [key: string]: unknown }>;
}

function savePendingUserMessage(
  sessionId: string,
  data: string | PendingUserMsg,
): void {
  try {
    const val = typeof data === "string" ? data : JSON.stringify(data);
    sessionStorage.setItem(`${STORAGE_PREFIX}${sessionId}`, val);
  } catch {
    /* quota exceeded – ignore */
  }
}

function loadPendingUserMessage(sessionId: string): PendingUserMsg | null {
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${sessionId}`);
    if (!raw) return null;
    // Try parsing as JSON (new format with content array)
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && "text" in parsed) {
        return parsed as PendingUserMsg;
      }
    } catch {
      /* not JSON — legacy plain-text format */
    }
    return { text: raw };
  } catch {
    return null;
  }
}

function clearPendingUserMessage(sessionId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${sessionId}`);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// SessionApi
// ---------------------------------------------------------------------------

class SessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private sessionList: IAgentScopeRuntimeWebUISession[] = [];

  /** Previous returned list reference for shallow-compare optimisation. */
  private _prevReturnedList: IAgentScopeRuntimeWebUISession[] | null = null;

  /**
   * When set, getSessionList will move the matching session to the front on the first call,
   * so the library's useMount auto-selects it instead of always defaulting to sessions[0].
   * Cleared after first use.
   */
  preferredChatId: string | null = null;

  /**
   * Tracks the last actively selected chat ID (realId or displayId).
   * Used to restore the correct session when ChatPage re-mounts without
   * a chatId in the URL (e.g. navigating back to /chat from /settings).
   */
  lastActiveChatId: string | null = null;

  // ---------------------------------------------------------------------------
  // Session switch lock (issue #4557)
  // Prevents rapid session switching from causing infinite loops by blocking
  // all clicks until the current switch completes (data loaded + URL updated).
  // ---------------------------------------------------------------------------

  /** Whether a session switch is currently in progress. */
  isSessionSwitching = false;

  /** AbortController for the current switch — aborted when a new switch starts. */
  private switchAbortController: AbortController | null = null;

  /**
   * Start a new session switch. Aborts any in-flight switch and returns a
   * fresh AbortController whose signal should be threaded through all async ops.
   */
  startNewSwitch(): AbortController {
    // Cancel previous in-flight switch
    this.switchAbortController?.abort();
    const controller = new AbortController();
    this.switchAbortController = controller;
    this.isSessionSwitching = true;
    return controller;
  }

  /**
   * Set to true by useCreateNewSession before calling createSession().
   * Consumed and reset inside createSession on every call.
   * Distinguishes a user-initiated creation from the library's automatic
   * post-SSE prepare call, which must NOT navigate away from the current
   * active conversation or fire onSessionCreated unexpectedly.
   */
  userInitiatedCreate = false;

  /** Short-lived result cache so the library's subsequent getSession call
   *  (triggered by setCurrentSessionId → useAsyncEffect) can reuse the
   *  already-fetched session without making another network request. */
  private sessionResultCache: Map<string, IAgentScopeRuntimeWebUISession> =
    new Map();

  // ---------------------------------------------------------------------------
  // LRU cache for fully-converted sessions (avoids re-fetching on switch-back)
  // ---------------------------------------------------------------------------

  private static readonly CONVERTED_CACHE_MAX = 10;
  private static readonly CONVERTED_CACHE_TTL = 5 * 60 * 1000; // 5 minutes

  /** LRU cache: backendId → { session, timestamp, updatedAt } */
  private convertedSessionCache = new Map<
    string,
    { session: ExtendedSession; timestamp: number; updatedAt: string | null }
  >();

  private getCachedConvertedSession(
    backendId: string,
    currentUpdatedAt?: string | null,
  ): ExtendedSession | null {
    const entry = this.convertedSessionCache.get(backendId);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > SessionApi.CONVERTED_CACHE_TTL) {
      this.convertedSessionCache.delete(backendId);
      return null;
    }
    // Staleness check against the chat's backend updated_at: when a new
    // message arrives from an external channel (e.g. DingTalk), the polled
    // session list carries a newer updated_at than what we cached. The cached
    // messages are therefore stale and must be dropped so callers re-fetch.
    // Without this, switching away and back served stale cached messages and
    // only a full page refresh (which recreates this singleton) showed the
    // new message (issue #6131 follow-up).
    if (
      currentUpdatedAt &&
      (!entry.updatedAt || currentUpdatedAt > entry.updatedAt)
    ) {
      this.convertedSessionCache.delete(backendId);
      return null;
    }
    // LRU: move to end
    this.convertedSessionCache.delete(backendId);
    this.convertedSessionCache.set(backendId, entry);
    return entry.session;
  }

  private setCachedConvertedSession(
    backendId: string,
    session: ExtendedSession,
    updatedAt: string | null,
  ): void {
    if (this.convertedSessionCache.size >= SessionApi.CONVERTED_CACHE_MAX) {
      // Evict oldest (first entry in Map iteration order)
      const oldestKey = this.convertedSessionCache.keys().next().value;
      if (oldestKey) this.convertedSessionCache.delete(oldestKey);
    }
    this.convertedSessionCache.set(backendId, {
      session,
      timestamp: Date.now(),
      updatedAt,
    });
  }

  /** Invalidate the converted cache for a session (call after sending a message). */
  invalidateConvertedCache(backendId: string): void {
    this.convertedSessionCache.delete(backendId);
  }

  /**
   * Pre-load a session's data. Returns the session with its realId resolved.
   * Used by handleSessionClick to load data BEFORE setting currentSessionId,
   * so the library's automatic getSession call hits the result cache.
   */
  async preloadSession(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<{
    session: IAgentScopeRuntimeWebUISession;
    realId: string | null;
  }> {
    try {
      const session = await this.getSession(sessionId, signal);
      const extendedSession = session as ExtendedSession;
      const realId = extendedSession.realId || null;

      // Cache the result so subsequent getSession calls return immediately.
      this.sessionResultCache.set(sessionId, session);
      if (realId) {
        this.sessionResultCache.set(realId, session);
      }
      // Clear cache after 3s (enough for the library's useAsyncEffect to fire).
      setTimeout(() => {
        this.sessionResultCache.delete(sessionId);
        if (realId) this.sessionResultCache.delete(realId);
      }, 3000);

      return { session, realId };
    } catch (error) {
      // Don't reset switching state on abort — the new switch owns the lock
      if (error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }
      this.isSessionSwitching = false;
      throw error;
    }
  }

  /** Called when a switch completes (or is superseded). */
  finishSessionSwitch(): void {
    this.isSessionSwitching = false;
    this.switchAbortController = null;
  }

  /**
   * Cache the latest user message for a chat so it can be patched into
   * history during reconnect (the backend only persists it after generation
   * completes). Persisted to sessionStorage so it survives page refresh.
   *
   * @param content  Optional full content array (in stored-name format)
   *                 including images/files. When provided, patchLastUserMessage
   *                 will reconstruct the user card with attachments.
   */
  setLastUserMessage(
    sessionId: string,
    text: string,
    content?: Array<{ type: string; [key: string]: unknown }>,
  ): void {
    if (!sessionId || !text) return;
    // Invalidate LRU cache so switching back fetches fresh messages
    this.invalidateConvertedCache(sessionId);
    if (content && content.length > 0) {
      savePendingUserMessage(sessionId, { text, content });
    } else {
      savePendingUserMessage(sessionId, text);
    }
  }

  /**
   * Deduplicates concurrent getSessionList calls so that two parallel
   * invocations share one network request and write sessionList only once,
   * preserving any realId mappings that were already resolved.
   */
  private sessionListRequest: Promise<IAgentScopeRuntimeWebUISession[]> | null =
    null;

  /** Pending resolve promise so getSession can await it before returning. */
  private resolvePromise: Promise<void> | null = null;

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
   * Called when a new session is created.
   * Consumers can register here to update the URL with the new session id.
   */
  onSessionCreated: ((sessionId: string) => void) | null = null;

  /**
   * When reconnecting to a running conversation, the backend history may not
   * include the latest user message (it's only persisted after generation
   * completes). If generating, look up the cached data from sessionStorage
   * and patch it into the message list (including any attachments).
   *
   * When not generating the conversation is done — clear the cached entry.
   */
  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): void {
    if (!generating) {
      clearPendingUserMessage(backendSessionId);
      return;
    }

    const cached = loadPendingUserMessage(backendSessionId);
    if (!cached || !cached.text) return;

    // Use the full content array (with images/files) when available;
    // fall back to text-only for legacy entries.
    const msgContent: unknown = cached.content ?? [
      { type: "text", text: cached.text },
    ];

    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === ROLE_USER) {
      const text = extractTextFromContent(
        lastMsg?.cards?.[0]?.data?.input?.[0]?.content,
      );
      if (!text) {
        lastMsg.cards = buildUserCard({
          content: msgContent,
          role: ROLE_USER,
        } as Message).cards;
      }
    } else {
      messages.push(
        buildUserCard({
          content: msgContent,
          role: ROLE_USER,
        } as Message),
      );
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

  private findSession(id: string): ExtendedSession | undefined {
    return this.sessionList.find(
      (x) => x.id === id || (x as ExtendedSession).realId === id,
    ) as ExtendedSession | undefined;
  }

  /** Returns the real backend UUID, or null when not yet resolved. */
  getRealIdForSession(sessionId: string): string | null {
    return this.findSession(sessionId)?.realId ?? null;
  }

  /** Resolves the effective ID for URL navigation (prefers backend UUID). */
  getEffectiveSessionId(
    sessionId: string,
    resolvedRealId?: string | null,
  ): string {
    return resolvedRealId ?? this.getRealIdForSession(sessionId) ?? sessionId;
  }

  /**
   * Centralizes state tracking after navigating to a session.
   * Reduces repeated `lastActiveChatId + lastNavigatedChatId + persist` scattered
   * across onSessionIdResolved, onSessionSelected, drawer, and initializer.
   */
  trackNavigatedSession(
    effectiveId: string,
    persistFn?: (agentId: string, id: string) => void,
    agentId?: string,
  ): void {
    this.lastActiveChatId = effectiveId;
    this.lastNavigatedChatId = effectiveId;
    if (persistFn && agentId) {
      persistFn(agentId, effectiveId);
    }
  }

  /**
   * Returns true if id is a newly-created local-timestamp session that hasn't
   * yet sent its first message (i.e. it's in sessionList but has no realId).
   * Used by onSessionSelected to suppress library auto-selection while the
   * user is on a blank new-chat screen.
   */
  isUnresolvedLocalSession(id: string): boolean {
    if (!isLocalTimestamp(id)) return false;
    const session = this.findSession(id);
    return !!session && !session.realId;
  }

  /** Returns the backend-compatible session_id. Falls back to the id itself. */
  getBackendSessionId(libraryId: string): string {
    return this.findSession(libraryId)?.sessionId || libraryId;
  }

  /** Returns session identity from the session list (authoritative).
   *  Uses lastActiveChatId (set only by intentional user actions) as the
   *  primary lookup key, avoiding the stale window globals problem. */
  getSessionIdentity(): {
    sessionId: string;
    userId: string;
    channel: string;
  } {
    // lastActiveChatId is immune to stale updateWindowVariables overwrites
    // because it is only set by onSessionSelected / onSessionCreated /
    // handleSessionClick — all intentional user actions.
    const session = this.lastActiveChatId
      ? this.findSession(this.lastActiveChatId)
      : undefined;
    if (session?.userId) {
      return {
        sessionId: session.sessionId || "",
        userId: session.userId,
        channel: session.channel || DEFAULT_CHANNEL,
      };
    }
    return {
      sessionId: window.currentSessionId || "",
      userId: window.currentUserId || DEFAULT_USER_ID,
      channel: window.currentChannel || DEFAULT_CHANNEL,
    };
  }

  /** Apply listChats to sessionList; merge realId and generating by session_id. */
  private applyChatsToSessionList(
    chats: ChatSpec[],
  ): IAgentScopeRuntimeWebUISession[] {
    // Capture the leading unresolved local session (the one just created via
    // createSession). It won't appear in the backend list until the first
    // message is sent; without this it would be wiped on every getSessionList
    // call — causing the "new chat flashes then disappears" bug.
    // We only track the leading entry: at most one unresolved session should
    // exist at any time (the guard in createSession enforces this invariant).
    const firstItem = this.sessionList[0];
    const leadingUnresolved =
      firstItem &&
      isLocalTimestamp(firstItem.id) &&
      !(firstItem as ExtendedSession).realId
        ? (firstItem as ExtendedSession)
        : null;

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
      if (existing.realId) {
        // Already resolved: keep the local id and the existing realId so the
        // library's currentSessionId (local timestamp) stays valid during SSE.
        next.id = existing.id;
        next.realId = existing.realId;
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

    // Re-prepend the leading unresolved local session if the backend didn't
    // return it yet (no message sent). Once matched, it's already in the new
    // list as {id: localId} via resolveRealId, so no re-prepend is needed.
    if (leadingUnresolved && !matchedExistingIds.has(leadingUnresolved.id)) {
      this.sessionList = [leadingUnresolved, ...this.sessionList];
    }

    if (this.preferredChatId) {
      const preferredId = this.preferredChatId;
      this.preferredChatId = null;
      let idx = this.sessionList.findIndex((s) => s.id === preferredId);
      // Page refresh: URL may contain a local timestamp but backend only has UUIDs.
      // Fall back to matching by sessionId (channel:user_id format).
      if (idx < 0 && isLocalTimestamp(preferredId)) {
        idx = this.sessionList.findIndex(
          (s) => (s as ExtendedSession).sessionId === preferredId,
        );
        if (idx >= 0) {
          const s = this.sessionList[idx] as ExtendedSession;
          s.realId = s.id;
          s.id = preferredId;
        }
      }
      if (idx > 0) {
        const [preferred] = this.sessionList.splice(idx, 1);
        this.sessionList.unshift(preferred);
      }
    }

    // If the list hasn't changed substantively, return the previous array
    // reference to prevent downstream useMemo / React re-renders.
    if (
      this._prevReturnedList &&
      this.isSessionListEqual(this._prevReturnedList, this.sessionList)
    ) {
      return this._prevReturnedList;
    }
    const result = [...this.sessionList];
    this._prevReturnedList = result;
    return result;
  }

  /**
   * Shallow-compare two session lists by key fields.
   * Returns true if lists are structurally identical (no re-render needed).
   */
  private isSessionListEqual(
    prev: IAgentScopeRuntimeWebUISession[],
    next: IAgentScopeRuntimeWebUISession[],
  ): boolean {
    if (prev.length !== next.length) return false;
    for (let i = 0; i < prev.length; i++) {
      const a = prev[i] as ExtendedSession;
      const b = next[i] as ExtendedSession;
      if (
        a.id !== b.id ||
        a.name !== b.name ||
        a.status !== b.status ||
        a.updatedAt !== b.updatedAt ||
        a.pinned !== b.pinned ||
        a.generating !== b.generating ||
        a.realId !== b.realId
      ) {
        return false;
      }
    }
    return true;
  }

  async getSessionList() {
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        const chats = await api.listChats({ archived: false });
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

  async getSession(sessionId: string, signal?: AbortSignal) {
    // Check short-lived result cache first (populated by preloadSession).
    const cached = this.sessionResultCache.get(sessionId);
    if (cached) return cached;

    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) return existingRequest;

    const requestPromise = this._doGetSession(sessionId, signal);
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
    signal?: AbortSignal,
  ): Promise<ExtendedSession> {
    // Check LRU cache for non-generating sessions
    const isIdle = !listEntry?.generating;
    if (isIdle) {
      const cached = this.getCachedConvertedSession(
        backendId,
        listEntry?.updatedAt,
      );
      if (cached) {
        // Update mutable fields that may differ
        cached.id = displayId;
        if (listEntry?.name) cached.name = listEntry.name;
        this.updateWindowVariables(cached);
        return cached;
      }
    }

    const chatHistory = await api.getChat(backendId, { signal });
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const generating = isGenerating(chatHistory);
    const messages = convertMessages(chatHistory.messages || []);
    this.patchLastUserMessage(messages, generating, backendId);

    const session: ExtendedSession = {
      id: displayId,
      name: listEntry?.name || DEFAULT_SESSION_NAME,
      sessionId: listEntry?.sessionId || displayId,
      userId: listEntry?.userId || DEFAULT_USER_ID,
      channel: listEntry?.channel || DEFAULT_CHANNEL,
      messages,
      meta: listEntry?.meta || {},
      realId: listEntry?.realId,
      generating,
    };
    this.updateWindowVariables(session);

    // Cache non-generating sessions
    if (!generating) {
      this.setCachedConvertedSession(
        backendId,
        session,
        listEntry?.updatedAt ?? null,
      );
    }

    return session;
  }

  private async _doGetSession(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    // --- No session selected (library bug: createSession sets undefined) ---
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return {
        id: sessionId || "",
        name: "",
        sessionId: "",
        userId: DEFAULT_USER_ID,
        channel: DEFAULT_CHANNEL,
        messages: [],
        meta: {},
      } as ExtendedSession;
    }

    // --- Local timestamp ID (New Chat before first reply) ---
    if (isLocalTimestamp(sessionId)) {
      const fromList = this.findSession(sessionId);
      if (fromList?.realId) {
        try {
          return await this.fetchAndBuildSession(
            sessionId,
            fromList.realId,
            fromList,
            signal,
          );
        } catch (error) {
          // If fetching with realId fails, return the local session without messages
          // This handles cases where the backend has an inconsistency
          this.updateWindowVariables(fromList);
          return fromList;
        }
      }
      // A triggerResolve may be in-flight (POST succeeded but getSessionList
      // hasn't returned yet). Wait for it so we can return real messages
      // instead of an empty local session — prevents clearing the library's
      // message state after the first SSE stream completes.
      if (fromList && this.resolvePromise) {
        await this.resolvePromise;
        const resolved = this.findSession(sessionId);
        if (resolved?.realId) {
          try {
            return await this.fetchAndBuildSession(
              sessionId,
              resolved.realId,
              resolved,
              signal,
            );
          } catch {
            this.updateWindowVariables(resolved);
            return resolved;
          }
        }
      }
      if (fromList) {
        this.updateWindowVariables(fromList);
        return fromList;
      }
      return this.createEmptySession(sessionId);
    }

    // --- Regular backend UUID ---
    try {
      return await this.fetchAndBuildSession(
        sessionId,
        sessionId,
        this.findSession(sessionId),
        signal,
      );
    } catch (error: any) {
      // If the backend session doesn't exist (e.g. invalid UUID or expired session)
      // return an empty session to prevent repeated 404 API calls.
      // Note: the request layer throws Error(message) without attaching .status,
      // so only message-based detection is reliable here.
      if (error.message?.includes("Chat not found")) {
        const emptySession = this.createEmptySession(sessionId);
        emptySession.id = sessionId;
        return emptySession;
      }
      throw error;
    }
  }

  /**
   * After fetching the latest session list, try to resolve a local timestamp
   * session to its real backend UUID and notify listeners.
   */
  private resolveAndNotify(tempId: string): void {
    const { list, realId } = resolveRealId(this.sessionList, tempId);
    this.sessionList = list;
    if (realId) {
      // Migrate the pending user message from the local timestamp key to
      // the backend UUID key so patchLastUserMessage can find it after
      // page refresh (where the URL — and therefore the lookup key — is
      // the UUID, not the original timestamp).
      const cached = loadPendingUserMessage(tempId);
      if (cached) {
        savePendingUserMessage(realId, cached);
        clearPendingUserMessage(tempId);
      }
      this.onSessionIdResolved?.(tempId, realId);
    }
  }

  /**
   * Trigger ID resolution for a local timestamp session.
   * Called by customFetch after POST succeeds (the backend has created the
   * chat at that point). Fire-and-forget — runs concurrently with SSE.
   */
  triggerResolve(tempId: string): void {
    if (!isLocalTimestamp(tempId)) return;
    const existing = this.findSession(tempId);
    if (!existing || existing.realId) return; // already resolved
    // Force a fresh listChats request: if a stale in-flight getSessionList
    // (started before the POST) is still pending, its response won't contain
    // the new backend session yet. Sharing that stale promise would cause
    // resolveRealId to silently fail and onSessionIdResolved never fires,
    // leaving the URL at /chat instead of /chat/<uuid>.
    this.sessionListRequest = null;
    const promise = this.getSessionList()
      .then(() => this.resolveAndNotify(tempId))
      .finally(() => {
        if (this.resolvePromise === promise) this.resolvePromise = null;
      });
    this.resolvePromise = promise;
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    // Strip messages before merging to avoid storing large data in the
    // session list. Use destructuring instead of mutating the input object
    // — the library may pass its own internal session reference, and
    // mutating session.messages would corrupt its React state.
    const { messages: _msgs, ...metadata } = session;
    const index = this.sessionList.findIndex((s) => s.id === metadata.id);

    if (index > -1) {
      this.sessionList[index] = { ...this.sessionList[index], ...metadata };
    } else {
      // Session not found by id — createSession now always unshifts the
      // session before returning, so this branch should not occur in normal
      // flows. Refresh the list to stay in sync but do NOT call resolveAndNotify:
      // triggerResolve (called by customFetch after POST success) is the sole
      // entry point for ID resolution.
      await this.getSessionList();
    }

    return [...this.sessionList];
  }

  async createSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    const isUserInitiated = this.userInitiatedCreate;
    this.userInitiatedCreate = false;

    // CRITICAL: The library's internal updateSession returns the INPUT `session`
    // object (not our return value). The library's createSession then does:
    //   setCurrentSessionId(session.id)
    //   setMessages(session.messages)
    // If session.id is undefined, currentSessionId becomes undefined, which
    // causes ensureSession to call createSession again on EVERY message send,
    // each time clearing messages via setMessages([]). We MUST write-back the
    // generated id onto the input object so the library sets currentSessionId
    // to a valid value.

    // Idempotency: reuse an existing unresolved local session. Only fire
    // onSessionCreated on explicit user action; suppress on library retries
    // to prevent navigating away during the race window where SSE ends before
    // resolveAndNotify completes (ts-xxx.realId not yet set).
    const existing = this.sessionList.find(
      (s) => isLocalTimestamp(s.id) && !(s as ExtendedSession).realId,
    ) as ExtendedSession | undefined;
    if (existing) {
      session.id = existing.id;
      if (isUserInitiated) this.onSessionCreated?.(existing.id);
      return [...this.sessionList];
    }

    // Library auto-prepares a session after SSE ends. Skip when the user is
    // already viewing a resolved conversation to avoid navigating away.
    if (
      !isUserInitiated &&
      this.lastActiveChatId &&
      !isLocalTimestamp(this.lastActiveChatId)
    ) {
      const active = this.findSession(this.lastActiveChatId);
      if (active) session.id = active.id;
      return [...this.sessionList];
    }

    const localId = `${Date.now()}-${Math.random()
      .toString(36)
      .substring(2, 9)}`;
    const extended = this.createEmptySession(localId);
    extended.name = session.name || DEFAULT_SESSION_NAME;
    this.sessionList.unshift(extended);
    session.id = localId;
    this.onSessionCreated?.(localId);
    return [...this.sessionList];
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this.sessionList];

    const { id: sessionId } = session;

    const existing = this.findSession(sessionId);

    const deleteId =
      existing?.realId ?? (isLocalTimestamp(sessionId) ? null : sessionId);

    if (deleteId) await api.deleteChat(deleteId);

    // Invalidate LRU cache for the deleted session
    if (deleteId) this.invalidateConvertedCache(deleteId);
    if (existing?.realId) this.invalidateConvertedCache(existing.realId);

    // Use the canonical id from the list entry (existing?.id = localId even when
    // the caller passed a UUID), so the filter always removes the right entry.
    const canonicalId = existing?.id ?? sessionId;
    this.sessionList = this.sessionList.filter((s) => s.id !== canonicalId);

    const resolvedId = existing?.realId ?? sessionId;
    this.onSessionRemoved?.(resolvedId);

    return [...this.sessionList];
  }
}

export default new SessionApi();

// ---------------------------------------------------------------------------
// Test-only exports (used by ./tests/testLargeSession.test.tsx — PR-F3 / #5479)
// These helpers are pure data transforms with no side effects; exposing them
// avoids reaching into internals via private reflection. Keep the surface tiny.
// ---------------------------------------------------------------------------
export const __test__ = {
  convertMessages,
  buildUserCard,
  buildResponseCard,
  toOutputMessage,
  normalizeOutputMessageContent,
  contentToRequestParts,
  extractTextFromContent,
  parseTimestamp,
  isLocalTimestamp,
  isGenerating,
  resolveRealId,
};
