import type { RefObject } from "react";
import {
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
  IAgentScopeRuntimeWebUIRef,
  IAgentScopeRuntimeWebUIInputData,
} from "@agentscope-ai/chat";
import api, {
  type ChatSpec,
  type ChatHistory,
  type Message,
} from "../../../api";
import type { ChatStatus } from "../../../api/types/chat";
import { toDisplayUrl } from "../utils";

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
const CHAT_HISTORY_PAGE_SIZE = 80;
const RUNNING_EMPTY_HISTORY_RETRY_COUNT = 40;
const RUNNING_EMPTY_HISTORY_RETRY_DELAY_MS = 500;

type ChatsListPayload =
  | ChatSpec[]
  | {
      chats?: ChatSpec[];
      data?: ChatSpec[];
      items?: ChatSpec[];
    };

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
export interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
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
}

// ---------------------------------------------------------------------------
// Message conversion helpers: backend flat messages → card-based UI format
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

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
  return (content as ContentItem[]).map(resolveContentItemUrl);
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
  const contentParts = contentToRequestParts(msg.content);
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
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );

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
    name: chat.name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
    status: chat.status ?? "idle",
    createdAt: chat.created_at ?? null,
  }) as ExtendedSession;

/** Returns true when id is a pure numeric local timestamp (not a backend UUID). */
const isLocalTimestamp = (id: string): boolean => /^\d+$/.test(id);

const isGenerating = (chatHistory: ChatHistory): boolean => {
  if (chatHistory.status === "running") return true;
  if (chatHistory.status === "idle") return false;
  const msgs = chatHistory.messages || [];
  if (msgs.length === 0) return false;
  const last = msgs[msgs.length - 1];
  return last.role === ROLE_USER;
};

const STORAGE_PREFIX = "copaw_pending_user_msg_";

