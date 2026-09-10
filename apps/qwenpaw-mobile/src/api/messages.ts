import type {
  DisplayMessage,
  DisplayPart,
  DisplayTurn,
  WireMessage,
} from "./types";

const TOOL_TYPES = new Set([
  "plugin_call",
  "plugin_call_output",
  "plugin_result",
  "function_call",
  "function_call_output",
  "mcp_tool_call",
  "mcp_tool_call_output",
]);

const MEDIA_TYPES = new Set(["image", "video", "audio", "file"]);
const PROCESS_TEXT_LIMIT = 8000;

export function toDisplayMessages(messages: WireMessage[]): DisplayMessage[] {
  return messages.flatMap((message, index) => {
    const display = toDisplayMessage(message, index);
    return display ? [display] : [];
  });
}

export function toDisplayParts(
  content: WireMessage["content"],
): DisplayPart[] {
  return contentParts(content);
}

export function toDisplayTurns(messages: DisplayMessage[]): DisplayTurn[] {
  const turns: DisplayTurn[] = [];
  let current: DisplayMessage[] = [];

  const flush = () => {
    if (!current.length) return;
    turns.push(buildTurn(current));
    current = [];
  };

  for (const message of messages) {
    if (message.role === "user" && current.length) flush();
    current.push(message);
  }
  flush();
  return turns;
}

function toDisplayMessage(
  message: WireMessage,
  index: number,
): DisplayMessage | null {
  const type = String(message.type ?? "message");
  const role = message.role === "user"
    ? "user"
    : TOOL_TYPES.has(type) || message.role === "tool"
      ? "tool"
      : "assistant";
  const kind = type === "reasoning"
    ? "reasoning"
    : TOOL_TYPES.has(type) || role === "tool"
      ? "tool"
      : "message";
  const tool = kind === "tool" ? extractTool(message) : null;
  const parts = kind === "tool"
    ? tool?.parts ?? []
    : contentParts(message.content);

  if (!parts.length && kind !== "tool") return null;
  return {
    id: String(message.id ?? `${role}-${index}`),
    role,
    kind,
    parts,
    toolName: tool?.name,
    toolState: tool?.state,
    toolCallId: tool?.callId,
    toolInput: tool?.input,
    toolOutput: tool?.output,
  };
}

function buildTurn(messages: DisplayMessage[]): DisplayTurn {
  const user = messages.find((message) => message.role === "user") ?? null;
  const responses = messages.filter((message) => message !== user);
  let answerIndex = -1;
  for (let index = responses.length - 1; index >= 0; index -= 1) {
    const message = responses[index];
    if (
      message.role === "assistant" &&
      message.kind === "message" &&
      (message.parts.length || message.pending || message.error)
    ) {
      answerIndex = index;
      break;
    }
  }
  const answer = answerIndex >= 0 ? responses[answerIndex] : null;
  const process = responses.filter((_, index) => index !== answerIndex);
  const answerMedia = new Set(
    (answer?.parts ?? []).filter(isMediaPart).map(mediaKey),
  );
  const resultMedia = uniqueMedia(
    process.flatMap((message) => message.parts.filter(isMediaPart)),
  ).filter((part) => !answerMedia.has(mediaKey(part)));

  return {
    id: user?.id ?? messages[0].id,
    user,
    process,
    answer,
    resultMedia,
    pending: messages.some((message) => message.pending),
  };
}

function contentParts(content: WireMessage["content"]): DisplayPart[] {
  if (typeof content === "string") return textParts(content);
  if (Array.isArray(content)) {
    return content.flatMap((item) => contentItemParts(item));
  }
  if (content && typeof content === "object") {
    return contentItemParts(content as Record<string, unknown>);
  }
  return [];
}

function contentItemParts(item: Record<string, unknown>): DisplayPart[] {
  const type = String(item.type ?? "");
  if (type === "text" && typeof item.text === "string") {
    return textParts(item.text);
  }
  if (type === "image") {
    return mediaPart("image", item.image_url ?? sourceUrl(item), item);
  }
  if (type === "video") {
    return mediaPart("video", item.video_url ?? sourceUrl(item), item);
  }
  if (type === "audio") {
    return mediaPart("audio", item.data ?? sourceUrl(item), item);
  }
  if (type === "file") {
    return mediaPart("file", item.file_url ?? sourceUrl(item), item);
  }
  if (MEDIA_TYPES.has(type)) return [];
  if (typeof item.text === "string") return textParts(item.text);
  return [];
}

function extractTool(message: WireMessage): {
  name?: string;
  state?: string;
  callId?: string;
  input?: string;
  output?: string;
  parts: DisplayPart[];
} | null {
  if (!Array.isArray(message.content)) return { parts: [] };
  const dataItems = message.content.flatMap((item) => {
    const data = item.data;
    return data && typeof data === "object" && !Array.isArray(data)
      ? [data as Record<string, unknown>]
      : [];
  });
  const callData = dataItems.find((item) => "arguments" in item) ?? dataItems[0];
  const resultData = dataItems.find((item) => "output" in item);
  const data = callData ?? resultData;
  if (!data) return { parts: [] };
  const output = resultData?.output ?? data.output;
  return {
    name: stringValue(data.name ?? resultData?.name),
    state: stringValue(resultData?.state ?? data.state),
    callId: stringValue(data.call_id ?? resultData?.call_id ?? data.id),
    input: formatToolDetail(callData?.arguments),
    output: formatToolDetail(output),
    parts: [
      ...mediaPartsFromArguments(callData?.arguments),
      ...mediaPartsFromUnknown(output),
    ],
  };
}

