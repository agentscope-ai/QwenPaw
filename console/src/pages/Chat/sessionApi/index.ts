import type {
  IAgentScopeRuntimeWebUICreateSessionResult,
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import api, {
  type ChatSpec,
  type ChatHistory,
  type ChatContextState,
  type ChatHistoryMetadata,
  type ChatMessagePage,
  type ChatStatus,
  type Message,
  type TranscriptPosition,
} from "../../../api";
import { toDisplayUrl } from "../utils";
import { useAgentStore } from "../../../stores/agentStore";
import {
  extractTurnUsageFromOutputMessages,
  extractLatestSnapshotFromCards,
  type TurnUsageSnapshot,
} from "../turnUsage";
import { takeChatHistoryPrefetch } from "../chatRoutePrefetch";
import { useTurnUsageStore } from "../turnUsageStore";
import { useMessageQueueStore } from "../../../stores/messageQueueStore";
import { syncSessionsGlobal } from "../../../stores/sessionListStore";
import {
  boundHistoryRows,
  splitHistoryMessagesIntoTurnRows,
  type HistoryUserMessage,
} from "../historyMessageWindowStore";

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
const HISTORY_PAGE_TURN_LIMIT = 5;

/** Publish one bounded server page; keep its cursor for the next interaction. */
function readHistoryPage(page: ChatMessagePage, signal?: AbortSignal) {
  signal?.throwIfAborted();
  return { page, messages: convertMessages(page.messages || [], true) };
}

function mergeCachedHistoryPages(
  older: IAgentScopeRuntimeWebUIMessage[],
  newer: IAgentScopeRuntimeWebUIMessage[],
) {
  const messages = boundHistoryRows(
    splitHistoryMessagesIntoTurnRows(mergeHistoryMessages(older, newer)),
    "oldest",
  ).flat();
  // A single turn can exceed the viewport's soft limit. Do not let that
  // exception grow a cached page indefinitely; its cursor remains resumable.
  return JSON.stringify(messages).length * 2 > 8 * 1024 * 1024
    ? older
    : messages;
}

function hydrateTurnUsageFromMessages(
  messages: IAgentScopeRuntimeWebUIMessage[],
  contextState?: ChatContextState | null,
): void {
  useTurnUsageStore.getState().invalidateTurn();
  const snap =
    contextState === undefined
      ? extractLatestSnapshotFromCards(messages)
      : ((contextState?.usage ?? null) as TurnUsageSnapshot | null);
  useTurnUsageStore.getState().setSnapshot(snap);
}

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

const getTranscriptPosition = (
  message?: Pick<Message, "metadata">,
): TranscriptPosition | undefined => {
  const metadata = message?.metadata as Record<string, unknown> | undefined;
  const position = metadata?.qwenpaw_transcript_position;
  if (!position || typeof position !== "object") return undefined;
  const candidate = position as Partial<TranscriptPosition>;
  if (
    typeof candidate.turn_id !== "string" ||
    typeof candidate.turn_seq !== "number" ||
    typeof candidate.ordinal !== "number"
  ) {
    return undefined;
  }
  return candidate as TranscriptPosition;
};

interface HistoryContentFragment {
  content_start: number;
  content_end: number;
  content_total: number;
  text_content_index?: number;
  text_start?: number;
  text_end?: number;
  text_total?: number;
  serialized_start?: number;
  serialized_end?: number;
  serialized_total?: number;
  serialized_fragment?: string;
  serialized_fragments?: string[];
}

type FragmentedMessage = {
  content?: unknown;
  metadata?: unknown;
};

const getHistoryContentFragment = (
  message: FragmentedMessage,
): HistoryContentFragment | undefined => {
  const metadata = message.metadata as Record<string, unknown> | undefined;
  const value = metadata?.qwenpaw_history_fragment;
  if (!value || typeof value !== "object") return undefined;
  const fragment = value as Partial<HistoryContentFragment>;
  if (
    typeof fragment.content_start !== "number" ||
    typeof fragment.content_end !== "number" ||
    typeof fragment.content_total !== "number"
  ) {
    return undefined;
  }
  return fragment as HistoryContentFragment;
};

const mergeContentFragments = <T extends FragmentedMessage>(
  older: T,
  newer: T,
): T | null => {
  const olderFragment = getHistoryContentFragment(older);
  const newerFragment = getHistoryContentFragment(newer);
  if (
    !olderFragment ||
    !newerFragment ||
    olderFragment.content_total !== newerFragment.content_total
  ) {
    return null;
  }

  const serializedParts = (fragment: HistoryContentFragment) => {
    if (
      Array.isArray(fragment.serialized_fragments) &&
      fragment.serialized_fragments.every((part) => typeof part === "string")
    ) {
      return fragment.serialized_fragments;
    }
    return typeof fragment.serialized_fragment === "string"
      ? [fragment.serialized_fragment]
      : null;
  };
  const olderSerialized = serializedParts(olderFragment);
  const newerSerialized = serializedParts(newerFragment);
  const serializedFragment =
    olderSerialized !== null &&
    newerSerialized !== null &&
    olderFragment.serialized_total === newerFragment.serialized_total &&
    olderFragment.serialized_end === newerFragment.serialized_start &&
    olderFragment.content_start === newerFragment.content_start &&
    olderFragment.content_end === newerFragment.content_end;
  if (serializedFragment) {
    const fragments = [...olderSerialized, ...newerSerialized];
    const position: HistoryContentFragment = {
      ...newerFragment,
      serialized_start: olderFragment.serialized_start,
      serialized_fragments: fragments,
    };
    delete position.serialized_fragment;
    let content: unknown[] = [];
    if (
      position.serialized_start === 0 &&
      position.serialized_end === position.serialized_total
    ) {
      try {
        content = [JSON.parse(fragments.join(""))];
      } catch {
        return null;
      }
      delete position.serialized_start;
      delete position.serialized_end;
      delete position.serialized_total;
      delete position.serialized_fragment;
      delete position.serialized_fragments;
    }
    return {
      ...newer,
      content,
      metadata: {
        ...((newer.metadata as Record<string, unknown> | null) ?? {}),
        qwenpaw_history_fragment: position,
      },
    };
  }

  const olderContent = Array.isArray(older.content) ? older.content : null;
  const newerContent = Array.isArray(newer.content) ? newer.content : null;
  if (!olderContent || !newerContent) return null;

  const textFragment =
    olderFragment.text_content_index === newerFragment.text_content_index &&
    olderFragment.text_total === newerFragment.text_total &&
    olderFragment.text_end === newerFragment.text_start &&
    olderFragment.content_start === newerFragment.content_start &&
    olderFragment.content_end === newerFragment.content_end &&
    olderContent.length === 1 &&
    newerContent.length === 1;
  if (textFragment) {
    const olderBlock = olderContent[0] as Record<string, unknown>;
    const newerBlock = newerContent[0] as Record<string, unknown>;
    if (
      typeof olderBlock?.text !== "string" ||
      typeof newerBlock?.text !== "string"
    ) {
      return null;
    }
    const position = {
      ...newerFragment,
      text_start: olderFragment.text_start,
    };
    if (
      position.text_start === 0 &&
      position.text_end === position.text_total
    ) {
      delete position.text_content_index;
      delete position.text_start;
      delete position.text_end;
      delete position.text_total;
    }
    return {
      ...newer,
      content: [
        {
          ...newerBlock,
          text: olderBlock.text + newerBlock.text,
        },
      ],
      metadata: {
        ...((newer.metadata as Record<string, unknown> | null) ?? {}),
        qwenpaw_history_fragment: position,
      },
    };
  }

  if (olderFragment.content_end !== newerFragment.content_start) return null;
  const metadata = {
    ...((newer.metadata as Record<string, unknown> | null) ?? {}),
    qwenpaw_history_fragment: {
      content_start: olderFragment.content_start,
      content_end: newerFragment.content_end,
      content_total: newerFragment.content_total,
    },
  };
  return {
    ...newer,
    content: [...olderContent, ...newerContent],
    metadata,
  };
};

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
  /** ISO 8601 completion time of the most recent task. */
  lastFinishedAt?: string | null;
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
  parentChatId?: string | null;
  forkTurnId?: string | null;
  forkTurnSeq?: number | null;
  /** Cursor state for loading older durable transcript pages. */
  historyPage?: ChatHistoryMetadata;
  /** Current model-context state, independent from historical messages. */
  contextState?: ChatContextState | null;
}

