import { FormEvent, useMemo, useRef, useState } from "react";

import type { DataSourceMetadata } from "./api";
import type { PawAppSdk } from "./sdk";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
}

const STARTERS = [
  "Summarize the key business domains and their north-star metrics.",
  "Find the largest week-over-week movement and explain possible drivers.",
  "Show which datasets can answer a customer retention question.",
];

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
  const sourceLabel = useMemo(
    () => selectedSource?.datasource_name || selectedSource?.datasource_id,
    [selectedSource],
  );

  async function submit(question: string) {
    const clean = question.trim();
    if (!clean || sending) return;
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: clean,
    };
    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setSending(true);
    try {
      const sourceContext = selectedSource
        ? `Use QwenPaw-Data source ${selectedSource.datasource_id} (${sourceLabel}) for this request unless the user explicitly asks for another source.\n\n`
        : "";
      const reply = await paw.chat(`${sourceContext}${clean}`, {
        agentId: "datapaw",
        sessionId: "pawapp:datapaw",
      });
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          text: reply || "The analysis completed without a text response.",
        },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          text: analysisErrorMessage(error),
        },
      ]);
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

      <div className="datapaw-conversation" aria-live="polite">
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
              QwenPaw-Data can retrieve semantic definitions, inspect relationships,
              and run governed queries through the selected data source.
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
                <div className="datapaw-message__body">{message.text}</div>
              </article>
            ))}
            {sending ? (
              <article className="datapaw-message datapaw-message--assistant">
                <div className="datapaw-message__role">QwenPaw-Data</div>
                <div className="datapaw-thinking" aria-label="Analyzing">
                  <i /> <i /> <i />
                </div>
              </article>
            ) : null}
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
          QwenPaw-Data may execute read-only queries. Verify important decisions.
        </div>
      </form>
    </section>
  );
}