function mediaPartsFromUnknown(value: unknown): DisplayPart[] {
  const parsed = parseJson(value);
  if (typeof parsed === "string") return mediaPartsFromText(parsed);
  if (Array.isArray(parsed)) {
    return parsed.flatMap((item) => mediaPartsFromUnknown(item));
  }
  if (!parsed || typeof parsed !== "object") return [];
  const item = parsed as Record<string, unknown>;
  const direct = contentItemParts(item).filter(isMediaPart);
  if (direct.length) return direct;
  if (item.type === "text" && typeof item.text === "string") {
    return mediaPartsFromText(item.text);
  }
  for (const key of ["output", "content", "result", "data"]) {
    if (key in item) {
      const nested = mediaPartsFromUnknown(item[key]);
      if (nested.length) return nested;
    }
  }
  return [];
}

function mediaPartsFromArguments(value: unknown): DisplayPart[] {
  const parsed = parseJson(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return [];
  const data = parsed as Record<string, unknown>;
  for (const key of ["file_path", "image_path", "video_path", "audio_path", "path"]) {
    const rawUrl = data[key];
    if (typeof rawUrl === "string" && isPreviewableUrl(rawUrl)) {
      return [pathMediaPart(rawUrl)];
    }
  }
  return [];
}

function mediaPartsFromText(value: string): DisplayPart[] {
  const match = value.match(
    /(?:file:\/\/)?(?:\/[\w.\-\p{L}]+)+(?:\/[\w.\-\p{L}]+)*\.(?:png|jpe?g|gif|bmp|webp|svg|mp4|mov|mkv|webm|mp3|wav|flac|aac|ogg|pdf|docx?|xlsx?|pptx?|txt|zip)/iu,
  );
  return match ? [pathMediaPart(match[0])] : [];
}

function pathMediaPart(url: string): DisplayPart {
  const name = fileName(url) || "文件";
  const extension = name.split(".").pop()?.toLocaleLowerCase() ?? "";
  if (["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"].includes(extension)) {
    return { type: "image", url, name };
  }
  if (["mp4", "mov", "mkv", "webm"].includes(extension)) {
    return { type: "video", url, name };
  }
  if (["mp3", "wav", "flac", "aac", "ogg"].includes(extension)) {
    return { type: "audio", url, name };
  }
  return { type: "file", url, name };
}

function isPreviewableUrl(value: string): boolean {
  return value.startsWith("/") ||
    value.startsWith("file://") ||
    value.startsWith("http://") ||
    value.startsWith("https://") ||
    /^[a-zA-Z]:[\\/]/.test(value);
}

function mediaPart(
  type: "image" | "video" | "audio" | "file",
  rawUrl: unknown,
  item: Record<string, unknown>,
): DisplayPart[] {
  if (typeof rawUrl !== "string" || !rawUrl.trim()) return [];
  const nameValue = item.filename ?? item.file_name ?? item.name;
  const name = typeof nameValue === "string" && nameValue
    ? nameValue
    : fileName(rawUrl);
  if (type === "file") return [{ type, url: rawUrl, name: name || "文件" }];
  return [{ type, url: rawUrl, name: name || undefined }];
}

function sourceUrl(item: Record<string, unknown>): unknown {
  const source = item.source;
  if (!source || typeof source !== "object" || Array.isArray(source)) return "";
  const data = source as Record<string, unknown>;
  if (data.type === "base64" && typeof data.data === "string") {
    const mediaType = typeof data.media_type === "string"
      ? data.media_type
      : "application/octet-stream";
    return `data:${mediaType};base64,${data.data}`;
  }
  return data.url;
}

function textParts(value: string): DisplayPart[] {
  return value.trim() ? [{ type: "text", text: value }] : [];
}

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function formatToolDetail(value: unknown): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const parsed = parseJson(value);
  const sanitized = sanitizeToolValue(parsed);
  const detail = typeof sanitized === "string"
    ? sanitized
    : JSON.stringify(sanitized, null, 2);
  if (!detail.trim()) return undefined;
  return detail.length > PROCESS_TEXT_LIMIT
    ? `${detail.slice(0, PROCESS_TEXT_LIMIT)}…`
    : detail;
}

function sanitizeToolValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeToolValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => [
      key,
      /token|password|secret|authorization|cookie/i.test(key)
        ? "••••••"
        : sanitizeToolValue(item),
    ]));
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isMediaPart(part: DisplayPart): boolean {
  return part.type !== "text";
}

function uniqueMedia(parts: DisplayPart[]): DisplayPart[] {
  const seen = new Set<string>();
  return parts.filter((part) => {
    const key = mediaKey(part);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function mediaKey(part: DisplayPart): string {
  return part.type === "text" ? `text:${part.text}` : `${part.type}:${part.url}`;
}

function fileName(value: string): string {
  return value.replace(/\\/g, "/").split("/").pop()?.split("?")[0] ?? "";
}
