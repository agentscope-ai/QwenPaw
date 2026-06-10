// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
import { chatApi } from "../../api/modules/chat";
export type CopyableContent = {
  type?: string;
  text?: string;
  refusal?: string;
};

export type CopyableMessage = {
  role?: string;
  content?: string | CopyableContent[];
};

export type CopyableResponse = {
  output?: CopyableMessage[];
};

export type RuntimeLoadingBridgeApi = {
  getLoading?: () => boolean | string;
  setLoading?: (loading: boolean | string) => void;
};

// ---------------------------------------------------------------------------
// Text extraction utilities
// ---------------------------------------------------------------------------

/** Extract copyable text from assistant response. */
export function extractCopyableText(response: CopyableResponse): string {
  const collectText = (assistantOnly: boolean) => {
    const chunks = (response.output || []).flatMap((item: CopyableMessage) => {
      if (assistantOnly && item.role !== "assistant") return [];

      if (typeof item.content === "string") {
        return [item.content];
      }

      if (!Array.isArray(item.content)) {
        return [];
      }

      return item.content.flatMap((content: CopyableContent) => {
        if (content.type === "text" && typeof content.text === "string") {
          return [content.text];
        }

        if (content.type === "refusal" && typeof content.refusal === "string") {
          return [content.refusal];
        }

        return [];
      });
    });

    return chunks.filter(Boolean).join("\n\n").trim();
  };

  return collectText(true) || JSON.stringify(response);
}

/** Extract plain text from user message content. */
export function extractUserMessageText(m: any): string {
  if (typeof m.content === "string") return m.content;
  if (!Array.isArray(m.content)) return "";
  return m.content
    .filter((p: any) => p.type === "text")
    .map((p: any) => p.text || "")
    .join("\n");
}

export function extractTextFromMessage(msg: any): string {
  const innerMessage = msg?.cards?.[0]?.data?.input?.[0];
  if (!innerMessage) return "";
  return extractUserMessageText(innerMessage);
}

// ---------------------------------------------------------------------------
// Clipboard utilities
// ---------------------------------------------------------------------------

/** Copy text to clipboard with fallback for non-secure contexts. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);

  let copied = false;
  try {
    textarea.focus();
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }

  if (!copied) {
    throw new Error("Failed to copy text");
  }
}

// ---------------------------------------------------------------------------
// Timestamp formatting utilities
// ---------------------------------------------------------------------------

/** Format a unix timestamp (seconds or milliseconds) to a short time string (HH:mm:ss). */
export function formatMessageTime(ts: number): string {
  if (!ts) return "";
  // Normalize to milliseconds
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const date = new Date(ms);
  const now = new Date();
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  const seconds = date.getSeconds().toString().padStart(2, "0");
  const time = `${hours}:${minutes}:${seconds}`;

  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (isToday) return time;

  const month = (date.getMonth() + 1).toString().padStart(2, "0");
  const day = date.getDate().toString().padStart(2, "0");
  if (date.getFullYear() === now.getFullYear()) {
    return `${month}-${day} ${time}`;
  }
  return `${date.getFullYear()}-${month}-${day} ${time}`;
}

// ---------------------------------------------------------------------------
// Error response utilities
// ---------------------------------------------------------------------------

/** Build a 400 error response when model is not configured. */
export function buildModelError(): Response {
  return new Response(
    JSON.stringify({
      error: "Model not configured",
      message: "Please configure a model first",
    }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
}

// ---------------------------------------------------------------------------
// URL normalization utilities
// ---------------------------------------------------------------------------

/** Decode each path segment; keeps `/` delimiters (including repeated `/`). */
function decodeUriPathSegments(path: string): string {
  return path
    .split("/")
    .map((segment) => {
      if (!segment) return segment;
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    })
    .join("/");
}

/** Convert file URL to stored path for backend: keep full path after `/files/preview/`. */
export function toStoredName(v: string): string {
  const marker = "/files/preview/";
  const idx = v.indexOf(marker);
  if (idx !== -1) {
    let rest = v.slice(idx + marker.length);
    const q = rest.indexOf("?");
    if (q !== -1) rest = rest.slice(0, q);
    const h = rest.indexOf("#");
    if (h !== -1) rest = rest.slice(0, h);
    if (rest) {
      const decoded = decodeUriPathSegments(rest);
      // Windows absolute path: C:\... or C:/...
      const isWindowsAbsolute = /^[a-zA-Z]:[\\/]/.test(decoded);
      if (isWindowsAbsolute) return decoded;
      return decoded.startsWith("/") ? decoded : `/${decoded}`;
    }
  }
  return v;
}

/** Convert content part URLs to stored name format. */
export function normalizeContentUrls(part: any): any {
  const p = { ...part };
  if (p.type === "image" && typeof p.image_url === "string")
    p.image_url = toStoredName(p.image_url);
  if (p.type === "file" && typeof p.file_url === "string")
    p.file_url = toStoredName(p.file_url);
  if (p.type === "audio" && typeof p.data === "string")
    p.data = toStoredName(p.data);
  if (p.type === "video" && typeof p.video_url === "string")
    p.video_url = toStoredName(p.video_url);
  return p;
}

/** Turn a backend content URL (path or full URL) into a full URL for display. */
export function toDisplayUrl(url: string | undefined): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("file://")) url = url.replace("file://", "");
  return chatApi.filePreviewUrl(url.startsWith("/") ? url : `/${url}`);
}

