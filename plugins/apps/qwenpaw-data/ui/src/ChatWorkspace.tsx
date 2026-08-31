import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import type { DataSourceMetadata } from "./api";
import { ArrowUpIcon, ArrowUpRightIcon, EllipsisIcon, PinIcon } from "./icons";
import { useLanguage, useT } from "./language";
import { LogoMark } from "./LogoMark";
import { renderMarkdown, splitCompletionMarker } from "./markdown";
import type {
  PawAppSdk,
  PawChatHistoryMessage,
  PawChatSession,
  PawChatStreamEvent,
} from "./sdk";
import { localeTag, translate, type Language, type StringKey } from "./strings";

type TraceStatus = "running" | "completed" | "error";

interface QueryResult {
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
}

interface ChatTraceItem {
  id: string;
  name: string;
  label: string;
  status: TraceStatus;
  detail?: string;
  result?: QueryResult;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  activity?: string;
  trace?: ChatTraceItem[];
  streaming?: boolean;
}

// Bare app-level session used as the fallback when dialogue management
// (the chatSessions API) is unavailable.
const FALLBACK_CHAT_SESSION_ID = "pawapp:qwenpaw-data";
const SOURCE_CONTEXT_OPEN = "<qwenpaw-data-source-context>";
const SOURCE_CONTEXT_CLOSE = "</qwenpaw-data-source-context>";
const LEGACY_SOURCE_CONTEXT_RE =
  /^Use QwenPaw-Data source .*? for this request unless the user explicitly asks for another source\.\s*/;

export interface ChatStreamState {
  textByMessage: Record<string, string>;
  messageOrder: string[];
  toolMessageIds: Record<string, string>;
  trace: ChatTraceItem[];
  finalMessageId?: string;
  finalText: string;
  completed: boolean;
}

const STARTER_KEYS: StringKey[] = [
  "chat.starter.domains",
  "chat.starter.movement",
  "chat.starter.retention",
];

/** Default names a first question may overwrite, across both languages. */
const DEFAULT_SESSION_NAMES = [
  "New analysis",
  "Previous analysis",
  "New Chat",
  "新分析",
  "历史分析",
];

const TOOL_LABEL_KEYS: Record<string, StringKey> = {
  qwenpaw_data_list_domains: "tool.listDomains",
  qwenpaw_data_explore_entity: "tool.exploreEntity",
  qwenpaw_data_search_context: "tool.searchContext",
  qwenpaw_data_execute_sql: "tool.executeSql",
};

export function createChatStreamState(): ChatStreamState {
  return {
    textByMessage: {},
    messageOrder: [],
    toolMessageIds: {},
    trace: [],
    finalText: "",
    completed: false,
  };
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function contentText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => {
      const block = recordValue(item);
      if (!block || block.type !== "text" || block.delta === true) return "";
      return typeof block.text === "string" ? block.text : "";
    })
    .join("");
}

function dataContent(content: unknown): Record<string, unknown> | undefined {
  if (!Array.isArray(content)) return undefined;
  for (const item of content) {
    const block = recordValue(item);
    if (!block || block.type !== "data") continue;
    const data = recordValue(block.data);
    if (data) return data;
  }
  return undefined;
}

function visibleUserText(text: string): string {
  const taggedStart = text.indexOf(SOURCE_CONTEXT_OPEN);
  if (taggedStart === 0) {
    const taggedEnd = text.indexOf(SOURCE_CONTEXT_CLOSE);
    if (taggedEnd >= 0) {
      return text.slice(taggedEnd + SOURCE_CONTEXT_CLOSE.length).trim();
    }
  }
  return text.replace(LEGACY_SOURCE_CONTEXT_RE, "").trim();
}

function finalAssistantMessage(event: PawChatStreamEvent) {
  if (!Array.isArray(event.output)) return undefined;
  for (let index = event.output.length - 1; index >= 0; index -= 1) {
    const message = recordValue(event.output[index]);
    if (!message) continue;
    if (message.type !== "message" || message.role !== "assistant") continue;
    const text = contentText(message.content);
    if (!text.trim()) continue;
    return {
      id: typeof message.id === "string" ? message.id : undefined,
      text: text.trim(),
    };
  }
  return undefined;
}