function savePendingUserMessage(sessionId: string, text: string): void {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${sessionId}`, text);
  } catch {
    // Ignore storage quota errors.
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
    // Ignore storage failures.
  }
}

function extractTextFromContent(content: unknown): string {
  if (typeof content === "string") {
    return content.trim();
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .filter(
      (part) =>
        typeof part === "object" &&
        part !== null &&
        (part as { type?: string }).type === "text" &&
        typeof (part as { text?: unknown }).text === "string",
    )
    .map((part) => ((part as { text?: string }).text || "").trim())
    .filter(Boolean)
    .join("\n")
    .trim();
}

function extractTextFromUserCardMessage(message: IAgentScopeRuntimeWebUIMessage): string {
  const firstCard = message.cards?.[0];
  if (!firstCard || typeof firstCard !== "object") return "";
  const cardData = (firstCard as { data?: unknown }).data;
  if (!cardData || typeof cardData !== "object") return "";
  const input = (cardData as { input?: Array<{ content?: unknown }> }).input;
  if (!Array.isArray(input) || input.length === 0) return "";
  return extractTextFromContent(input[0]?.content);
}

function hasInjectedUserMessage(
  messages: IAgentScopeRuntimeWebUIMessage[],
  cachedText: string,
): boolean {
  const normalizedCached = cachedText.trim();
  if (!normalizedCached) return false;

  return messages.some((msg) => {
    if (msg.role !== ROLE_USER) return false;
    return extractTextFromUserCardMessage(msg) === normalizedCached;
  });
}

let lastLocalSessionId = 0;

function generateLocalSessionId(): string {
  const now = Date.now();
  if (now <= lastLocalSessionId) {
    lastLocalSessionId += 1;
  } else {
    lastLocalSessionId = now;
  }
  return String(lastLocalSessionId);
}

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
  const tempSession = sessionList.find(
    (s) => s.id === tempSessionId,
  ) as ExtendedSession | undefined;
  const realSession = sessionList.find(
    (s) =>
      (s as ExtendedSession).sessionId === tempSessionId && s.id !== tempSessionId,
  ) as ExtendedSession | undefined;
  if (!realSession) return { list: sessionList, realId: null };

  const realUUID = realSession.id;
  if (tempSession) {
    const localMessages = Array.isArray(tempSession.messages)
      ? tempSession.messages
      : [];
    const remoteMessages = Array.isArray(realSession.messages)
      ? realSession.messages
      : [];
    const useLocalMessages =
      localMessages.length > 0 && remoteMessages.length < localMessages.length;

    realSession.messages = useLocalMessages ? localMessages : remoteMessages;
    realSession.meta = Object.keys(tempSession.meta || {}).length
      ? tempSession.meta
      : realSession.meta;
  }

  // Keep the timestamp as id (so the library's currentSessionId still matches),
  // and store the real UUID in realId for backend requests.
  const pendingUserText = loadPendingUserMessage(tempSessionId);
  if (pendingUserText) {
    savePendingUserMessage(realUUID, pendingUserText);
  }
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
   * When set, getSessionList will move the matching session to the front on the first call,
   * so the library's useMount auto-selects it instead of always defaulting to sessions[0].
   * Cleared after first use.
   */
  preferredChatId: string | null = null;

  /**
   * Cache the latest user message for a chat so it can be patched into
   * history during reconnect (the backend only persists it after generation
   * completes). Persisted to sessionStorage so it survives page refresh.
   */
  setLastUserMessage(sessionId: string, text: string): void {
    if (!sessionId || !text) return;
    savePendingUserMessage(sessionId, text);
  }

  private pickRicherMessages(
    current: IAgentScopeRuntimeWebUIMessage[] | undefined,
    next: IAgentScopeRuntimeWebUIMessage[] | undefined,
  ): IAgentScopeRuntimeWebUIMessage[] {
    const currentMessages = Array.isArray(current) ? current : [];
    const nextMessages = Array.isArray(next) ? next : [];
    return currentMessages.length >= nextMessages.length
      ? currentMessages
      : nextMessages;
  }

  private findSessionByAnyId(sessionId: string): ExtendedSession | undefined {
    return this.sessionList.find((s) => {
      const ext = s as ExtendedSession;
      return (
        s.id === sessionId ||
        ext.realId === sessionId ||
        ext.sessionId === sessionId
      );
    }) as ExtendedSession | undefined;
  }

  private normalizeChatList(payload: ChatsListPayload): ChatSpec[] {
    if (Array.isArray(payload)) {
      return payload;
    }
    if (Array.isArray(payload.chats)) {
      return payload.chats;
    }
    if (Array.isArray(payload.data)) {
      return payload.data;
    }
    if (Array.isArray(payload.items)) {
      return payload.items;
    }
    return [];
  }

  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): void {
    const aliasSession = this.sessionList.find(
      (s) => (s as ExtendedSession).realId === backendSessionId,
    ) as ExtendedSession | undefined;
    const aliasId = aliasSession?.id;

    if (!generating) {
      clearPendingUserMessage(backendSessionId);
      if (aliasId) {
        clearPendingUserMessage(aliasId);
      }
      return;
    }

    const cachedText =
      loadPendingUserMessage(backendSessionId) ||
      (aliasId ? loadPendingUserMessage(aliasId) : "");
    if (!cachedText) return;

    if (hasInjectedUserMessage(messages, cachedText)) {
      return;
    }

    const lastUserIndex = [...messages]
      .map((message, index) => ({ message, index }))
      .reverse()
      .find(({ message }) => message.role === ROLE_USER)?.index;

    // Only inject the cached user turn when no user card exists yet.
    // If a user card already exists, avoid appending another one at the tail,
    // otherwise assistant output may appear before a duplicated user turn.
    if (lastUserIndex === undefined) {
      messages.push(
        buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message),
      );
      return;
    }

    const lastUserMessage = messages[lastUserIndex] as RuntimeUiMessageLike;
    const existingText = extractTextFromContent(
      lastUserMessage.cards?.[0]?.data &&
        typeof lastUserMessage.cards[0].data === "object" &&
        (lastUserMessage.cards[0].data as { input?: Array<{ content?: unknown }> }).input?.[0]?.content,
    );
    if (!existingText) {
      lastUserMessage.cards =
        buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        } as Message).cards;
    }
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
   *
   * Ref to the chat component so we can trigger submit with reconnect flag
   * (library will call customFetch with biz_params.reconnect and consume the SSE stream).
   */
  private chatRef: RefObject<IAgentScopeRuntimeWebUIRef> | null = null;

  setChatRef(ref: RefObject<IAgentScopeRuntimeWebUIRef> | null): void {
    this.chatRef = ref;
  }

  /**
   * Programmatically trigger the library's submit with biz_params.reconnect so
   * customFetch does POST /console/chat with reconnect:true and the library
   * consumes the SSE stream (replay + live tail).
   */
  triggerReconnectSubmit(): void {
    const ref = this.chatRef?.current;
    if (!ref?.input?.submit) {
      console.warn("triggerReconnectSubmit: chatRef not available");
      return;
    }
    ref.input.submit({
      query: "",
      biz_params: {
        reconnect: true,
      } as IAgentScopeRuntimeWebUIInputData["biz_params"],
    });
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
    const local = this.sessionList.find((s) => s.id === sessionId);
    if (local) {
      this.updateWindowVariables(local as ExtendedSession);
      return local;
    }
    return this.createEmptySession(sessionId);
  }

  private async getAllChatMessages(
    chatId: string,
  ): Promise<{ messages: Message[]; status: "idle" | "running" }> {
    const fetchPagedHistory = async (): Promise<{
      messages: Message[];
      status: "idle" | "running";
    }> => {
      const allMessages: Message[] = [];
      let offset = 0;
      let latestStatus: "idle" | "running" = "idle";

      while (true) {
        const chatHistory = await api.getChat(chatId, {
          offset,
          limit: CHAT_HISTORY_PAGE_SIZE,
        });
        const pageMessages = chatHistory.messages || [];
        latestStatus = chatHistory.status ?? latestStatus;

        allMessages.push(...pageMessages);

        const hasMoreByFlag = chatHistory.has_more === true;
        const hasMoreByTotal =
          typeof chatHistory.total === "number"
            ? offset + pageMessages.length < chatHistory.total
            : false;
        const hasMore = hasMoreByFlag || hasMoreByTotal;

        if (!hasMore || pageMessages.length === 0) {
          break;
        }
        offset += pageMessages.length;
      }

      return { messages: allMessages, status: latestStatus };
    };

    let history = await fetchPagedHistory();

    // Newly-created chats can briefly report `running` with empty history.
    // Retry for a short window so first assistant chunks can be observed.
    for (
      let i = 0;
      i < RUNNING_EMPTY_HISTORY_RETRY_COUNT &&
      history.status === "running" &&
      history.messages.length === 0;
      i += 1
    ) {
      await new Promise((resolve) => {
        setTimeout(resolve, RUNNING_EMPTY_HISTORY_RETRY_DELAY_MS);
      });
      history = await fetchPagedHistory();
    }

    return history;
  }

  /**
   * Returns the real backend UUID for a session identified by id (which may be
   * a local timestamp). Returns null when not yet resolved or not found.
   */
  getRealIdForSession(sessionId: string): string | null {
    const s = this.findSessionByAnyId(sessionId);
    return s?.realId ?? null;
  }

  hasLiveMessagesForSession(sessionId: string | undefined): boolean {
    if (!sessionId) {
      return false;
    }
    const targetId =
      this.getRealIdForSession(sessionId) ?? sessionId;
    const session = this.findSessionByAnyId(targetId);

    if (!session || !Array.isArray(session.messages) || session.messages.length === 0) {
      return false;
    }

    const lastMessage = session.messages[session.messages.length - 1] as
      | (IAgentScopeRuntimeWebUIMessage & { msgStatus?: string })
      | undefined;
    if (!lastMessage) {
      return false;
    }

    return lastMessage.msgStatus === "generating";
  }

  async getSessionList() {
    // Deduplicate: reuse the in-flight request if one is already running so
    // concurrent calls don't overwrite sessionList and lose realId mappings.
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        const chatPayload = (await api.listChats()) as ChatsListPayload;
        const chats = this.normalizeChatList(chatPayload);
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

          if (!existing) {
            return s;
          }

          // First resolution moment: backend row (UUID) appears while local
          // timestamp session still owns the freshest in-memory messages.
          if (isLocalTimestamp(existing.id) && !existing.realId) {
            return {
              ...s,
              id: existing.id,
              realId: (s as ExtendedSession).id,
              messages: this.pickRicherMessages(
                existing.messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
                (s as ExtendedSession).messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
              ),
              meta:
                Object.keys(existing.meta || {}).length > 0
                  ? existing.meta
                  : (s as ExtendedSession).meta,
              status: existing.status ?? (s as ExtendedSession).status,
            } as ExtendedSession;
          }

          if (!existing.realId) {
            return {
              ...s,
              messages: this.pickRicherMessages(
                existing.messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
                (s as ExtendedSession).messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
              ),
            } as ExtendedSession;
          }

          const messages = this.pickRicherMessages(
            existing.messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
            (s as ExtendedSession).messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
          );

          return {
            ...s,
            id: existing.id,
            realId: existing.realId,
            messages,
            meta:
              Object.keys(existing.meta || {}).length > 0
                ? existing.meta
                : (s as ExtendedSession).meta,
          } as ExtendedSession;
        });

        // Move the preferred session to the front so the library's useMount
        // auto-selects it, avoiding an unnecessary getSession call for sessions[0].
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
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  /** Track the last session ID that triggered onSessionSelected to avoid duplicate calls. */
  private lastSelectedSessionId: string | null = null;

  async getSession(sessionId: string) {
    // Deduplicate: reuse the in-flight request if one is already running
    // for the same sessionId so concurrent calls share one network request.
    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) return existingRequest;

    const requestPromise = this._doGetSession(sessionId);
    this.sessionRequests.set(sessionId, requestPromise);

    try {
      const session = await requestPromise;
      // Trigger onSessionSelected only when session actually changes
      if (sessionId !== this.lastSelectedSessionId) {
        this.lastSelectedSessionId = sessionId;
        const extendedSession = session as ExtendedSession;
        const realId = extendedSession.realId || null;
        this.onSessionSelected?.(sessionId, realId);
      }
      return session;
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
        const { messages, status } = await this.getAllChatMessages(
          fromList.realId,
        );
        const generating = isGenerating({ status, messages } as ChatHistory);
        const convertedMessages = convertMessages(messages);
        this.patchLastUserMessage(convertedMessages, generating, fromList.realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: fromList.name || DEFAULT_SESSION_NAME,
          sessionId: fromList.sessionId || sessionId,
          userId: fromList.userId || DEFAULT_USER_ID,
          channel: fromList.channel || DEFAULT_CHANNEL,
          messages: convertedMessages,
          meta: fromList.meta || {},
          realId: fromList.realId,
          status,
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
        const { messages, status } = await this.getAllChatMessages(
          refreshed.realId,
        );
        const generating = isGenerating({ status, messages } as ChatHistory);
        const convertedMessages = convertMessages(messages);
        this.patchLastUserMessage(
          convertedMessages,
          generating,
          refreshed.realId,
        );
        const session: ExtendedSession = {
          id: sessionId,
          name: refreshed.name || DEFAULT_SESSION_NAME,
          sessionId: refreshed.sessionId || sessionId,
          userId: refreshed.userId || DEFAULT_USER_ID,
          channel: refreshed.channel || DEFAULT_CHANNEL,
          messages: convertedMessages,
          meta: refreshed.meta || {},
          realId: refreshed.realId,
          status,
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
      return this.createEmptySession(generateLocalSessionId());
    }

    // --- Regular backend UUID ---
    let fromList = this.findSessionByAnyId(sessionId);

    // Ensure metadata is resolved before writing window.currentSessionId.
    // If fromList is missing on first load, we might incorrectly use chat_id
    // as session_id and send /console/chat to a different conversation.
    if (!fromList) {
      await this.getSessionList();
      fromList = this.findSessionByAnyId(sessionId);
    }

    const { messages, status } = await this.getAllChatMessages(sessionId);
    const convertedMessages = convertMessages(messages);
    const generating = isGenerating({ status, messages } as ChatHistory);
    this.patchLastUserMessage(convertedMessages, generating, sessionId);
    const localMessages = Array.isArray(fromList?.messages)
      ? (JSON.parse(JSON.stringify(fromList.messages)) as IAgentScopeRuntimeWebUIMessage[])
      : [];
    const convertedHasUser = convertedMessages.some((m) => m.role === ROLE_USER);
    const localHasUser = localMessages.some((m) => m.role === ROLE_USER);
    const shouldUseLocalFallback =
      localMessages.length > 0 &&
      status === "running" &&
      (convertedMessages.length === 0 || (localHasUser && !convertedHasUser));

    const session: ExtendedSession = {
      id: fromList?.id || sessionId,
      name: fromList?.name || sessionId,
      sessionId: fromList?.sessionId || sessionId,
      userId: fromList?.userId || DEFAULT_USER_ID,
      channel: fromList?.channel || DEFAULT_CHANNEL,
      messages: shouldUseLocalFallback ? localMessages : convertedMessages,
      meta: fromList?.meta || {},
      realId: fromList?.realId,
      status,
    };

    this.updateWindowVariables(session);
    return session;
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    const nextSession = { ...session };

    const index = this.sessionList.findIndex((s) => {
      const ext = s as ExtendedSession;
      return (
        s.id === session.id ||
        ext.realId === session.id ||
        ext.sessionId === session.id
      );
    });

    if (index > -1) {
      const existing = this.sessionList[index] as ExtendedSession;
      const mergedMessages = this.pickRicherMessages(
        existing.messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
        nextSession.messages as IAgentScopeRuntimeWebUIMessage[] | undefined,
      );

      this.sessionList[index] = {
        ...existing,
        ...nextSession,
        id: existing.id,
        realId: existing.realId,
        sessionId: existing.sessionId,
        userId: existing.userId,
        channel: existing.channel,
        messages: mergedMessages,
      } as ExtendedSession;

      // Timestamp session without realId yet — resolve in the background
      const updated = this.sessionList[index] as ExtendedSession;
      if (isLocalTimestamp(updated.id) && !updated.realId) {
        const tempId = updated.id;
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
      const tempId = nextSession.id!;
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
    session.id = generateLocalSessionId();

    const extended: ExtendedSession = {
      ...session,
      sessionId: session.id,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
    } as ExtendedSession;

    this.updateWindowVariables(extended);
    // this.sessionList.unshift(extended);
    this.onSessionCreated?.(session.id);
    return this.sessionList;
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

type RuntimeUiMessageLike = IAgentScopeRuntimeWebUIMessage & {
  cards?: Array<{ data?: unknown }>;
  role?: string;
};

export default new SessionApi();
