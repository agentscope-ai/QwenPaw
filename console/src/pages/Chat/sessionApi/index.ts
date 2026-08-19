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
import { useAgentStore } from "../../../stores/agentStore";
import {
  extractTurnUsageFromOutputMessages,
  extractLatestSnapshotFromCards,
} from "../turnUsage";
import { useTurnUsageStore } from "../turnUsageStore";
import { QWENPAW_CLIENT_MESSAGE_ID_KEY } from "../../../utils/clientMessageId";

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

function hydrateTurnUsageFromMessages(
  messages: IAgentScopeRuntimeWebUIMessage[],
): void {
  useTurnUsageStore.getState().invalidateTurn();
  const snap = extractLatestSnapshotFromCards(messages);
  const activeMax = useTurnUsageStore.getState().activeMaxInputLength;
  if (snap?.context_usage && typeof activeMax === "number" && activeMax > 0) {
    const estimatedTokens = snap.context_usage.estimated_tokens;
    const updatedContext = {
      estimated_tokens: estimatedTokens,
      max_input_length: activeMax,
      context_usage_ratio: Math.min((estimatedTokens / activeMax) * 100, 100),
    };
    // Keep the latest assistant card in sync with the store. Otherwise
    // patchContextMaxInputLength early-returns on stale card.max and the
    // ring stops updating after a config change + model switch.
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role !== ROLE_ASSISTANT) continue;
      const card = (
        msg.cards as
          | Array<{ code?: string; data?: Record<string, unknown> }>
          | undefined
      )?.find((c) => c?.code === CARD_RESPONSE);
      if (!card?.data?.context_usage) continue;
      card.data.context_usage = updatedContext;
      break;
    }
    useTurnUsageStore.getState().setSnapshot({
      usage: snap.usage,
      context_usage: updatedContext,
    });
    return;
  }
  useTurnUsageStore.getState().setSnapshot(snap);
}

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
  /** Whether the chat is archived. */
  archived?: boolean;
  /** ISO 8601 archive timestamp from backend. */
  archivedAt?: string | null;
  source?: ChatSpec["source"];
  groupId?: string | null;
  parentSessionId?: string | null;
  rootSessionId?: string | null;
}

// ---------------------------------------------------------------------------
// Message conversion helpers: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

/**
 * Cryptographically random base36 suffix for locally generated ids.
 * The ids are not secrets, but sourcing them from the CSPRNG avoids any
 * predictability concern and keeps static analysis clean.
 */
function randomBase36(length: number): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = "";
  for (const byte of bytes) out += (byte % 36).toString(36);
  return out;
}