// ---------------------------------------------------------------------------
// Session key matching
// ---------------------------------------------------------------------------

/** Match a runner session_id against a key (UUID/timestamp).
 *  Accepts an exact match or `key` appearing as a whole `_`-delimited segment
 *  (the `<name>_<timestamp>` shape). Deliberately avoids arbitrary substring
 *  containment, which could mis-route one session to another's backend id.
 */
export function sessionIdMatchesKey(
  sessionId: string | undefined,
  key: string,
): boolean {
  if (!key) return false;
  const sid = sessionId || "";
  return (
    sid === key ||
    sid.endsWith(`_${key}`) ||
    sid.startsWith(`${key}_`) ||
    sid.includes(`_${key}_`)
  );
}

/** Match a session list row by display id, backend UUID, or runner session_id. */
export function sessionKeyMatches(
  entry: { id?: string; realId?: string; sessionId?: string },
  key: string,
): boolean {
  if (!key) return false;
  if (entry.id === key || entry.realId === key) return true;
  return sessionIdMatchesKey(entry.sessionId, key);
}

/** Build the inline response-card output item that carries a usage note.
 *  Shared by the live stop path (Chat page) and the reload path (sessionApi).
 */
export const USAGE_NOTE_META_KEY = "qwenpaw_usage_note";

/** Matches the prefix produced by ``format_usage_chat_note`` on the backend. */
function isUsageNoteMarkdown(text: string): boolean {
  return text.trimStart().startsWith("📊 **");
}

export function buildUsageNoteOutputItem(
  note: string,
): Record<string, unknown> {
  return {
    id: `stop-usage-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`,
    type: "message",
    role: "assistant",
    content: [{ type: "text", text: note, status: "completed" }],
    status: "completed",
    metadata: { [USAGE_NOTE_META_KEY]: true },
  };
}

const RESPONSE_CARD = "AgentScopeRuntimeResponseCard";

function getResponseCardData(
  cards: unknown,
): Record<string, unknown> | null {
  if (!Array.isArray(cards)) return null;
  const card = cards.find(
    (c) => (c as { code?: string })?.code === RESPONSE_CARD,
  ) as { data?: Record<string, unknown> } | undefined;
  return card?.data ?? null;
}

function outputItemHasUsageNote(item: Record<string, unknown>): boolean {
  const meta = item?.metadata;
  if (meta && typeof meta === "object" && !Array.isArray(meta)) {
    if ((meta as Record<string, unknown>)[USAGE_NOTE_META_KEY]) return true;
  }
  const content = item?.content;
  if (typeof content === "string") return isUsageNoteMarkdown(content);
  if (Array.isArray(content)) {
    return content.some(
      (c: Record<string, unknown>) =>
        typeof c?.text === "string" && isUsageNoteMarkdown(c.text),
    );
  }
  return false;
}

/** Check if a message already contains a usage note in its response cards. */
export function messageHasUsageNote(msg: {
  cards?: Array<{ code?: string; data?: Record<string, unknown> }>;
}): boolean {
  return (
    msg.cards?.some((card) => {
      if (card?.code !== RESPONSE_CARD) return false;
      const output = card?.data?.output;
      if (!Array.isArray(output)) return false;
      return output.some((item: Record<string, unknown>) =>
        outputItemHasUsageNote(item),
      );
    }) ?? false
  );
}

export function appendUsageNoteToResponseCard(
  data: Record<string, unknown>,
  note: string,
): void {
  if (!Array.isArray(data.output)) data.output = [];
  (data.output as Array<Record<string, unknown>>).push(
    buildUsageNoteOutputItem(note),
  );
}

/** Patch the last assistant message in-place; returns true if note is present. */
export function patchLastAssistantUsageNote(
  messages: Array<{ role?: string; cards?: unknown }>,
  note: string,
): boolean {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role !== "assistant" || !msg.cards) continue;
    if (messageHasUsageNote(msg as Parameters<typeof messageHasUsageNote>[0]))
      return true;
    const data = getResponseCardData(msg.cards);
    if (!data) continue;
    appendUsageNoteToResponseCard(data, note);
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// DOM utilities
// ---------------------------------------------------------------------------

/** Set textarea value and trigger input event for React state sync.
 * Uses native value setter to bypass React's internal value tracker.
 */
export function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  if (nativeValueSetter) {
    nativeValueSetter.call(textarea, value);
  } else {
    textarea.value = value;
  }
  textarea.selectionStart = textarea.selectionEnd = value.length;
  const event = new Event("input", { bubbles: true });
  textarea.dispatchEvent(event);
}