export interface SessionIdentity {
  sdkSessionId: string;
  chatId?: string;
  sessionId: string;
  userId: string;
  channel: string;
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

/**
 * Parse a metadata time string (e.g. "2026-05-27 10:44:53.362") to unix
 * seconds; returns 0 when the value is absent or not parseable.
 */
const metadataTimeToSeconds = (ts: unknown): number => {
  if (!ts || typeof ts !== "string") return 0;
  const ms = new Date(ts.replace(" ", "T")).getTime();
  return Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
};

/** Parse metadata.timestamp string (e.g. "2026-05-27 10:44:53.362") to unix seconds. */
const parseTimestamp = (msg: Record<string, unknown>): number =>
  metadataTimeToSeconds((msg.metadata as Record<string, unknown>)?.timestamp);

/**
 * Parse metadata.finished_at string to unix seconds (0 when absent).
 * `finished_at` is stamped when the reply actually ended; `timestamp` is
 * the created_at alias pinned at the first saved segment, which can be far
 * earlier for turns with long tool calls.
 */
const parseFinishedAt = (msg: Record<string, unknown>): number =>
  metadataTimeToSeconds((msg.metadata as Record<string, unknown>)?.finished_at);

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
  terminal?: { status?: string; error?: unknown; finished_at?: string },
  turnId?: string,
  userTimestamp = 0,
): IAgentScopeRuntimeWebUIMessage => {
  const fallbackNow = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, m) => Math.max(max, m.sequence_number || 0),
    0,
  );

  const firstTs = outputMessages.length ? parseTimestamp(outputMessages[0]) : 0;
  const lastTs = outputMessages.length
    ? parseTimestamp(outputMessages[outputMessages.length - 1])
    : 0;
  // Prefer the real reply-end time (finished_at) over timestamp so turns
  // with long tool calls show the true completion time (#6826). Falls
  // back to timestamp for legacy sessions without the stamp.
  const finishedAt = outputMessages.reduce(
    (max, m) => Math.max(max, parseFinishedAt(m)),
    0,
  );

  const normalizedMessages = outputMessages.map((msg) => ({
    ...msg,
    content: normalizeOutputMessageContent(msg.content),
  }));

  const turnUsage = extractTurnUsageFromOutputMessages(outputMessages);
  const messageId = turnId ? `history-turn:${turnId}` : generateId();

  return {
    id: messageId,
    role: ROLE_ASSISTANT,
    cards: [
      {
        code: CARD_RESPONSE,
        data: {
          id: turnId
            ? `history-response:${turnId}`
            : `response_${generateId()}`,
          output: normalizedMessages,
          object: "response",
          status: terminal?.status || "completed",
          created_at: firstTs || userTimestamp || fallbackNow,
          sequence_number: maxSeq + 1,
          error: terminal?.error ?? null,
          completed_at:
            metadataTimeToSeconds(terminal?.finished_at) ||
            finishedAt ||
            lastTs ||
            userTimestamp ||
            fallbackNow,
          usage: turnUsage?.usage ?? null,
          context_usage: turnUsage?.context_usage ?? null,
        },
      },
    ],
    msgStatus: terminal?.status === "canceled" ? "interrupted" : "finished",
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
  history = false,
): IAgentScopeRuntimeWebUIMessage[] => {
  const sourceMessages = history
    ? messages.map((message) => {
        const metadata =
          message.metadata &&
          typeof message.metadata === "object" &&
          !Array.isArray(message.metadata)
            ? (message.metadata as Record<string, unknown>)
            : {};
        return {
          ...message,
          metadata: {
            ...metadata,
            qwenpaw_history: true,
          },
        };
      })
    : messages;
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  const len = sourceMessages.length;
  let i = 0;

  while (i < len) {
    let terminal:
      | { status?: string; error?: unknown; finished_at?: string }
      | undefined;
    let userTimestamp = 0;
    let turnId: string | undefined;
    if (sourceMessages[i].role === ROLE_USER) {
      const user = sourceMessages[i++];
      userTimestamp = parseTimestamp(user);
      const meta = user.metadata as Record<string, unknown> | undefined;
      const nested = meta?.metadata;
      const stateMetadata =
        nested && typeof nested === "object"
          ? (nested as Record<string, unknown>)
          : meta;
      terminal = stateMetadata?.qwenpaw_turn_state as
        | { status?: string; error?: unknown; finished_at?: string }
        | undefined;
      turnId = getTranscriptPosition(user)?.turn_id;
      result.push(buildUserCard(user));
    }
    const startIdx = i;
    turnId ??= getTranscriptPosition(sourceMessages[i])?.turn_id;
    while (i < len && sourceMessages[i].role !== ROLE_USER) {
      const candidateTurnId = getTranscriptPosition(sourceMessages[i])?.turn_id;
      if (turnId && candidateTurnId && candidateTurnId !== turnId) break;
      i++;
    }
    const outputMsgs = sourceMessages.slice(startIdx, i).map(toOutputMessage);
    if (
      outputMsgs.length ||
      terminal?.status === "failed" ||
      terminal?.status === "canceled"
    ) {
      result.push(
        buildResponseCard(outputMsgs, terminal, turnId, userTimestamp),
      );
    }
  }

  return history
    ? result.map((message) => ({ ...message, history: true }))
    : result;
};

type ResponseCardData = Record<string, unknown> & {
  output?: OutputMessage[];
  created_at?: number;
  completed_at?: number;
};