function toolLabel(name: string, language: Language = "en"): string {
  const key = TOOL_LABEL_KEYS[name];
  if (key) return translate(language, key);
  return name
    .replace(/^qwenpaw_data_/, "")
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function parseToolOutput(
  output: unknown,
  language: Language = "en",
): {
  status: TraceStatus;
  detail?: string;
  result?: QueryResult;
} {
  if (typeof output !== "string" || !output) return { status: "completed" };
  let parsed: Record<string, unknown> | undefined;
  try {
    parsed = recordValue(JSON.parse(output));
  } catch {
    return { status: "completed" };
  }
  if (!parsed) return { status: "completed" };

  if (parsed.exec_status === "error" || parsed.error) {
    const detail = String(
      parsed.error || translate(language, "trace.queryFailed"),
    ).split("\n")[0];
    return { status: "error", detail };
  }

  if (Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) {
    const columns = parsed.columns.map(String);
    const rows = parsed.rows.filter(Array.isArray) as unknown[][];
    const total =
      typeof parsed.total_row_count === "number"
        ? parsed.total_row_count
        : rows.length;
    return {
      status: "completed",
      detail: translate(language, "trace.rows", {
        count: total,
        rowWord: translate(
          language,
          total === 1 ? "trace.row" : "trace.rowPlural",
        ),
      }),
      result: {
        columns,
        rows,
        truncated: parsed.truncated === true,
      },
    };
  }

  const relevance = recordValue(parsed.relevance);
  if (typeof relevance?.status === "string") {
    return {
      status: "completed",
      detail: relevance.status.replaceAll("_", " "),
    };
  }
  return { status: "completed" };
}

function upsertTrace(
  trace: ChatTraceItem[],
  item: ChatTraceItem,
): ChatTraceItem[] {
  const index = trace.findIndex((candidate) => candidate.id === item.id);
  if (index === -1) return [...trace, item];
  const next = [...trace];
  next[index] = { ...next[index], ...item };
  return next;
}

/** Rebuild QwenPaw Data's transcript and trace cards from QwenPaw session events. */
export function historyToChatMessages(
  history: PawChatHistoryMessage[],
  language: Language = "en",
): ChatMessage[] {
  const transcript: ChatMessage[] = [];
  const grouped = new Map<string, ChatMessage>();

  history.forEach((event, index) => {
    const role = event.role === "user" ? "user" : "assistant";
    if (role !== "user" && event.role !== "assistant") return;
    const metadata = recordValue(event.metadata);
    const originalId =
      typeof metadata?.original_id === "string"
        ? metadata.original_id
        : event.id || `history-${index}`;
    const key = `${role}:${originalId}`;
    let message = grouped.get(key);
    if (!message) {
      message = {
        id: key,
        role,
        text: "",
        trace: role === "assistant" ? [] : undefined,
        streaming: false,
      };
      grouped.set(key, message);
      transcript.push(message);
    }

    if (event.type === "message") {
      const segment = contentText(event.content).trim();
      if (!segment) return;
      if (role === "user") {
        const visible = visibleUserText(segment);
        message.text = [message.text, visible].filter(Boolean).join("\n\n");
        return;
      }
      if (message.text) {
        message.activity = [message.activity, message.text]
          .filter(Boolean)
          .join("\n\n");
      }
      message.text = segment;
      return;
    }

    if (role !== "assistant") return;
    const data = dataContent(event.content);
    if (!data) return;
    const callId = typeof data.call_id === "string" ? data.call_id : "";
    if (!callId) return;
    const existing = message.trace?.find((item) => item.id === callId);
    const name =
      typeof data.name === "string" ? data.name : existing?.name || "tool";
    if (event.type === "plugin_call") {
      message.trace = upsertTrace(message.trace || [], {
        id: callId,
        name,
        label: toolLabel(name, language),
        status: "running",
      });
      return;
    }
    if (event.type === "plugin_call_output") {
      message.trace = upsertTrace(message.trace || [], {
        id: callId,
        name,
        label: toolLabel(name, language),
        ...parseToolOutput(data.output, language),
      });
    }
  });

  return transcript
    .map((message) => ({
      ...message,
      trace: message.trace?.map((item) =>
        item.status === "running"
          ? { ...item, status: "completed" as const }
          : item,
      ),
    }))
    .filter(
      (message) =>
        Boolean(message.text) ||
        Boolean(message.activity) ||
        Boolean(message.trace?.length),
    );
}

export function reduceChatStreamEvent(
  state: ChatStreamState,
  event: PawChatStreamEvent,
  language: Language = "en",
): ChatStreamState {
  let next = state;

  if (event.type === "text" && typeof event.text === "string") {
    const messageId = event.msg_id || "assistant";
    const existing = state.textByMessage[messageId] || "";
    const text =
      event.delta === true ? existing + event.text : existing || event.text;
    next = {
      ...next,
      textByMessage: { ...next.textByMessage, [messageId]: text },
      messageOrder: next.messageOrder.includes(messageId)
        ? next.messageOrder
        : [...next.messageOrder, messageId],
    };
  }

  if (event.type === "data") {
    const data = recordValue(event.data);
    if (data) {
      const eventMessageId = event.msg_id || "";
      const explicitCallId =
        typeof data.call_id === "string" ? data.call_id : undefined;
      const callId =
        explicitCallId || next.toolMessageIds[eventMessageId] || undefined;
      const name = typeof data.name === "string" ? data.name : undefined;

      if (callId && eventMessageId) {
        next = {
          ...next,
          toolMessageIds: {
            ...next.toolMessageIds,
            [eventMessageId]: callId,
          },
        };
      }

      if (callId && name) {
        const hasOutput = Object.prototype.hasOwnProperty.call(data, "output");
        const parsed =
          hasOutput && event.status === "completed"
            ? parseToolOutput(data.output, language)
            : { status: "running" as const };
        next = {
          ...next,
          trace: upsertTrace(next.trace, {
            id: callId,
            name,
            label: toolLabel(name, language),
            ...parsed,
          }),
        };
      }
    }
  }

  if (event.object === "response" && event.status === "completed") {
    const final = finalAssistantMessage(event);
    const fallbackId = next.messageOrder.at(-1);
    next = {
      ...next,
      finalMessageId: final?.id || fallbackId,
      finalText:
        final?.text || (fallbackId ? next.textByMessage[fallbackId] || "" : ""),
      completed: true,
      trace: next.trace.map((item) =>
        item.status === "running" ? { ...item, status: "completed" } : item,
      ),
    };
  }

  return next;
}

function streamMessagePatch(state: ChatStreamState): Partial<ChatMessage> {
  const finalId = state.finalMessageId;
  const activity = state.messageOrder
    .filter((messageId) => !state.completed || messageId !== finalId)
    .map((messageId) => state.textByMessage[messageId])
    .join("")
    .trim();
  return {
    text: state.finalText,
    activity,
    trace: state.trace,
    streaming: !state.completed,
  };
}

export function analysisErrorMessage(
  error: unknown,
  language: Language = "en",
): string {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? String(error.code || "")
      : "";
  if (code === "MODEL_NOT_CONFIGURED") {
    return translate(language, "error.modelNotConfigured");
  }
  if (code === "UNAUTHORIZED_MODEL_ACCESS") {
    return translate(language, "error.modelUnauthorized");
  }
  const detail = error instanceof Error ? error.message : String(error);
  if (/not found in config/i.test(detail)) {
    return translate(language, "error.agentReloading");
  }
  return translate(language, "error.analysisFallback", { detail });
}

function ResultTable({ result }: { result: QueryResult }) {
  const t = useT();
  if (!result.columns.length || !result.rows.length) return null;
  return (
    <div className="qwenpaw-data-trace-result">
      <table>
        <thead>
          <tr>
            {result.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.slice(0, 100).map((row, rowIndex) => (
            <tr key={rowIndex}>
              {result.columns.map((_, columnIndex) => (
                <td key={columnIndex}>{String(row[columnIndex] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {result.truncated || result.rows.length > 100 ? (
        <small>
          {t("trace.showingRows", {
            count: Math.min(result.rows.length, 100),
          })}
        </small>
      ) : null}
    </div>
  );
}

function AnalysisTrace({ message }: { message: ChatMessage }) {
  const t = useT();
  const trace = message.trace || [];
  if (!message.activity && trace.length === 0) return null;
  return (
    <details className="qwenpaw-data-analysis-trace" open={message.streaming}>
      <summary>
        <span className={message.streaming ? "is-running" : ""} />
        {message.streaming
          ? t("trace.live")
          : t("trace.steps", {
              count: trace.length,
              stepWord: t(
                trace.length === 1 ? "trace.step" : "trace.stepPlural",
              ),
            })}
      </summary>
      <div className="qwenpaw-data-analysis-trace__body">
        {message.activity ? (
          <div className="qwenpaw-data-analysis-trace__narrative">
            {message.activity}
          </div>
        ) : null}
        {trace.length ? (
          <ol>
            {trace.map((item) => (
              <li className={`is-${item.status}`} key={item.id}>
                <i />
                <div>
                  <b>{item.label}</b>
                  {item.detail ? <small>{item.detail}</small> : null}
                  {item.result ? <ResultTable result={item.result} /> : null}
                </div>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </details>
  );
}

/** Pinned dialogues first, then most recently updated. */
export function sortChatSessions(sessions: PawChatSession[]): PawChatSession[] {
  return [...sessions].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return (b.updatedAt || "").localeCompare(a.updatedAt || "");
  });
}

/** Which dialogue becomes active after one is archived or deleted. */
export function nextActiveSessionId(
  sessions: PawChatSession[],
  removedSessionId: string,
  activeSessionId: string,
): string {
  if (removedSessionId !== activeSessionId) return activeSessionId;
  const remaining = sortChatSessions(sessions).filter(
    (session) => session.sessionId !== removedSessionId,
  );
  return remaining[0]?.sessionId || "";
}

function sessionTimestamp(value: string, language: Language = "en"): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(localeTag(language), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function DialogueHistory({
  sessions,
  activeSessionId,
  busy,
  creating,
  onCreate,
  onSelect,
  onTogglePin,
  onRename,
  onArchive,
  onDelete,
}: {
  sessions: PawChatSession[];
  activeSessionId: string;
  busy: boolean;
  creating: boolean;
  onCreate(): void;
  onSelect(sessionId: string): void;
  onTogglePin(session: PawChatSession): void;
  onRename(session: PawChatSession, name: string): void;
  onArchive(session: PawChatSession): void;
  onDelete(session: PawChatSession): void;
}) {
  const [menuFor, setMenuFor] = useState("");
  const [renamingId, setRenamingId] = useState("");
  const [renameDraft, setRenameDraft] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState("");
  const language = useLanguage();
  const t = useT();
  const ordered = sortChatSessions(sessions);

  function closeMenu() {
    setMenuFor("");
    setConfirmDeleteId("");
  }

  function submitRename(session: PawChatSession) {
    const clean = renameDraft.trim();
    setRenamingId("");
    if (clean && clean !== session.name) onRename(session, clean);
  }

  return (
    <aside className="qwenpaw-data-history" aria-label={t("history.aria")}>
      <header className="qwenpaw-data-history__header">
        <b>{t("history.sessions")}</b>
        <button
          type="button"
          className="qwenpaw-data-new-chat"
          disabled={busy || creating}
          onClick={onCreate}
        >
          {creating ? t("history.creating") : t("history.newChat")}
        </button>
      </header>
      <ul className="qwenpaw-data-history__list">
        {ordered.map((session) => {
          const isActive = session.sessionId === activeSessionId;
          const isLegacy = session.id === "legacy";
          return (
            <li
              key={session.id}
              className={[
                "qwenpaw-data-history__item",
                isActive ? "is-active" : "",
                session.pinned ? "is-pinned" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {renamingId === session.id ? (
                <form
                  className="qwenpaw-data-history__rename"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submitRename(session);
                  }}
                >
                  <input
                    autoFocus
                    aria-label={t("history.dialogueName")}
                    value={renameDraft}
                    maxLength={80}
                    onChange={(event) => setRenameDraft(event.target.value)}
                    onBlur={() => submitRename(session)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") setRenamingId("");
                    }}
                  />
                </form>
              ) : (
                <>
                  <button
                    type="button"
                    className="qwenpaw-data-history__open"
                    disabled={busy}
                    onClick={() => onSelect(session.sessionId)}
                  >
                    <b>
                      {session.pinned ? (
                        <i aria-label="Pinned">
                          <PinIcon size={12} />
                        </i>
                      ) : null}
                      {session.name}
                    </b>
                    <small>
                      {sessionTimestamp(session.updatedAt, language)}
                    </small>
                  </button>
                  {isLegacy ? null : (
                    <button
                      type="button"
                      className="qwenpaw-data-history__more"
                      aria-label={t("history.actionsFor", {
                        name: session.name,
                      })}
                      aria-expanded={menuFor === session.id}
                      onClick={() =>
                        menuFor === session.id
                          ? closeMenu()
                          : setMenuFor(session.id)
                      }
                    >
                      <EllipsisIcon size={14} />
                    </button>
                  )}
                  {menuFor === session.id ? (
                    <>
                      <div
                        className="qwenpaw-data-history__backdrop"
                        onClick={closeMenu}
                      />
                      <div className="qwenpaw-data-history__menu" role="menu">
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            closeMenu();
                            onTogglePin(session);
                          }}
                        >
                          {session.pinned
                            ? t("history.unpin")
                            : t("history.pin")}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            closeMenu();
                            setRenameDraft(session.name);
                            setRenamingId(session.id);
                          }}
                        >
                          {t("history.rename")}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            closeMenu();
                            onArchive(session);
                          }}
                        >
                          {t("history.archive")}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          className="is-danger"
                          onClick={() => {
                            if (confirmDeleteId !== session.id) {
                              setConfirmDeleteId(session.id);
                              return;
                            }
                            closeMenu();
                            onDelete(session);
                          }}
                        >
                          {confirmDeleteId === session.id
                            ? t("history.confirmDelete")
                            : t("history.delete")}
                        </button>
                      </div>
                    </>
                  ) : null}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

function AssistantBody({ text }: { text: string }) {
  const { body, marker } = splitCompletionMarker(text);
  return (
    <>
      <div className="qwenpaw-data-message__body qwenpaw-data-message__body--rich">
        {renderMarkdown(body)}
      </div>
      {marker ? (
        <div className="qwenpaw-data-run-summary">
          <i aria-hidden="true" />
          <span>{marker}</span>
        </div>
      ) : null}
    </>
  );
}

export function ChatWorkspace({
  paw,
  selectedSource,
  sources,
  selectedSourceId,
  onSelectSource,
}: {
  paw: PawAppSdk;
  selectedSource?: DataSourceMetadata;
  sources: DataSourceMetadata[];
  selectedSourceId: string;
  onSelectSource(id: string): void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<PawChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [creatingSession, setCreatingSession] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const language = useLanguage();
  const t = useT();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const sourceLabel = useMemo(
    () => selectedSource?.datasource_name || selectedSource?.datasource_id,
    [selectedSource],
  );
  const activeSession = sessions.find(
    (session) => session.sessionId === activeSessionId,
  );

  useEffect(() => {
    let cancelled = false;
    void paw.storage
      .get<boolean>("chat-history-open", true)
      .then((open) => {
        if (!cancelled) setHistoryOpen(open !== false);
      })
      .catch(() => undefined);
    void Promise.all([
      paw.chatSessions.list({ agentId: "qwenpaw-data" }),
      paw.storage.get<string>("active-chat-session", ""),
    ])
      .then(async ([available, storedSessionId]) => {
        if (cancelled) return;
        let next = available;
        if (next.length === 0) {
          next = [
            await paw.chatSessions.create({
              agentId: "qwenpaw-data",
              name: t("history.newAnalysis"),
            }),
          ];
        }
        if (cancelled) return;
        setSessions(next);
        const selected = next.some(
          (session) => session.sessionId === storedSessionId,
        )
          ? storedSessionId
          : next[0].sessionId;
        setActiveSessionId(selected);
      })
      .catch(() => {
        if (cancelled) return;
        const fallback: PawChatSession = {
          id: "legacy",
          sessionId: FALLBACK_CHAT_SESSION_ID,
          name: t("history.previousAnalysis"),
          createdAt: "",
          updatedAt: "",
          archived: false,
          pinned: false,
        };
        setSessions([fallback]);
        setActiveSessionId(fallback.sessionId);
        void paw
          .toast(t("session.legacyFallback"), "warning")
          .catch(() => undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [paw]);

  useEffect(() => {
    if (!activeSessionId) return;
    let cancelled = false;
    setRestoring(true);
    setMessages([]);
    void paw.storage
      .set("active-chat-session", activeSessionId)
      .catch(() => undefined);
    void paw
      .getChatHistory({
        agentId: "qwenpaw-data",
        sessionId: activeSessionId,
      })
      .then((history) => {
        if (cancelled) return;
        setMessages(historyToChatMessages(history.messages, language));
      })
      .catch(() => {
        if (!cancelled) {
          void paw
            .toast(t("session.restoreFailed"), "warning")
            .catch(() => undefined);
        }
      })
      .finally(() => {
        if (!cancelled) setRestoring(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeSessionId, paw]);

  useEffect(() => {
    if (!sending || !conversationRef.current) return;
    conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
  }, [messages, sending]);

  useEffect(() => {
    if (restoring || !conversationRef.current) return;
    conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
  }, [restoring]);

  async function createDialogue() {
    if (sending || creatingSession) return;
    setCreatingSession(true);
    try {
      const created = await paw.chatSessions.create({
        agentId: "qwenpaw-data",
        name: t("history.newAnalysis"),
      });
      setSessions((current) => [created, ...current]);
      setActiveSessionId(created.sessionId);
    } catch (error) {
      await paw.toast(
        t("session.createFailed", {
          detail: error instanceof Error ? error.message : String(error),
        }),
        "error",
      );
    } finally {
      setCreatingSession(false);
    }
  }

  function switchDialogue(sessionId: string) {
    if (!sessionId || sessionId === activeSessionId || sending) return;
    setActiveSessionId(sessionId);
  }

  function updateSession(updated: PawChatSession) {
    setSessions((current) =>
      current.map((session) => (session.id === updated.id ? updated : session)),
    );
  }

  function toggleHistory() {
    setHistoryOpen((open) => {
      void paw.storage.set("chat-history-open", !open).catch(() => undefined);
      return !open;
    });
  }

  async function sessionActionFailed(actionKey: StringKey, error: unknown) {
    await paw.toast(
      t("session.actionFailed", {
        action: t(actionKey),
        detail: error instanceof Error ? error.message : String(error),
      }),
      "error",
    );
  }

  function togglePin(session: PawChatSession) {
    void paw.chatSessions
      .pin(session.id, !session.pinned, { agentId: "qwenpaw-data" })
      .then(updateSession)
      .catch((error) => void sessionActionFailed("session.action.pin", error));
  }

  function renameDialogue(session: PawChatSession, name: string) {
    void paw.chatSessions
      .rename(session.id, name, { agentId: "qwenpaw-data" })
      .then(updateSession)
      .catch(
        (error) => void sessionActionFailed("session.action.rename", error),
      );
  }

  async function dropDialogue(session: PawChatSession) {
    const nextActive = nextActiveSessionId(
      sessions,
      session.sessionId,
      activeSessionId,
    );
    setSessions((current) =>
      current.filter((candidate) => candidate.id !== session.id),
    );
    if (nextActive === activeSessionId) return;
    if (nextActive) {
      setActiveSessionId(nextActive);
      return;
    }
    // The last dialogue is gone; keep the workspace usable with a fresh one.
    try {
      const created = await paw.chatSessions.create({
        agentId: "qwenpaw-data",
        name: t("history.newAnalysis"),
      });
      setSessions([created]);
      setActiveSessionId(created.sessionId);
    } catch (error) {
      await sessionActionFailed("session.action.replace", error);
    }
  }

  function archiveDialogue(session: PawChatSession) {
    void paw.chatSessions
      .archive(session.id, { agentId: "qwenpaw-data" })
      .then(() => dropDialogue(session))
      .catch(
        (error) => void sessionActionFailed("session.action.archive", error),
      );
  }

  function deleteDialogue(session: PawChatSession) {
    void paw.chatSessions
      .delete(session.id, { agentId: "qwenpaw-data" })
      .then(() => dropDialogue(session))
      .catch(
        (error) => void sessionActionFailed("session.action.delete", error),
      );
  }

  async function submit(question: string) {
    const clean = question.trim();
    if (!clean || sending || restoring || !activeSessionId) return;
    const sessionForTurn = activeSessionId;
    const shouldNameSession =
      messages.length === 0 &&
      activeSession &&
      DEFAULT_SESSION_NAMES.includes(activeSession.name) &&
      activeSession.id !== "legacy";
    const now = Date.now();
    const assistantId = `assistant-${now}`;
    const userMessage: ChatMessage = {
      id: `user-${now}`,
      role: "user",
      text: clean,
    };
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      text: "",
      trace: [],
      streaming: true,
    };
    setMessages((current) => [...current, userMessage, assistantMessage]);
    setDraft("");
    setSending(true);
    if (shouldNameSession && activeSession) {
      void paw.chatSessions
        .rename(activeSession.id, clean.slice(0, 64), {
          agentId: "qwenpaw-data",
        })
        .then(updateSession)
        .catch(() => undefined);
    }
    let streamState = createChatStreamState();
    try {
      const sourceContext = selectedSource
        ? `${SOURCE_CONTEXT_OPEN}Use QwenPaw-Data source ${selectedSource.datasource_id} (${sourceLabel}) for this request unless the user explicitly asks for another source.${SOURCE_CONTEXT_CLOSE}\n\n`
        : "";
      for await (const event of paw.chatStream(`${sourceContext}${clean}`, {
        agentId: "qwenpaw-data",
        sessionId: sessionForTurn,
      })) {
        streamState = reduceChatStreamEvent(streamState, event, language);
        const patch = streamMessagePatch(streamState);
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? { ...message, ...patch } : message,
          ),
        );
      }

      if (!streamState.completed) {
        const fallbackId = streamState.messageOrder.at(-1);
        streamState = {
          ...streamState,
          completed: true,
          finalMessageId: fallbackId,
          finalText:
            (fallbackId && streamState.textByMessage[fallbackId]) ||
            t("chat.noTextResponse"),
        };
        const patch = streamMessagePatch(streamState);
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? { ...message, ...patch } : message,
          ),
        );
      }
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                text: analysisErrorMessage(error, language),
                streaming: false,
              }
            : message,
        ),
      );
      await paw.toast(t("chat.analysisFailed"), "error");
    } finally {
      setSending(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(draft);
  }

  return (
    <section
      className={`qwenpaw-data-chat ${historyOpen ? "has-history" : ""}`.trim()}
      aria-label={t("chat.aria")}
    >
      <div className="qwenpaw-data-chat__main">
        <div className="qwenpaw-data-chat__topline qwenpaw-data-chat__toolbar">
          <div className="qwenpaw-data-chat__controls">
            <label className="qwenpaw-data-source-pill qwenpaw-data-source-pill--select">
              <span className="qwenpaw-data-source-pill__dot" />
              <select
                aria-label={t("chat.sourceSelect")}
                value={selectedSourceId}
                onChange={(event) => onSelectSource(event.target.value)}
              >
                <option value="">{t("chat.allContext")}</option>
                {sources.map((source) => (
                  <option
                    key={source.datasource_id}
                    value={source.datasource_id}
                  >
                    {source.datasource_name || source.datasource_id}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        <div
          className="qwenpaw-data-conversation"
          aria-live="polite"
          ref={conversationRef}
        >
          {restoring ? (
            <div className="qwenpaw-data-welcome">
              <h2>{t("chat.restoring")}</h2>
            </div>
          ) : messages.length === 0 ? (
            <div className="qwenpaw-data-welcome">
              <div className="qwenpaw-data-welcome__mark">
                <LogoMark />
              </div>
              <h2>{t("chat.welcomeTitle")}</h2>
              <p>{t("chat.welcomeBody")}</p>
              <div className="qwenpaw-data-starters">
                {STARTER_KEYS.map((starterKey) => {
                  const starter = t(starterKey);
                  return (
                    <button
                      key={starterKey}
                      type="button"
                      disabled={restoring}
                      onClick={() => void submit(starter)}
                    >
                      <span>{starter}</span>
                      <b aria-hidden="true">
                        <ArrowUpRightIcon size={12} />
                      </b>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="qwenpaw-data-messages">
              {messages.map((message) => (
                <article
                  className={`qwenpaw-data-message qwenpaw-data-message--${message.role}`}
                  key={message.id}
                >
                  <div className="qwenpaw-data-message__role">
                    {message.role === "user" ? t("chat.you") : "QwenPaw-Data"}
                  </div>
                  {message.role === "assistant" ? (
                    <>
                      <AnalysisTrace message={message} />
                      {message.text ? (
                        <AssistantBody text={message.text} />
                      ) : message.streaming && !message.activity ? (
                        <div
                          className="qwenpaw-data-thinking"
                          aria-label={t("chat.analyzing")}
                        >
                          <i /> <i /> <i />
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="qwenpaw-data-message__body">
                      {message.text}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </div>

        <form className="qwenpaw-data-composer" onSubmit={handleSubmit}>
          <textarea
            ref={inputRef}
            value={draft}
            rows={2}
            disabled={restoring || !activeSessionId}
            placeholder={t("chat.placeholder")}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit(draft);
              }
            }}
          />
          <button
            type="submit"
            disabled={!draft.trim() || sending || restoring}
            aria-label={t("chat.send")}
          >
            <ArrowUpIcon size={16} />
          </button>
          <div className="qwenpaw-data-composer__hint">{t("chat.hint")}</div>
        </form>
      </div>
      <div className="qwenpaw-data-history-rail">
        <button
          type="button"
          className="qwenpaw-data-history-tab"
          aria-expanded={historyOpen}
          aria-label={historyOpen ? t("history.collapse") : t("history.expand")}
          onClick={toggleHistory}
        >
          <i aria-hidden="true">{historyOpen ? "›" : "‹"}</i>
          <span>{t("history.sessions")}</span>
        </button>
        {historyOpen ? (
          <DialogueHistory
            sessions={sessions}
            activeSessionId={activeSessionId}
            busy={sending || restoring}
            creating={creatingSession}
            onCreate={() => void createDialogue()}
            onSelect={switchDialogue}
            onTogglePin={togglePin}
            onRename={renameDialogue}
            onArchive={archiveDialogue}
            onDelete={deleteDialogue}
          />
        ) : null}
      </div>
    </section>
  );
}
