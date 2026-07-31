import { useCallback, useRef, useState } from "react";

import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import sessionApi from "../Chat/sessionApi";

/**
 * Minimal Doubao-style quick-input page: a single text box plus a streamed
 * reply. Loaded in the floating quick-input window (route /quick-input),
 * summoned by the global hotkey registered on the Tauri side. See #6568.
 *
 * Deliberately slim — does NOT mount the full AgentScopeRuntimeWebUI; it
 * POSTs the user's text directly to /console/chat (stream:true) and renders
 * the streamed assistant text. Session identity comes from
 * sessionApi.getSessionIdentity(), which returns safe defaults in a fresh
 * window (the backend creates the conversation on the first message).
 */
const STYLES = {
  root: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100vh",
    background: "#1e1e1e",
    color: "#e8e8e8",
    fontFamily: "system-ui, sans-serif",
  },
  textarea: {
    flex: "0 0 auto",
    minHeight: 56,
    maxHeight: 160,
    margin: 12,
    padding: 12,
    borderRadius: 10,
    border: "1px solid #444",
    background: "#2a2a2a",
    color: "#e8e8e8",
    fontSize: 15,
    resize: "none" as const,
    outline: "none",
  },
  reply: {
    flex: "1 1 auto",
    margin: "0 12px 12px",
    padding: 12,
    borderRadius: 10,
    background: "#262626",
    overflowY: "auto" as const,
    whiteSpace: "pre-wrap" as const,
    fontSize: 14,
    lineHeight: 1.5,
  },
};

export default function QuickInputPage() {
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async () => {
    const query = text.trim();
    if (!query || loading) return;
    setLoading(true);
    setReply("");
    const controller = new AbortController();
    abortRef.current = controller;

    const identity = sessionApi.getSessionIdentity();
    const body = {
      input: [{ role: "user", content: [{ type: "text", text: query }] }],
      session_id: identity.sessionId,
      user_id: identity.userId,
      channel: identity.channel,
      stream: true,
    };

    try {
      const res = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders() },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        setReply(`Error: HTTP ${res.status}`);
        return;
      }

      // Minimal SSE reader (mirrors parseSseDataLines in Chat/turnUsage.ts).
      // res.body is a ReadableStream; use the reader API (the TS lib here
      // doesn't include ReadableStream's async iterator).
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done || !value) break;
        buffer += decoder.decode(value, { stream: true });
        for (;;) {
          const sep = buffer.indexOf("\n\n");
          if (sep < 0) break;
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of block.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            let payload: Record<string, unknown>;
            try {
              payload = JSON.parse(line.slice(6)) as Record<string, unknown>;
            } catch {
              continue;
            }
            if (
              payload.type === "turn_usage" ||
              payload.type === "rate_limited"
            ) {
              continue;
            }
            const delta = extractAssistantText(payload);
            if (delta) setReply(delta); // full-output convention: replace
          }
        }
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== "AbortError") {
        setReply(`Error: ${String(e)}`);
      }
    } finally {
      setLoading(false);
    }
  }, [text, loading]);

  return (
    <div style={STYLES.root}>
      <textarea
        style={STYLES.textarea}
        placeholder="Ask anything…  (Enter to send, Shift+Enter for newline)"
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void send();
          }
        }}
      />
      <div style={STYLES.reply}>{reply || (loading ? "…" : "")}</div>
    </div>
  );
}

/** Extract the assistant's text from a streamed payload's `output` array.
 * Mirrors extractTextFromContent (sessionApi/index.ts) + the payload shape
 * consumed by responseParser (Chat/index.tsx). */
function extractAssistantText(payload: Record<string, unknown>): string {
  const out = Array.isArray(payload.output) ? payload.output : [];
  return out
    .filter((m): m is { content: unknown } => {
      const msg = m as { role?: string };
      return msg?.role === "assistant";
    })
    .flatMap((m) => (Array.isArray(m.content) ? m.content : []))
    .filter((c): c is { type?: string; text?: string } => c?.type === "text")
    .map((c) => c.text || "")
    .join("");
}