const responseCardData = (
  message: IAgentScopeRuntimeWebUIMessage,
): ResponseCardData | undefined => {
  const cards = message.cards as
    | Array<{ code?: string; data?: ResponseCardData }>
    | undefined;
  return cards?.find((card) => card.code === CARD_RESPONSE)?.data;
};

type RequestCardData = Record<string, unknown> & {
  input?: FragmentedMessage[];
};

const requestCardData = (
  message: IAgentScopeRuntimeWebUIMessage,
): RequestCardData | undefined => {
  const cards = message.cards as
    | Array<{ code?: string; data?: RequestCardData }>
    | undefined;
  return cards?.find((card) => card.code === "AgentScopeRuntimeRequestCard")
    ?.data;
};

const mergeRequestMessages = (
  older: IAgentScopeRuntimeWebUIMessage,
  newer: IAgentScopeRuntimeWebUIMessage,
): IAgentScopeRuntimeWebUIMessage => {
  const olderData = requestCardData(older);
  const newerData = requestCardData(newer);
  const olderInput = olderData?.input?.[0];
  const newerInput = newerData?.input?.[0];
  if (!olderData || !newerData || !olderInput || !newerInput) return newer;
  const mergedInput =
    mergeContentFragments(olderInput, newerInput) ||
    mergeContentFragments(newerInput, olderInput);
  if (!mergedInput) return newer;
  const cards = (
    newer.cards as Array<{ code: string; data?: RequestCardData }>
  ).map((card) =>
    card.code === "AgentScopeRuntimeRequestCard"
      ? {
          ...card,
          data: {
            ...olderData,
            ...newerData,
            created_at: Math.min(
              Number(olderData.created_at ?? Number.MAX_SAFE_INTEGER),
              Number(newerData.created_at ?? Number.MAX_SAFE_INTEGER),
            ),
            input: [mergedInput],
          },
        }
      : card,
  );
  return {
    ...newer,
    cards,
    history:
      (older as { history?: boolean }).history ||
      (newer as { history?: boolean }).history,
  } as IAgentScopeRuntimeWebUIMessage & { history?: boolean };
};

const outputIdentity = (message: OutputMessage): string => {
  if (typeof message.id === "string" && message.id) return message.id;
  const position = getTranscriptPosition(message);
  if (position) return `${position.turn_id}:${position.ordinal}`;
  return JSON.stringify(message);
};

const mergeResponseMessages = (
  older: IAgentScopeRuntimeWebUIMessage,
  newer: IAgentScopeRuntimeWebUIMessage,
): IAgentScopeRuntimeWebUIMessage => {
  const olderData = responseCardData(older);
  const newerData = responseCardData(newer);
  if (!olderData || !newerData) return newer;
  const output = new Map<string, OutputMessage>();
  for (const message of [
    ...(olderData.output ?? []),
    ...(newerData.output ?? []),
  ]) {
    const identity = outputIdentity(message);
    const previous = output.get(identity);
    output.set(
      identity,
      (previous &&
        (mergeContentFragments(previous, message) ||
          mergeContentFragments(message, previous))) ||
        message,
    );
  }
  const sortedOutput = [...output.values()].sort((left, right) => {
    const leftPosition = getTranscriptPosition(left);
    const rightPosition = getTranscriptPosition(right);
    if (!leftPosition || !rightPosition) return 0;
    return (
      leftPosition.turn_seq - rightPosition.turn_seq ||
      leftPosition.ordinal - rightPosition.ordinal
    );
  });
  const olderStatus = String(olderData.status ?? "");
  const preserveOlderTerminal = ["failed", "canceled"].includes(olderStatus);
  const status = preserveOlderTerminal ? olderData.status : newerData.status;
  const error = preserveOlderTerminal ? olderData.error : newerData.error;
  const cards = (
    newer.cards as Array<{
      code: string;
      data?: ResponseCardData;
    }>
  ).map((card) =>
    card.code === CARD_RESPONSE
      ? {
          ...card,
          data: {
            ...olderData,
            ...newerData,
            status,
            error,
            output: sortedOutput,
            created_at: Math.min(
              olderData.created_at ?? Number.MAX_SAFE_INTEGER,
              newerData.created_at ?? Number.MAX_SAFE_INTEGER,
            ),
            completed_at: Math.max(
              olderData.completed_at ?? 0,
              newerData.completed_at ?? 0,
            ),
          },
        }
      : card,
  );
  const olderHistory = (older as { history?: boolean }).history;
  const newerHistory = (newer as { history?: boolean }).history;
  return {
    ...newer,
    cards,
    msgStatus: status === "canceled" ? "interrupted" : "finished",
    history: olderHistory || newerHistory,
  } as IAgentScopeRuntimeWebUIMessage & { history?: boolean };
};

