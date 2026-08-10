import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import type { DataSourceMetadata } from "./api";
import type { PawAppSdk, PawChatStreamEvent } from "./sdk";

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

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  activity?: string;
  trace?: ChatTraceItem[];
  streaming?: boolean;
}

export interface ChatStreamState {
  textByMessage: Record<string, string>;
  messageOrder: string[];
  toolMessageIds: Record<string, string>;
  trace: ChatTraceItem[];
  finalMessageId?: string;
  finalText: string;
  completed: boolean;
}

const STARTERS = [
  "Summarize the key business domains and their north-star metrics.",
  "Find the largest week-over-week movement and explain possible drivers.",
  "Show which datasets can answer a customer retention question.",
];

const TOOL_LABELS: Record<string, string> = {
  datapaw_list_domains: "List business domains",
  datapaw_explore_entity: "Explore semantic entity",
  datapaw_search_context: "Search governed context",
  datapaw_execute_sql: "Execute governed SQL",
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

function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  return name
    .replace(/^datapaw_/, "")
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function parseToolOutput(output: unknown): {
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
    const detail = String(parsed.error || "Query failed").split("\n")[0];
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
      detail: `${total} row${total === 1 ? "" : "s"}`,
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

export function reduceChatStreamEvent(
  state: ChatStreamState,
  event: PawChatStreamEvent,
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
            ? parseToolOutput(data.output)
            : { status: "running" as const };
        next = {
          ...next,
          trace: upsertTrace(next.trace, {
            id: callId,
            name,
            label: toolLabel(name),
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

function analysisErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "MODEL_NOT_CONFIGURED"
  ) {
    return (
      "No language model is configured for this QwenPaw workspace. " +
      "Open Settings → Models, configure and activate a model, then retry."
    );
  }
  const detail = error instanceof Error ? error.message : String(error);
  return `I could not run that analysis. ${detail}`;
}

function ResultTable({ result }: { result: QueryResult }) {
  if (!result.columns.length || !result.rows.length) return null;
  return (
    <div className="datapaw-trace-result">
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
          Showing the first {Math.min(result.rows.length, 100)} rows.
        </small>
      ) : null}
    </div>
  );
}

function AnalysisTrace({ message }: { message: ChatMessage }) {
  const trace = message.trace || [];
  if (!message.activity && trace.length === 0) return null;
  return (
    <details className="datapaw-analysis-trace" open={message.streaming}>
      <summary>
        <span className={message.streaming ? "is-running" : ""} />
        {message.streaming
          ? "Live analysis"
          : `Analysis trace · ${trace.length} step${
              trace.length === 1 ? "" : "s"
            }`}
      </summary>
      <div className="datapaw-analysis-trace__body">
        {message.activity ? (
          <div className="datapaw-analysis-trace__narrative">
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

export function ChatWorkspace({
  paw,
  selectedSource,
}: {
  paw: PawAppSdk;
  selectedSource?: DataSourceMetadata;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const sourceLabel = useMemo(
    () => selectedSource?.datasource_name || selectedSource?.datasource_id,
    [selectedSource],
  );

  useEffect(() => {
    if (!sending || !conversationRef.current) return;
    conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
  }, [messages, sending]);

  async function submit(question: string) {
    const clean = question.trim();
    if (!clean || sending) return;
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
    let streamState = createChatStreamState();
    try {
      const sourceContext = selectedSource
        ? `Use QwenPaw-Data source ${selectedSource.datasource_id} (${sourceLabel}) for this request unless the user explicitly asks for another source.\n\n`
        : "";
      for await (const event of paw.chatStream(`${sourceContext}${clean}`, {
        agentId: "datapaw",
        sessionId: "pawapp:datapaw",
      })) {
        streamState = reduceChatStreamEvent(streamState, event);
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
            "The analysis completed without a text response.",
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
                text: analysisErrorMessage(error),
                streaming: false,
              }
            : message,
        ),
      );
      await paw.toast("QwenPaw-Data analysis failed", "error");
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
    <section className="datapaw-chat" aria-label="Data analysis chat">
      <div className="datapaw-chat__topline">
        <div>
          <span className="datapaw-eyebrow">Analysis workspace</span>
          <h1>Ask your data, with context.</h1>
        </div>
        <div className="datapaw-source-pill">
          <span className="datapaw-source-pill__dot" />
          {sourceLabel || "All available context"}
        </div>
      </div>

      <div
        className="datapaw-conversation"
        aria-live="polite"
        ref={conversationRef}
      >
        {messages.length === 0 ? (
          <div className="datapaw-welcome">
            <div className="datapaw-welcome__mark">
              <img
                src="/api/frontend_plugin/datapaw/files/ui/dist/app/logo-mark-v4.png"
                alt=""
              />
            </div>
            <h2>What would you like to understand?</h2>
            <p>
              QwenPaw-Data can retrieve semantic definitions, inspect
              relationships, and run governed queries through the selected data
              source.
            </p>
            <div className="datapaw-starters">
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  onClick={() => void submit(starter)}
                >
                  <span>{starter}</span>
                  <b aria-hidden="true">↗</b>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="datapaw-messages">
            {messages.map((message) => (
              <article
                className={`datapaw-message datapaw-message--${message.role}`}
                key={message.id}
              >
                <div className="datapaw-message__role">
                  {message.role === "user" ? "You" : "QwenPaw-Data"}
                </div>
                {message.role === "assistant" ? (
                  <>
                    <AnalysisTrace message={message} />
                    {message.text ? (
                      <div className="datapaw-message__body">
                        {message.text}
                      </div>
                    ) : message.streaming && !message.activity ? (
                      <div className="datapaw-thinking" aria-label="Analyzing">
                        <i /> <i /> <i />
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className="datapaw-message__body">{message.text}</div>
                )}
              </article>
            ))}
          </div>
        )}
      </div>

      <form className="datapaw-composer" onSubmit={handleSubmit}>
        <textarea
          ref={inputRef}
          value={draft}
          rows={2}
          placeholder="Ask about a metric, trend, dataset, or business question…"
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
          disabled={!draft.trim() || sending}
          aria-label="Send"
        >
          ↑
        </button>
        <div className="datapaw-composer__hint">
          QwenPaw-Data may execute read-only queries. Verify important
          decisions.
        </div>
      </form>
    </section>
  );
}