function generateId(): string {
  return `${Date.now()}-${randomBase36(9)}`;
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

const extractClientMessageId = (metadata: unknown): string | undefined => {
  if (!metadata || typeof metadata !== "object") return undefined;
  const nestedMetadata = (metadata as Record<string, unknown>).metadata;
  if (!nestedMetadata || typeof nestedMetadata !== "object") {
    return undefined;
  }
  const candidate = (nestedMetadata as Record<string, unknown>)[
    QWENPAW_CLIENT_MESSAGE_ID_KEY
  ];
  return typeof candidate === "string" ? candidate : undefined;
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
              metadata: msg.metadata ?? null,
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
    source: chat.source ?? "chat",
    groupId: chat.group_id ?? null,
    parentSessionId: chat.parent_session_id ?? null,
    rootSessionId: chat.root_session_id ?? null,
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
  clientMessageId?: string;
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

/**
 * Ownership token for asynchronous session work. Captured when an operation
 * starts; a result whose token no longer matches the active epoch must not
 * mutate singleton state or notify the current view.
 *
 * The generation is required in addition to the agent id: switching
 * A -> B -> A would otherwise let work from the first A epoch pass an
 * agent-id-only comparison.
 */
export interface SessionOwnerToken {
  agentId: string;
  generation: number;
}

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
   *  already-fetched session without making another network request. Each
   *  entry carries the owner epoch it was produced under and is only served
   *  within that epoch. */
  private sessionResultCache: Map<
    string,
    { session: IAgentScopeRuntimeWebUISession; owner: SessionOwnerToken }
  > = new Map();

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
    const owner = this.getActiveOwner();
    try {
      const session = await this.getSession(sessionId, signal);

      // A preload that completes after an agent switch must fail like an
      // aborted request: resolving normally would let the caller navigate
      // the new agent to the stale session and mark it as preferred.
      if (!this.isActiveOwner(owner)) {
        throw new DOMException("Aborted", "AbortError");
      }

      const extendedSession = session as ExtendedSession;
      const realId = extendedSession.realId || null;

      // Cache the result so subsequent getSession calls return immediately.
      const entry = { session, owner };
      this.sessionResultCache.set(sessionId, entry);
      if (realId) {
        this.sessionResultCache.set(realId, entry);
      }
      // Clear after 3s (enough for the library's useAsyncEffect to fire).
      // Delete by entry identity so a late timer cannot remove a newer
      // entry cached under the same key.
      setTimeout(() => {
        if (this.sessionResultCache.get(sessionId) === entry) {
          this.sessionResultCache.delete(sessionId);
        }
        if (realId && this.sessionResultCache.get(realId) === entry) {
          this.sessionResultCache.delete(realId);
        }
      }, 3000);

      return { session, realId };
    } catch (error) {
      // A stale completion must look like an abort on the error path too:
      // a plain network/backend rejection would otherwise be handled as a
      // failure of the CURRENT switch and select the old agent's session.
      if (!this.isActiveOwner(owner)) {
        throw new DOMException("Aborted", "AbortError");
      }
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

  // ---------------------------------------------------------------------------
  // Agent ownership epochs
  // Async session operations capture the active owner token before awaiting;
  // late results from a previous epoch are rejected before they can mutate
  // singleton state or notify the current view.
  // ---------------------------------------------------------------------------

  /** Current ownership epoch. agentId "" = not yet claimed (tests only —
   *  at runtime the module claims the selected agent on load, below). */
  private activeOwner: SessionOwnerToken = { agentId: "", generation: 0 };

  /**
   * Claims session ownership for an agent. Advances the generation whenever
   * the agent actually changes so that A -> B -> A creates a fresh epoch.
   * Driven by the agent-store subscription at the bottom of this module, so
   * the claim happens synchronously with the agent change — before any React
   * re-render or effect can start new-agent session work.
   */
  setActiveAgent(agentId: string): SessionOwnerToken {
    if (this.activeOwner.agentId === agentId) return this.activeOwner;
    this.activeOwner = { agentId, generation: this.activeOwner.generation + 1 };
    // Drop shared in-flight work and short-lived caches from the previous
    // epoch so the new agent never awaits or reuses them. The underlying
    // promises keep running but their results are rejected by the owner
    // checks at the apply sites.
    this.sessionListRequest = null;
    this.resolvePromise = null;
    this.sessionRequests.clear();
    this.sessionResultCache.clear();
    this.convertedSessionCache.clear();
    // Reset the session list and its comparison state as well: the next
    // agent's chats can share a session_id (channel:user_id) with the old
    // list, and merging against leftover entries would transfer the previous
    // agent's local id / backend UUID onto a different chat.
    this.sessionList = [];
    this._prevReturnedList = null;
    this.lastSelectedIds.clear();
    // Release the switch lock: the switch it belonged to is owned by the
    // previous epoch and its completion handler may never run (e.g. the
    // initializer aborted on unmount). Leaving it set would make the new
    // agent permanently skip URL sync, session selection, and list polling.
    this.isSessionSwitching = false;
    this.switchAbortController?.abort();
    this.switchAbortController = null;
    return this.activeOwner;
  }

  getActiveOwner(): SessionOwnerToken {
    return this.activeOwner;
  }

  /** A token is active only when both the agent and its epoch still match. */
  isActiveOwner(token: SessionOwnerToken): boolean {
    return (
      token.agentId === this.activeOwner.agentId &&
      token.generation === this.activeOwner.generation
    );
  }

  /**
   * Applies the view-facing side effects of a loaded session (window identity
   * globals and the turn-usage store) only while the owner epoch that started
   * the load is still active. A stale load must never rewrite the current
   * agent's identity or usage view.
   */
  private applySessionView(
    session: ExtendedSession,
    owner: SessionOwnerToken,
  ): void {
    if (!this.isActiveOwner(owner)) return;
    this.updateWindowVariables(session);
    hydrateTurnUsageFromMessages(session.messages ?? []);
  }

  /**
   * Test-only: restores ownership, in-flight work, caches, and callbacks to a
   * pristine page-load state so tests cannot leak state into each other.
   */
  resetForTests(): void {
    this.activeOwner = { agentId: "", generation: 0 };
    this.sessionListRequest = null;
    this.resolvePromise = null;
    this.sessionRequests.clear();
    this.sessionResultCache.clear();
    this.convertedSessionCache.clear();
    this.sessionList = [];
    this._prevReturnedList = null;
    this.lastSelectedIds.clear();
    this.preferredChatId = null;
    this.lastActiveChatId = null;
    this.lastNavigatedChatId = null;
    this.isSessionSwitching = false;
    this.switchAbortController = null;
    this.userInitiatedCreate = false;
    this.onSessionIdResolved = null;
    this.onSessionRemoved = null;
    this.onSessionSelected = null;
    this.onSessionCreated = null;
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
    clientMessageId?: string,
  ): void {
    if (!sessionId || !text) return;
    // Invalidate LRU cache so switching back fetches fresh messages
    this.invalidateConvertedCache(sessionId);
    if (content && content.length > 0) {
      savePendingUserMessage(sessionId, { text, content, clientMessageId });
    } else if (clientMessageId) {
      savePendingUserMessage(sessionId, { text, clientMessageId });
    } else {
      savePendingUserMessage(sessionId, text);
    }
  }

  /** Remove a pending message only when it still belongs to this request. */
  discardLastUserMessage(sessionId: string, clientMessageId?: string): void {
    if (!sessionId) return;
    const cached = loadPendingUserMessage(sessionId);
    if (!cached) return;
    if (
      clientMessageId &&
      cached.clientMessageId &&
      cached.clientMessageId !== clientMessageId
    ) {
      return;
    }
    clearPendingUserMessage(sessionId);
  }

  /**
   * Deduplicates concurrent getSessionList calls so that two parallel
   * invocations share one network request and write sessionList only once,
   * preserving any realId mappings that were already resolved.
   * The in-flight request carries the owner token it was started under so it
   * is never reused — nor applied — across an agent switch.
   */
  private sessionListRequest: {
    owner: SessionOwnerToken;
    promise: Promise<IAgentScopeRuntimeWebUISession[]>;
  } | null = null;

  /** Pending resolve promise so getSession can await it before returning. */
  private resolvePromise: Promise<void> | null = null;

  /**
   * Deduplicates concurrent getSession calls for the same sessionId.
   * Each in-flight promise carries the owner epoch it was started under and
   * is never reused across an agent switch.
   */
  private sessionRequests: Map<
    string,
    {
      promise: Promise<IAgentScopeRuntimeWebUISession>;
      owner: SessionOwnerToken;
    }
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
   * When not generating the conversation is done — clear the cached entry
   * once the fetched history contains the pending text.
   *
   * Returns true when an unconfirmed pending message was patched in (the
   * history is incomplete and must not be treated as canonical).
   */
  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): boolean {
    const cached = loadPendingUserMessage(backendSessionId);
    if (!cached || !cached.text) {
      if (!generating) clearPendingUserMessage(backendSessionId);
      return false;
    }

    // When the chat is idle, clear the cache only after the fetched
    // history actually contains the pending text. Clearing
    // unconditionally lost the last message in two windows: POST sent
    // but the run not registered yet (status still "idle"), and
    // generation completed but the memory flush not finished.
    if (!generating) {
      let lastUserText = "";
      let lastUserClientMessageId: string | undefined;
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role !== ROLE_USER) continue;
        const input = messages[i]?.cards?.[0]?.data?.input?.[0];
        lastUserText = extractTextFromContent(input?.content);
        lastUserClientMessageId = extractClientMessageId(input?.metadata);
        break;
      }
      const persistenceConfirmed = cached.clientMessageId
        ? lastUserClientMessageId === cached.clientMessageId
        : lastUserText.trim() === cached.text.trim();
      if (persistenceConfirmed) {
        clearPendingUserMessage(backendSessionId);
        return false;
      }
      // History is missing the turn — fall through and patch it in,
      // keeping the cache until a later fetch confirms persistence.
    }

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
    return true;
  }

  private createEmptySession(
    sessionId: string,
    owner: SessionOwnerToken,
  ): ExtendedSession {
    if (this.isActiveOwner(owner)) {
      window.currentSessionId = sessionId;
      window.currentUserId = DEFAULT_USER_ID;
      window.currentChannel = DEFAULT_CHANNEL;
      useTurnUsageStore.getState().setSnapshot(null);
    }
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

  /** Resets window identity globals to their defaults. Called on agent
   *  switch: the globals are otherwise only rewritten when another session
   *  loads, so a new agent would inherit the previous agent's session and
   *  channel (possibly one that has since been deleted). */
  resetWindowIdentity(): void {
    window.currentSessionId = "";
    window.currentUserId = DEFAULT_USER_ID;
    window.currentChannel = DEFAULT_CHANNEL;
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
    // Never persist a temporary local timestamp id. These ids only exist in
    // memory for brand-new chats before the first message is sent; persisting
    // them causes an unknown id to be restored on agent switch.
    if (persistFn && agentId && !isLocalTimestamp(effectiveId)) {
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
    // Window globals can outlive the session they came from (they are only
    // rewritten when another session loads), so trust them only when they
    // still resolve to a session in the current list. After an agent switch
    // the list is reloaded and a stale identity — including a channel that
    // may no longer exist — fails this lookup and falls through to defaults.
    const windowSessionId = window.currentSessionId || "";
    const windowSession = windowSessionId
      ? (this.sessionList.find(
          (s) =>
            (s as ExtendedSession).sessionId === windowSessionId ||
            s.id === windowSessionId,
        ) as ExtendedSession | undefined)
      : undefined;
    if (windowSession?.userId) {
      return {
        sessionId: windowSession.sessionId || "",
        userId: windowSession.userId,
        channel: windowSession.channel || DEFAULT_CHANNEL,
      };
    }
    // A fresh local id is still safe to keep: blank chats are always
    // created on the console channel.
    return {
      sessionId: isLocalTimestamp(windowSessionId) ? windowSessionId : "",
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
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
        a.createdAt !== b.createdAt ||
        a.pinned !== b.pinned ||
        a.generating !== b.generating ||
        a.realId !== b.realId ||
        a.sessionId !== b.sessionId ||
        a.userId !== b.userId ||
        a.channel !== b.channel ||
        a.archivedAt !== b.archivedAt ||
        a.archived !== b.archived ||
        a.source !== b.source ||
        a.groupId !== b.groupId ||
        a.parentSessionId !== b.parentSessionId ||
        a.rootSessionId !== b.rootSessionId
      ) {
        return false;
      }
    }
    return true;
  }

  async getSessionList() {
    // Reuse an in-flight request only within the same ownership epoch, so a
    // new agent never awaits a list request started by a previous agent.
    if (
      this.sessionListRequest &&
      this.isActiveOwner(this.sessionListRequest.owner)
    ) {
      return this.sessionListRequest.promise;
    }

    const owner = this.getActiveOwner();
    const entry = { owner } as {
      owner: SessionOwnerToken;
      promise: Promise<IAgentScopeRuntimeWebUISession[]>;
    };
    entry.promise = (async () => {
      try {
        const chats = await api.listChats({
          archived: false,
          include_app_owned: false,
        });
        // A result from a stale epoch must not replace the current agent's
        // session list; hand back the current list without mutation.
        if (!this.isActiveOwner(owner)) {
          return this._prevReturnedList ?? [...this.sessionList];
        }
        return this.applyChatsToSessionList(chats);
      } finally {
        if (this.sessionListRequest === entry) this.sessionListRequest = null;
      }
    })();
    this.sessionListRequest = entry;

    return entry.promise;
  }

  /**
   * Track both displayId and realId of the last selected session to avoid
   * duplicate onSessionSelected calls when the same session is loaded via
   * either its displayId or realId (issue #4557).
   */
  private lastSelectedIds: Set<string> = new Set();

  async getSession(sessionId: string, signal?: AbortSignal) {
    const owner = this.getActiveOwner();

    // Check short-lived result cache first (populated by preloadSession).
    // Entries from a previous ownership epoch are never served.
    const cached = this.sessionResultCache.get(sessionId);
    if (cached && this.isActiveOwner(cached.owner)) return cached.session;

    // Reuse an in-flight request only within the same ownership epoch, so a
    // new agent never adopts a request (and its captured owner) started by a
    // previous agent.
    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest && this.isActiveOwner(existingRequest.owner)) {
      return existingRequest.promise;
    }

    const requestPromise = this._doGetSession(sessionId, signal, owner);
    const entry = { promise: requestPromise, owner };
    this.sessionRequests.set(sessionId, entry);

    try {
      const session = await requestPromise;
      const extendedSession = session as ExtendedSession;
      const realId = extendedSession.realId || null;

      // Only trigger onSessionSelected if the result still belongs to the
      // active ownership epoch and neither the displayId nor the realId has
      // already been selected. The latter prevents the infinite loop where
      // displayId and realId alternate triggering onSessionSelected.
      if (this.isActiveOwner(owner) && !this.lastSelectedIds.has(sessionId)) {
        this.lastSelectedIds.clear();
        this.lastSelectedIds.add(sessionId);
        if (realId) this.lastSelectedIds.add(realId);
        this.onSessionSelected?.(sessionId, realId);
      }
      return session;
    } finally {
      // Delete by entry identity so a stale request cannot remove a newer
      // epoch's in-flight entry stored under the same key.
      if (this.sessionRequests.get(sessionId) === entry) {
        this.sessionRequests.delete(sessionId);
      }
    }
  }

  /**
   * Fetch chat history from backend and build an ExtendedSession.
   * Centralises the repeated fetch-convert-patch-build pattern used by
   * _doGetSession in multiple branches. Construction is applied to shared
   * state (window identity, turn-usage store, converted cache) only while
   * the caller's owner epoch is still active.
   */
  private async fetchAndBuildSession(
    displayId: string,
    backendId: string,
    listEntry: ExtendedSession | undefined,
    signal: AbortSignal | undefined,
    owner: SessionOwnerToken,
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
        this.applySessionView(cached, owner);
        return cached;
      }
    }

    const chatHistory = await api.getChat(backendId, {
      signal,
      include_app_owned: false,
    });
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const generating = isGenerating(chatHistory);
    const messages = convertMessages(chatHistory.messages || []);
    const patchedPending = this.patchLastUserMessage(
      messages,
      generating,
      backendId,
    );

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

    // Cache non-generating sessions — only within the epoch that fetched
    // them, so a stale load cannot write into the new agent's cache.
    // A history patched with an unconfirmed pending message is NOT
    // canonical (the agent reply may still be missing): caching it would
    // keep serving the incomplete turn for the whole cache TTL.
    if (!generating && !patchedPending && this.isActiveOwner(owner)) {
      this.setCachedConvertedSession(
        backendId,
        session,
        listEntry?.updatedAt ?? null,
      );
    }

    this.applySessionView(session, owner);
    return session;
  }

  private async _doGetSession(
    sessionId: string,
    signal: AbortSignal | undefined,
    owner: SessionOwnerToken,
  ): Promise<IAgentScopeRuntimeWebUISession> {
    // --- No session selected (library bug: createSession sets undefined) ---
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      if (this.isActiveOwner(owner)) {
        useTurnUsageStore.getState().setSnapshot(null);
      }
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
            owner,
          );
        } catch (error) {
          // If fetching with realId fails, return the local session without messages
          // This handles cases where the backend has an inconsistency
          this.applySessionView(fromList, owner);
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
              owner,
            );
          } catch {
            this.applySessionView(resolved, owner);
            return resolved;
          }
        }
      }
      if (fromList) {
        this.applySessionView(fromList, owner);
        return fromList;
      }
      return this.createEmptySession(sessionId, owner);
    }

    // --- Regular backend UUID ---
    try {
      return await this.fetchAndBuildSession(
        sessionId,
        sessionId,
        this.findSession(sessionId),
        signal,
        owner,
      );
    } catch (error: any) {
      // If the backend session doesn't exist (e.g. invalid UUID or expired session)
      // return an empty session to prevent repeated 404 API calls.
      // Note: the request layer throws Error(message) without attaching .status,
      // so only message-based detection is reliable here.
      if (error.message?.includes("Chat not found")) {
        const emptySession = this.createEmptySession(sessionId, owner);
        emptySession.id = sessionId;
        return emptySession;
      }
      throw error;
    }
  }

  /**
   * After fetching the latest session list, try to resolve a local timestamp
   * session to its real backend UUID and notify listeners. Skipped entirely
   * when the ownership epoch the resolution was started under is no longer
   * active: a late resolution from a previous agent must neither rewrite the
   * current agent's session list nor fire onSessionIdResolved into its view.
   */
  private resolveAndNotify(tempId: string, owner: SessionOwnerToken): void {
    if (!this.isActiveOwner(owner)) return;
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
    const owner = this.getActiveOwner();
    // Force a fresh listChats request: if a stale in-flight getSessionList
    // (started before the POST) is still pending, its response won't contain
    // the new backend session yet. Sharing that stale promise would cause
    // resolveRealId to silently fail and onSessionIdResolved never fires,
    // leaving the URL at /chat instead of /chat/<uuid>.
    this.sessionListRequest = null;
    const promise = this.getSessionList()
      .then(() => this.resolveAndNotify(tempId, owner))
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

    const localId = `${Date.now()}-${randomBase36(7)}`;
    const extended = this.createEmptySession(localId, this.getActiveOwner());
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

const sessionApi = new SessionApi();

// Ownership follows the selected agent from the agent store. Claiming here —
// at module load and synchronously inside every store update — guarantees a
// single lifecycle location and that the epoch advances before any React
// re-render or effect can start new-agent session work, regardless of which
// page (chat, settings, sidebar preload) triggers the change.
sessionApi.setActiveAgent(useAgentStore.getState().selectedAgent);
useAgentStore.subscribe((state) => {
  sessionApi.setActiveAgent(state.selectedAgent);
});

export default sessionApi;

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