export const mergeHistoryMessages = (
  older: IAgentScopeRuntimeWebUIMessage[],
  newer: IAgentScopeRuntimeWebUIMessage[],
): IAgentScopeRuntimeWebUIMessage[] => {
  const merged = [...older];
  const positions = new Map(
    merged.map((message, index) => [message.id, index]),
  );
  for (const message of newer) {
    const index = positions.get(message.id);
    if (index === undefined) {
      positions.set(message.id, merged.length);
      merged.push(message);
    } else if (message.role === ROLE_ASSISTANT) {
      merged[index] = mergeResponseMessages(merged[index], message);
    } else if (message.role === ROLE_USER) {
      merged[index] = mergeRequestMessages(merged[index], message);
    }
  }
  const position = (message: IAgentScopeRuntimeWebUIMessage) => {
    const raw =
      responseCardData(message)?.output?.[0] ??
      requestCardData(message)?.input?.[0];
    return raw ? getTranscriptPosition(raw as Message) : undefined;
  };
  return merged.sort((left, right) => {
    const a = position(left);
    const b = position(right);
    return a && b ? a.turn_seq - b.turn_seq || a.ordinal - b.ordinal : 0;
  });
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
    generating: chat.status === "running",
    createdAt: chat.created_at ?? null,
    updatedAt: chat.updated_at ?? null,
    lastFinishedAt: chat.last_finished_at ?? null,
    pinned: chat.pinned ?? false,
    source: chat.source ?? "chat",
    groupId: chat.group_id ?? null,
    parentSessionId: chat.parent_session_id ?? null,
    rootSessionId: chat.root_session_id ?? null,
    parentChatId: chat.parent_chat_id ?? null,
    forkTurnId: chat.fork_turn_id ?? null,
    forkTurnSeq: chat.fork_turn_seq ?? null,
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

  /** Durable transcript cursor state, keyed by canonical backend chat ID. */
  private historyPages = new Map<string, ChatHistoryMetadata>();

  /** Coalesce repeated top-scroll events while one page is in flight. */
  private historyPageRequests = new Map<
    string,
    Promise<{ messages: IAgentScopeRuntimeWebUIMessage[]; noMore: boolean }>
  >();

  /** Loaded transcript pages, newest first. Only adjacent pages are exposed
   *  to the SDK so durable history can grow without growing the message DOM. */
  private historyWindows = new Map<
    string,
    {
      pages: IAgentScopeRuntimeWebUIMessage[][];
      activeIndex: number;
      forwardFragment?: { boundary: string; before: string };
      latestBeforeAnchor?: {
        messages: IAgentScopeRuntimeWebUIMessage[];
        page: ChatHistoryMetadata | undefined;
      };
    }
  >();

  private setHistoryPage(backendId: string, page: ChatHistoryMetadata): void {
    this.historyPages.set(backendId, page);
  }

  private getHistoryBackendId(sessionId: string): string {
    return this.findSession(sessionId)?.realId ?? sessionId;
  }

  private renderHistoryWindow(
    backendId: string,
  ): IAgentScopeRuntimeWebUIMessage[] {
    const state = this.historyWindows.get(backendId);
    if (!state) return [];
    const current = state.pages[state.activeIndex] ?? [];
    const newer = state.pages[state.activeIndex - 1] ?? [];
    // Keep only the adjoining boundary message for scroll anchoring and a
    // turn fragment that crosses the cursor. Mounting the whole newer page
    // would double the DOM budget for every history step.
    return mergeHistoryMessages(current, newer.slice(0, 1));
  }

  private resetHistoryWindow(
    backendId: string,
    messages: IAgentScopeRuntimeWebUIMessage[],
  ): void {
    this.historyWindows.set(backendId, {
      pages: [messages],
      activeIndex: 0,
    });
  }

  /** Capture live additions before leaving the newest history page. */
  syncVisibleHistory(
    sessionId: string,
    messages: IAgentScopeRuntimeWebUIMessage[],
  ): void {
    const backendId = this.getHistoryBackendId(sessionId);
    const state = this.historyWindows.get(backendId);
    if (!state || state.activeIndex !== 0) return;
    state.pages[0] = messages;
  }

  /** Move one loaded page towards the newest messages without a request. */
  loadNewerHistory(sessionId: string): {
    messages: IAgentScopeRuntimeWebUIMessage[];
    atLatest: boolean;
    canLoadOlder: boolean;
  } | null {
    const backendId = this.getHistoryBackendId(sessionId);
    const state = this.historyWindows.get(backendId);
    if (!state || state.activeIndex === 0) return null;
    state.activeIndex--;
    const page = this.historyPages.get(backendId);
    return {
      messages: this.renderHistoryWindow(backendId),
      atLatest: state.activeIndex === 0,
      canLoadOlder:
        state.activeIndex + 1 < state.pages.length || Boolean(page?.has_more),
    };
  }

  /** Restore the newest loaded page before starting or reconnecting a run. */
  showLatestHistory(
    sessionId: string,
  ): IAgentScopeRuntimeWebUIMessage[] | null {
    const backendId = this.getHistoryBackendId(sessionId);
    const state = this.historyWindows.get(backendId);
    if (!state) return null;
    if (state.latestBeforeAnchor) {
      const { messages, page } = state.latestBeforeAnchor;
      this.resetHistoryWindow(backendId, messages);
      if (page) this.setHistoryPage(backendId, page);
      else this.historyPages.delete(backendId);
      return messages;
    }
    state.activeIndex = 0;
    return this.renderHistoryWindow(backendId);
  }

  private getCachedConvertedSession(
    backendId: string,
    currentUpdatedAt?: string | null,
  ): ExtendedSession | null {
    const entry = this.convertedSessionCache.get(backendId);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > SessionApi.CONVERTED_CACHE_TTL) {
      this.convertedSessionCache.delete(backendId);
      this.historyPages.delete(backendId);
      this.historyWindows.delete(backendId);
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
      this.historyPages.delete(backendId);
      this.historyWindows.delete(backendId);
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
      if (oldestKey) {
        this.convertedSessionCache.delete(oldestKey);
        this.historyPages.delete(oldestKey);
        this.historyWindows.delete(oldestKey);
      }
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
    this.historyPages.delete(backendId);
    this.historyPageRequests.delete(backendId);
    this.historyWindows.delete(backendId);
  }

  /** Load and convert one older durable transcript page. */
  async loadOlderHistory(
    sessionId: string,
    signal?: AbortSignal,
    accumulate = false,
    beforeMessageId?: string,
  ): Promise<{
    messages: IAgentScopeRuntimeWebUIMessage[];
    noMore: boolean;
  }> {
    const entry = this.findSession(sessionId) as ExtendedSession | undefined;
    const backendId = entry?.realId ?? sessionId;
    const window = this.historyWindows.get(backendId);
    if (
      !beforeMessageId &&
      window &&
      window.activeIndex + 1 < window.pages.length
    ) {
      const olderIndex = window.activeIndex + 1;
      if (accumulate) {
        window.pages[window.activeIndex] = mergeCachedHistoryPages(
          window.pages[olderIndex],
          window.pages[window.activeIndex],
        );
        window.pages.splice(olderIndex, 1);
      } else {
        window.activeIndex = olderIndex;
      }
      return {
        messages: this.renderHistoryWindow(backendId),
        noMore:
          window.activeIndex === window.pages.length - 1 &&
          !(this.historyPages.get(backendId) ?? entry?.historyPage)?.has_more,
      };
    }
    const page = this.historyPages.get(backendId) ?? entry?.historyPage;
    if (!beforeMessageId && (!page?.has_more || !page.next_before)) {
      return { messages: [], noMore: true };
    }
    const existing = this.historyPageRequests.get(backendId);
    if (existing) return existing;

    const owner = this.getActiveOwner();
    const request = api
      .getChatMessages(backendId, {
        ...(beforeMessageId
          ? { before_message_id: beforeMessageId }
          : { before: page?.next_before ?? undefined }),
        limit: HISTORY_PAGE_TURN_LIMIT,
        signal,
        include_app_owned: false,
      })
      .then((result) => readHistoryPage(result, signal))
      .then(({ page: result, messages }) => {
        if (!this.isActiveOwner(owner)) {
          throw new DOMException("Agent changed", "AbortError");
        }
        const nextPage: ChatHistoryMetadata = {
          has_more: result.has_more,
          next_before: result.next_before,
          snapshot: result.snapshot,
        };
        this.setHistoryPage(backendId, nextPage);
        if (entry) entry.historyPage = nextPage;

        const historyWindow = this.historyWindows.get(backendId) ?? {
          pages: [entry?.messages ?? []],
          activeIndex: 0,
        };
        if (accumulate) {
          const current = historyWindow.pages[historyWindow.activeIndex] ?? [];
          historyWindow.pages[historyWindow.activeIndex] =
            mergeCachedHistoryPages(messages, current);
        } else {
          historyWindow.pages.push(messages);
          if (historyWindow.pages.length > 4)
            historyWindow.pages.splice(1, historyWindow.pages.length - 4);
          historyWindow.activeIndex = historyWindow.pages.length - 1;
        }
        this.historyWindows.set(backendId, historyWindow);
        const visibleMessages = beforeMessageId
          ? messages
          : this.renderHistoryWindow(backendId);
        const cached = this.convertedSessionCache.get(backendId);
        if (cached) {
          cached.session.messages = visibleMessages;
          cached.session.historyPage = nextPage;
        }
        return { messages: visibleMessages, noMore: !result.has_more };
      })
      .finally(() => {
        if (this.historyPageRequests.get(backendId) === request) {
          this.historyPageRequests.delete(backendId);
        }
      });
    this.historyPageRequests.set(backendId, request);
    return request;
  }

  async loadUserMessageText(
    sessionId: string,
    messageId: string,
    signal?: AbortSignal,
  ) {
    return (
      await api.getChatUserMessageText(
        this.getHistoryBackendId(sessionId),
        messageId,
        signal,
      )
    ).text;
  }

  async loadUserMessageIndex(sessionId: string, signal?: AbortSignal) {
    return (await this.loadUserMessageIndexPage(sessionId, undefined, signal))
      .items;
  }

  async loadUserMessageIndexPage(
    sessionId: string,
    before?: string,
    signal?: AbortSignal,
  ): Promise<{ items: HistoryUserMessage[]; total: number; before?: string }> {
    const backendId = this.getHistoryBackendId(sessionId);
    const page = await api.getChatUserMessages(backendId, {
      before,
      limit: 50,
      signal,
      include_app_owned: false,
    });
    return {
      items: page.items.map((item) => ({
        clientMessageId: item.client_message_id,
        messageId: item.message_id,
        preview: item.preview,
        createdAt: item.created_at,
        anchor: item.anchor,
      })),
      total: page.total ?? page.items.length,
      before: page.has_more ? page.next_before ?? undefined : undefined,
    };
  }

  async loadHistoryAtAnchor(
    sessionId: string,
    anchor: string,
    targetMessageId?: string,
    signal?: AbortSignal,
    mode: "replace" | "append-newer" = "replace",
    isLatest = false,
  ): Promise<{
    messages: IAgentScopeRuntimeWebUIMessage[];
    noMore: boolean;
  }> {
    const backendId = this.getHistoryBackendId(sessionId);
    const owner = this.getActiveOwner();
    const window = this.historyWindows.get(backendId) ?? {
      pages: [[]],
      activeIndex: 0,
      forwardFragment: undefined as
        | { boundary: string; before: string }
        | undefined,
    };
    const continuation =
      mode === "append-newer" &&
      window.forwardFragment &&
      window.forwardFragment.boundary === targetMessageId
        ? window.forwardFragment.before
        : undefined;
    const result = await api.getChatMessages(backendId, {
      ...(continuation
        ? { before: continuation }
        : mode === "append-newer"
        ? { after_message_id: targetMessageId }
        : { before: anchor }),
      limit: mode === "append-newer" ? 1 : HISTORY_PAGE_TURN_LIMIT,
      signal,
      include_app_owned: false,
    });
    signal?.throwIfAborted();
    if (!this.isActiveOwner(owner))
      throw new DOMException("Agent changed", "AbortError");
    const { messages } = readHistoryPage(result, signal);
    if (mode === "append-newer") {
      this.historyWindows.set(backendId, window);
      // The API returns the suffix of a split turn. Read its preceding
      // fragments before advancing to another turn; never skip the gap.
      window.forwardFragment =
        messages.length > 0 &&
        messages[0].role !== ROLE_USER &&
        result.has_more &&
        result.next_before &&
        targetMessageId
          ? { boundary: targetMessageId, before: result.next_before }
          : undefined;
    }
    const page: ChatHistoryMetadata = {
      has_more: result.has_more,
      next_before: result.next_before,
      snapshot: result.snapshot,
    };
    // Forward fills must not move the oldest loaded boundary.
    if (mode === "replace" && !signal?.aborted) {
      const previous = this.historyWindows.get(backendId);
      const latestBeforeAnchor =
        (isLatest ? { messages, page } : previous?.latestBeforeAnchor) ??
        (previous
          ? {
              messages: previous.pages[0],
              page: this.historyPages.get(backendId),
            }
          : undefined);
      this.historyWindows.set(backendId, {
        pages: [messages],
        activeIndex: 0,
        latestBeforeAnchor,
      });
      this.setHistoryPage(backendId, page);
    }
    return { messages, noMore: !result.has_more };
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

      // A preload must not navigate or repopulate an alias after its Agent
      // or canonical Chat identity changes while history is loading.
      const extendedSession = session as ExtendedSession;
      const realId = extendedSession.realId || null;
      if (
        !this.isActiveOwner(owner) ||
        this.getEffectiveSessionId(sessionId) !== (realId ?? session.id)
      ) {
        throw new DOMException("Aborted", "AbortError");
      }

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
    this.switchAbortController?.abort();
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

  /** Route metadata survives lists that exclude the selected archived Chat. */
  private resolvedRouteSession: ExtendedSession | null = null;
  private routeResolutionVersion = 0;
  private removedRouteIds = new Set<string>();
  private removedCurrentRouteIds = new Set<string>();

  /** Prevent canonical deleted routes from resolving while navigation settles. */
  markRouteRemoved(...ids: Array<string | null | undefined>): void {
    for (const id of ids) {
      if (id) this.removedRouteIds.add(id);
    }
  }

  /** Temporarily suppress aliases only while their deleted route is current. */
  markCurrentRouteRemoved(...ids: Array<string | null | undefined>): void {
    for (const id of ids) {
      if (id) this.removedCurrentRouteIds.add(id);
    }
  }

  isRouteRemoved(id?: string | null): boolean {
    return (
      !!id &&
      (this.removedRouteIds.has(id) || this.removedCurrentRouteIds.has(id))
    );
  }

  clearRouteRemoval(id?: string | null): void {
    if (!id) return;
    this.removedRouteIds.delete(id);
    this.removedCurrentRouteIds.delete(id);
  }

  /** Notify route aliases when their cached existence proof is invalidated. */
  getRouteResolutionVersion(): number {
    return this.routeResolutionVersion;
  }

  registerResolvedChat(chat: ChatSpec, owner: SessionOwnerToken): void {
    if (!this.isActiveOwner(owner)) return;
    const previousIds = new Map(
      [chat.id, chat.session_id].map((id) => [
        id,
        this.getEffectiveSessionId(id),
      ]),
    );
    this.resolvedRouteSession = {
      ...chatSpecToSession(chat),
      realId: chat.id,
    };
    const changedIds = new Set<string>();
    for (const [id, previousId] of previousIds) {
      if (previousId === this.getEffectiveSessionId(id)) continue;
      changedIds.add(id);
      this.sessionRequests.delete(id);
      this.sessionResultCache.delete(id);
      this.lastSelectedIds.delete(id);
    }
    if (changedIds.size) {
      // Confirmed canonical and runtime IDs supersede stale display aliases.
      // Drop alias-keyed work and restore the displaced row's canonical ID.
      this.sessionList = this.sessionList.map((session) => {
        const existing = session as ExtendedSession;
        return changedIds.has(existing.id) && existing.realId
          ? { ...existing, id: existing.realId }
          : session;
      });
      syncSessionsGlobal([...this.sessionList]);
    }
  }

  /** Publish a confirmed fork before navigation or a background refresh. */
  registerForkedChat(chat: ChatSpec, owner: SessionOwnerToken): void {
    if (!this.isActiveOwner(owner)) return;
    this.sessionListRequest = null;
    this.sessionList = [
      chatSpecToSession(chat),
      ...this.sessionList.filter(
        (session) =>
          session.id !== chat.id &&
          (session as ExtendedSession).realId !== chat.id,
      ),
    ];
    this._prevReturnedList = [...this.sessionList];
    syncSessionsGlobal(this._prevReturnedList);
  }

  private creationVisit = 0;
  private pendingCreatedSessions = new Set<string>();

  /** A new route visit must not join or publish an earlier draft's creation. */
  invalidateSessionCreation(): void {
    this.creationVisit++;
    this.sessionCreationRequest = null;
    this.pendingCreatedSessions.clear();
  }

  /** Called only after the SDK accepts and activates the creation result. */
  activateCreatedSession(id?: string): void {
    if (!id || !this.pendingCreatedSessions.delete(id)) return;
    this.onSessionCreated?.(id);
  }

  /** Share only pending creation within an owner epoch, never a completed Chat. */
  private sessionCreationRequest: {
    owner: SessionOwnerToken;
    promise: Promise<IAgentScopeRuntimeWebUICreateSessionResult>;
  } | null = null;

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
    this.invalidateSessionCreation();
    this.resolvePromise = null;
    this.pendingLocalSessionIds.clear();
    this.sessionRequests.clear();
    this.sessionResultCache.clear();
    this.convertedSessionCache.clear();
    this.historyPages.clear();
    this.historyPageRequests.clear();
    this.historyWindows.clear();
    // Reset the session list and its comparison state as well: the next
    // agent's chats can share a session_id (channel:user_id) with the old
    // list, and merging against leftover entries would transfer the previous
    // agent's local id / backend UUID onto a different chat.
    this.sessionList = [];
    this.resolvedRouteSession = null;
    this.removedRouteIds.clear();
    this.removedCurrentRouteIds.clear();
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

  /** Bind SDK callbacks to their mounted Agent, including late effect calls. */
  bindToOwner(): IAgentScopeRuntimeWebUISessionAPI {
    const owner = this.getActiveOwner();
    return {
      getSessionList: async () =>
        this.isActiveOwner(owner) ? this.getSessionList() : [],
      getSession: async (id) => {
        if (!this.isActiveOwner(owner)) return undefined;
        const session = await this.getSession(id);
        // Direct callers may inspect late results, but an old SDK/adapter
        // must not publish them into the current owner's view or observer.
        return this.isActiveOwner(owner) ? session : undefined;
      },
      updateSession: async (session) =>
        this.isActiveOwner(owner) ? this.updateSession(session) : [],
      removeSession: async (session) =>
        this.isActiveOwner(owner) ? this.removeSession(session) : [],
      createSession: async (session) => {
        if (!this.isActiveOwner(owner)) {
          throw new DOMException("Agent changed", "AbortError");
        }
        return this.createSession(session);
      },
    };
  }

  /** A token is active only when both the agent and its epoch still match. */
  isActiveOwner(token: SessionOwnerToken): boolean {
    return (
      token.agentId === this.activeOwner.agentId &&
      token.generation === this.activeOwner.generation
    );
  }

  /**
   * Applies view-facing turn usage only while the owner epoch that started the
   * load is still active.
   */
  private visibleSessionId: string | null | undefined;

  setVisibleSession(sessionId: string | null): void {
    if (this.visibleSessionId === sessionId) return;
    this.visibleSessionId = sessionId;
    const turn = useTurnUsageStore.getState().activeTurn;
    if (
      sessionId &&
      turn?.agentId === this.activeOwner.agentId &&
      this.getBackendSessionId(sessionId) === turn.sessionId
    )
      return;
    useTurnUsageStore.getState().invalidateTurn();
    useTurnUsageStore.getState().setActiveMaxInputLength(null);
  }

  private isVisibleSession(sessionId: string): boolean {
    return (
      this.visibleSessionId === undefined ||
      (this.visibleSessionId !== null &&
        this.getEffectiveSessionId(sessionId, null) ===
          this.getEffectiveSessionId(this.visibleSessionId, null))
    );
  }

  private applySessionView(
    session: ExtendedSession,
    owner: SessionOwnerToken,
  ): void {
    if (!this.isActiveOwner(owner) || !this.isVisibleSession(session.id))
      return;
    // A history response must not invalidate or overwrite a live stream.
    if (useTurnUsageStore.getState().activeTurn) return;
    hydrateTurnUsageFromMessages(session.messages ?? [], session.contextState);
  }

  /**
   * Test-only: restores ownership, in-flight work, caches, and callbacks to a
   * pristine page-load state so tests cannot leak state into each other.
   */
  resetForTests(): void {
    this.visibleSessionId = undefined;
    this.activeOwner = { agentId: "", generation: 0 };
    this.resolvedRouteSession = null;
    this.routeResolutionVersion = 0;
    this.removedRouteIds.clear();
    this.removedCurrentRouteIds.clear();
    this.sessionListRequest = null;
    this.invalidateSessionCreation();
    this.resolvePromise = null;
    this.pendingLocalSessionIds.clear();
    this.sessionRequests.clear();
    this.sessionResultCache.clear();
    this.convertedSessionCache.clear();
    this.historyPages.clear();
    this.historyPageRequests.clear();
    this.historyWindows.clear();
    this.sessionList = [];
    this._prevReturnedList = null;
    this.lastSelectedIds.clear();
    this.preferredChatId = null;
    this.lastActiveChatId = null;
    this.isSessionSwitching = false;
    this.switchAbortController = null;
    this.onSessionIdResolved = null;
    this.onSessionRemoved = null;
    this.onSessionSelected = null;
    this.onSessionCreated = null;
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

  // A sidebar poll may replace a local placeholder with the backend UUID
  // before POST headers arrive. Keep its ownership until resolution notifies
  // the host, rather than relying on the placeholder still being in the list.
  private pendingLocalSessionIds = new Set<string>();

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
   * Called when a new session is created.
   * Consumers can register here to update the URL with the new session id.
   */
  onSessionCreated: ((sessionId: string) => void) | null = null;

  private createEmptySession(
    sessionId: string,
    owner: SessionOwnerToken,
  ): ExtendedSession {
    if (this.isActiveOwner(owner) && this.isVisibleSession(sessionId)) {
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

  private findSession(id: string): ExtendedSession | undefined {
    // Canonical IDs, including resolved archived Chats, precede SDK aliases.
    const canonical = this.sessionList.find(
      (x) => ((x as ExtendedSession).realId ?? x.id) === id,
    ) as ExtendedSession | undefined;
    if (canonical) return canonical;

    const resolved = this.resolvedRouteSession;
    if (
      resolved?.id === id ||
      resolved?.realId === id ||
      resolved?.sessionId === id
    )
      return resolved;

    const display = this.sessionList.find((x) => x.id === id) as
      | ExtendedSession
      | undefined;
    if (display) return display;

    // Runtime session_id values are opaque. Most locally-created values use
    // the timestamp-random format, but imported/auto-registered Chats may use
    // UUID-looking runtime IDs as well. Use an unconfirmed list alias only
    // when the match is unique: the backend permits multiple Chats to share
    // a runtime identity, and guessing would cross conversation data.
    const runtimeMatches = new Map<string, ExtendedSession>();
    for (const session of this.sessionList as ExtendedSession[]) {
      if (session.sessionId === id)
        runtimeMatches.set(session.realId ?? session.id, session);
    }
    return runtimeMatches.size === 1
      ? runtimeMatches.values().next().value
      : undefined;
  }

  /** Returns the real backend UUID, or null when not yet resolved. */
  getRealIdForSession(sessionId: string): string | null {
    const session = this.findSession(sessionId);
    if (!session) return null;
    return session.realId ?? (session.id !== sessionId ? session.id : null);
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
   * Reduces repeated `lastActiveChatId + persist` scattered
   * across onSessionIdResolved, onSessionSelected, sidebar, and initializer.
   */
  trackNavigatedSession(
    effectiveId: string,
    persistFn?: (agentId: string, id: string) => void,
    agentId?: string,
  ): void {
    this.lastActiveChatId = effectiveId;
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

  /** Resolve one immutable identity from an explicit SDK, chat, or runtime id. */
  getSessionIdentity(referenceId?: string | null): SessionIdentity {
    const explicitId = referenceId || "";
    const session = explicitId
      ? this.findSession(explicitId)
      : (this.sessionList.find(
          (item) =>
            isLocalTimestamp(item.id) && !(item as ExtendedSession).realId,
        ) as ExtendedSession | undefined);
    const sdkSessionId = session?.id || explicitId;
    const chatId =
      session?.realId ??
      (session && sdkSessionId && !isLocalTimestamp(sdkSessionId)
        ? sdkSessionId
        : undefined);
    return {
      sdkSessionId,
      chatId,
      sessionId:
        session?.sessionId ||
        (isLocalTimestamp(sdkSessionId) ? sdkSessionId : ""),
      userId: session?.userId || DEFAULT_USER_ID,
      channel: session?.channel || DEFAULT_CHANNEL,
    };
  }

  /** Apply listChats to sessionList; merge realId and generating by session_id. */
  private applyChatsToSessionList(
    chats: ChatSpec[],
  ): IAgentScopeRuntimeWebUISession[] {
    const resolvedId = this.resolvedRouteSession?.id;
    if (
      resolvedId &&
      this.sessionList.some(
        (session) =>
          ((session as ExtendedSession).realId ?? session.id) === resolvedId,
      ) &&
      !chats.some((chat) => chat.id === resolvedId)
    ) {
      // A listed Chat disappeared: let the route distinguish archive from
      // deletion. Never-listed archived Chats retain their resolved identity.
      this.resolvedRouteSession = null;
      this.routeResolutionVersion++;
    }
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
          const eExt = e as ExtendedSession;
          return (
            eExt.sessionId === sExt.sessionId &&
            eExt.userId === sExt.userId &&
            eExt.channel === sExt.channel
          );
        }) as ExtendedSession | undefined;
      }

      if (!existing) return s;

      matchedExistingIds.add(existing.id);

      const next = { ...s } as ExtendedSession;
      if (existing.realId && existing.realId === s.id) {
        // Keep local aliases only for the same canonical Chat: runtime IDs
        // can be reassigned after deletion. Preserve the SDK ID during SSE.
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
      // Page refresh: URL may contain an opaque runtime session_id while the
      // backend list exposes only Chat UUIDs. UUID-looking runtime IDs are
      // valid too, so match by value rather than by the old timestamp shape.
      if (idx < 0 && this.resolvedRouteSession?.id !== preferredId) {
        const runtimeMatches = this.sessionList
          .map((s, index) => ({ s: s as ExtendedSession, index }))
          .filter(({ s }) => s.sessionId === preferredId);
        if (runtimeMatches.length === 1) {
          idx = runtimeMatches[0].index;
          const s = runtimeMatches[0].s;
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
        a.lastFinishedAt !== b.lastFinishedAt ||
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
        a.rootSessionId !== b.rootSessionId ||
        a.parentChatId !== b.parentChatId ||
        a.forkTurnId !== b.forkTurnId ||
        a.forkTurnSeq !== b.forkTurnSeq
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
        // Agent switches and confirmed forks invalidate older list reads.
        // Return the current list so poll subscribers cannot roll it back.
        if (!this.isActiveOwner(owner) || this.sessionListRequest !== entry) {
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

  /** Refresh after another sender has owned this Chat, without selecting it. */
  async refreshSession(sessionId: string, signal?: AbortSignal) {
    const owner = this.getActiveOwner();
    const inFlight = this.sessionRequests.get(sessionId);
    if (inFlight) await inFlight.promise.catch(() => undefined);
    if (signal?.aborted || !this.isActiveOwner(owner)) return undefined;
    const backendId = this.getRealIdForSession(sessionId) || sessionId;
    this.sessionResultCache.delete(sessionId);
    this.sessionResultCache.delete(backendId);
    this.invalidateConvertedCache(backendId);
    return this._doGetSession(sessionId, signal, owner);
  }

  async getSession(sessionId: string, signal?: AbortSignal) {
    const owner = this.getActiveOwner();

    // Check short-lived result cache first (populated by preloadSession).
    // Entries must still belong to the same owner and canonical Chat.
    const cached = this.sessionResultCache.get(sessionId);
    if (
      cached &&
      this.isActiveOwner(cached.owner) &&
      this.getEffectiveSessionId(sessionId) ===
        ((cached.session as ExtendedSession).realId ?? cached.session.id)
    ) {
      this.applySessionView(cached.session as ExtendedSession, owner);
      return cached.session;
    }

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
      if (
        this.isActiveOwner(owner) &&
        this.getEffectiveSessionId(sessionId) !== (realId ?? session.id)
      ) {
        throw new DOMException("Aborted", "AbortError");
      }

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
   * state (turn-usage store and converted cache) only while
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
        if (cached.historyPage && this.isActiveOwner(owner)) {
          this.setHistoryPage(backendId, cached.historyPage);
        }
        // Update mutable fields that may differ
        cached.id = displayId;
        if (listEntry?.name) cached.name = listEntry.name;
        cached.realId =
          listEntry?.realId ??
          (backendId !== displayId ? backendId : cached.realId);
        const historyWindow = this.historyWindows.get(backendId);
        if (historyWindow) {
          const latest = historyWindow.latestBeforeAnchor;
          if (latest) {
            historyWindow.pages = [latest.messages];
            historyWindow.latestBeforeAnchor = undefined;
            if (latest.page) this.setHistoryPage(backendId, latest.page);
          }
          historyWindow.activeIndex = 0;
          cached.messages = this.renderHistoryWindow(backendId);
        }
        this.applySessionView(cached, owner);
        return cached;
      }
    }

    const chatHistory = await (takeChatHistoryPrefetch(
      backendId,
      owner.agentId,
    ) ??
      api.getChat(backendId, {
        signal,
        include_app_owned: false,
      }));
    const historyPage = chatHistory.history ?? {
      has_more: false,
      next_before: null,
      snapshot: null,
    };
    if (
      signal?.aborted ||
      (this.isActiveOwner(owner) &&
        this.getEffectiveSessionId(displayId) !== backendId)
    ) {
      throw new DOMException("Aborted", "AbortError");
    }
    if (this.isActiveOwner(owner)) {
      this.setHistoryPage(backendId, historyPage);
      for (const id of new Set([displayId, backendId])) {
        useMessageQueueStore
          .getState()
          .reconcileHistory(id, owner.agentId, chatHistory.messages || []);
      }
    }
    const generating = isGenerating(chatHistory);
    const messages = convertMessages(chatHistory.messages || [], true);
    if (this.isActiveOwner(owner)) {
      this.resetHistoryWindow(backendId, messages);
    }

    const session: ExtendedSession = {
      id: displayId,
      name: listEntry?.name || DEFAULT_SESSION_NAME,
      sessionId: listEntry?.sessionId || displayId,
      userId: listEntry?.userId || DEFAULT_USER_ID,
      channel: listEntry?.channel || DEFAULT_CHANNEL,
      messages,
      meta: listEntry?.meta || {},
      realId:
        listEntry?.realId ?? (backendId !== displayId ? backendId : undefined),
      generating,
      historyPage,
      contextState: chatHistory.context_state,
    };

    // Cache non-generating sessions only within the epoch that fetched them,
    // so a stale load cannot write into the new agent's cache.
    if (!generating && this.isActiveOwner(owner)) {
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
        return this.fetchAndBuildSession(
          sessionId,
          fromList.realId,
          fromList,
          signal,
          owner,
        );
      }
      // A triggerResolve may be in-flight (POST succeeded but getSessionList
      // hasn't returned yet). Wait for it so we can return real messages
      // instead of an empty local session — prevents clearing the library's
      // message state after the first SSE stream completes.
      if (fromList && this.resolvePromise) {
        await this.resolvePromise;
        const resolved = this.findSession(sessionId);
        if (resolved?.realId) {
          return this.fetchAndBuildSession(
            sessionId,
            resolved.realId,
            resolved,
            signal,
            owner,
          );
        }
      }
      if (fromList) {
        this.applySessionView(fromList, owner);
        return fromList;
      }
      return this.createEmptySession(sessionId, owner);
    }

    // --- Backend Chat UUID or an opaque runtime session_id alias ---
    const listEntry = this.findSession(sessionId);
    const backendId =
      listEntry?.realId ??
      (listEntry && listEntry.id !== sessionId ? listEntry.id : sessionId);
    return this.fetchAndBuildSession(
      sessionId,
      backendId,
      listEntry,
      signal,
      owner,
    );
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
      this.pendingLocalSessionIds.delete(tempId);
      // Publish the resolved mapping immediately so the SDK can match a URL
      // carrying the backend UUID while the response is still generating.
      syncSessionsGlobal(this.sessionList as ExtendedSession[]);
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
    const owner = this.getActiveOwner();
    if (existing?.realId) {
      if (this.pendingLocalSessionIds.has(tempId)) {
        this.resolveAndNotify(tempId, owner);
      }
      return;
    }
    if (!existing && !this.pendingLocalSessionIds.has(tempId)) return;
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
    const metadata = { ...session };
    delete metadata.messages;
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

  async createSession(
    session: Partial<IAgentScopeRuntimeWebUISession>,
  ): Promise<IAgentScopeRuntimeWebUICreateSessionResult> {
    const owner = this.getActiveOwner();
    const visit = this.creationVisit;
    if (
      this.sessionCreationRequest &&
      this.isActiveOwner(this.sessionCreationRequest.owner)
    ) {
      return this.sessionCreationRequest.promise;
    }
    // Idempotency: reuse an unresolved local session. The explicit SDK result
    // identifies the reused session without mutating the caller's draft or
    // relying on list order.
    const existing = this.sessionList.find(
      (s) => isLocalTimestamp(s.id) && !(s as ExtendedSession).realId,
    ) as ExtendedSession | undefined;
    if (existing) {
      this.pendingCreatedSessions.add(existing.id);
      return { sessions: [...this.sessionList], session: existing };
    }

    const entry = {
      owner,
      promise:
        (async (): Promise<IAgentScopeRuntimeWebUICreateSessionResult> => {
          const runtimeSessionId = `${Date.now()}-${randomBase36(7)}`;
          // Resolve the backend UUID before the first turn. Only this shared
          // operation publishes the session and fires the creation callback.
          const placeholderName = session.name?.slice(0, 10) || "Media Message";
          const chat = await api.createChat({
            session_id: runtimeSessionId,
            user_id: DEFAULT_USER_ID,
            channel: DEFAULT_CHANNEL,
            name: placeholderName,
            meta: { console_placeholder_name: placeholderName },
          });
          if (!this.isActiveOwner(owner) || visit !== this.creationVisit) {
            throw new DOMException("Session creation superseded", "AbortError");
          }
          // Publish the same metadata as a list refresh on the first render;
          // missing timestamps would briefly place a new Chat in Earlier.
          const extended = {
            ...this.createEmptySession(chat.id, owner),
            ...chatSpecToSession(chat),
            realId: chat.id,
            sessionId: chat.session_id || runtimeSessionId,
          };
          this.sessionList.unshift(extended);
          this.pendingCreatedSessions.add(chat.id);
          return { sessions: [...this.sessionList], session: extended };
        })(),
    };
    this.sessionCreationRequest = entry;
    try {
      return await entry.promise;
    } finally {
      // Both success and failure permit another creation. An old epoch must
      // not clear the request installed by a newer A -> B -> A cycle.
      if (this.sessionCreationRequest === entry) {
        this.sessionCreationRequest = null;
      }
    }
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this.sessionList];

    const { id: sessionId } = session;
    const owner = this.getActiveOwner();

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
    if (
      this.isActiveOwner(owner) &&
      this.resolvedRouteSession?.id === canonicalId
    ) {
      this.resolvedRouteSession = null;
      this.routeResolutionVersion++;
    }

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
  parseFinishedAt,
  isLocalTimestamp,
  isGenerating,
  resolveRealId,
  getTranscriptPosition,
  mergeHistoryMessages,
};
