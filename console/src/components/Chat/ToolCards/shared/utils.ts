/**
 * Shared utility functions for tool cards.
 * Extracted from ToolCallBlock.tsx for reuse across individual card plugins.
 */

import type { TFunction } from "i18next";
import type { ToolCallContent } from "./types";
import { chatApi } from "@/api/modules/chat";

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

/** Convert a backend file/image URL to a displayable URL */
export function toDisplayUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("data:")) return url;
  if (url.startsWith("file://")) url = url.replace("file://", "");
  return chatApi.filePreviewUrl(url.startsWith("/") ? url : `/${url}`);
}

// ---------------------------------------------------------------------------
// File helpers
// ---------------------------------------------------------------------------

/** Extract short file name from a path */
export function shortFileName(filePath: string): string {
  const parts = filePath.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || filePath;
}

/** Count lines in a string */
export function countLines(text: unknown): number {
  if (typeof text !== "string" || !text) return 0;
  return text.split("\n").length;
}

/** Get language identifier from file extension for syntax highlighting */
export function getFileLanguage(tc: ToolCallContent): string {
  const params = tc.params || {};
  const filePath = (
    (params.file_path || params.path || "") as string
  ).toLowerCase();
  const ext = filePath.match(/\.([^.]+)$/)?.[1] || "";

  const langMap: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    rb: "ruby",
    go: "go",
    rs: "rust",
    java: "java",
    kt: "kotlin",
    swift: "swift",
    cs: "csharp",
    cpp: "cpp",
    c: "c",
    h: "c",
    hpp: "cpp",
    html: "html",
    css: "css",
    less: "less",
    scss: "scss",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    toml: "toml",
    xml: "xml",
    sql: "sql",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    md: "markdown",
    txt: "text",
    conf: "ini",
    ini: "ini",
    dockerfile: "dockerfile",
    makefile: "makefile",
    vue: "vue",
    svelte: "svelte",
    dart: "dart",
    php: "php",
    lua: "lua",
    r: "r",
    scala: "scala",
    ex: "elixir",
    exs: "elixir",
  };

  return langMap[ext] || "";
}

// ---------------------------------------------------------------------------
// Media detection
// ---------------------------------------------------------------------------

const IMG_EXTS = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"];
const VIDEO_EXTS = ["mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"];
const AUDIO_EXTS = ["mp3", "wav", "flac", "ape", "aac", "ogg", "wma"];

export type MediaType = "image" | "video" | "audio" | "file";

export interface MediaInfo {
  url: string;
  name: string;
  type: MediaType;
  size?: number;
}

export function getFileExtFromPath(path: string): string {
  const match = path.match(/\.([^.?#]+)(?:[?#]|$)/);
  return match ? match[1].toLowerCase() : "";
}

function classifyMediaType(ext: string): MediaType {
  if (IMG_EXTS.includes(ext)) return "image";
  if (VIDEO_EXTS.includes(ext)) return "video";
  if (AUDIO_EXTS.includes(ext)) return "audio";
  return "file";
}

/** Extract media info from tool params/result */
export function getMediaInfo(tc: ToolCallContent): MediaInfo | null {
  const params = tc.params || {};

  if (tc.name === "send_file_to_user") {
    const filePath = (params.file_path || params.path || "") as string;
    if (!filePath) return null;
    const ext = getFileExtFromPath(filePath);
    const name = filePath.split("/").pop() || filePath;
    const mediaType = classifyMediaType(ext);

    let rawUrl = filePath;
    if (typeof tc.result === "string") {
      try {
        const parsed = JSON.parse(tc.result);
        if (parsed?.url) rawUrl = parsed.url;
        else if (parsed?.path) rawUrl = parsed.path;
      } catch {
        // Use filePath as-is
      }
    }
    return { url: toDisplayUrl(rawUrl), name, type: mediaType };
  }

  if (tc.name === "view_video") {
    const videoPath = (params.video_path || params.path || "") as string;
    if (!videoPath) return null;
    const name = videoPath.split("/").pop() || videoPath;
    return { url: toDisplayUrl(videoPath), name, type: "video" };
  }

  if (tc.name === "view_image") {
    const imgPath = (params.image_path || params.path || "") as string;
    if (!imgPath) return null;
    const name = imgPath.split("/").pop() || imgPath;
    return { url: toDisplayUrl(imgPath), name, type: "image" };
  }

  if (tc.name === "desktop_screenshot") {
    let rawUrl = "";
    if (typeof tc.result === "string") {
      try {
        const parsed = JSON.parse(tc.result);
        if (parsed?.path) rawUrl = parsed.path;
      } catch {
        const match = tc.result.match(/saved to (.+)/);
        if (match) rawUrl = match[1].trim();
      }
    }
    if (!rawUrl) return null;
    const name = rawUrl.split("/").pop() || "screenshot.png";
    return { url: toDisplayUrl(rawUrl), name, type: "image" };
  }

  // Generic: try to extract media from result for any tool
  if (tc.result && typeof tc.result === "string") {
    return extractMediaFromText(tc.result);
  }

  return null;
}

/** Try to extract media URL from a text result (JSON or plain text patterns) */
export function extractMediaFromText(resultStr: string): MediaInfo | null {
  // 1. JSON parsing
  try {
    const parsed = JSON.parse(resultStr);
    const rawUrl =
      parsed?.url ||
      parsed?.path ||
      parsed?.file_path ||
      parsed?.image_url ||
      parsed?.video_url ||
      parsed?.audio_url ||
      "";
    if (rawUrl) {
      const ext = getFileExtFromPath(rawUrl);
      const name = rawUrl.split("/").pop() || "file";
      const mediaType = classifyMediaType(ext);
      if (mediaType !== "file") {
        return { url: toDisplayUrl(rawUrl), name, type: mediaType };
      }
    }
  } catch {
    // Not JSON
  }

  // 2. "Saved to" pattern
  const pathMatch = resultStr.match(
    /(?:saved to|Saved to|保存到|输出到)[:\s]+([^\s\n]+)/i,
  );
  if (pathMatch) {
    const rawUrl = pathMatch[1].trim();
    const ext = getFileExtFromPath(rawUrl);
    const name = rawUrl.split("/").pop() || "file";
    const mediaType = classifyMediaType(ext);
    if (mediaType !== "file") {
      return { url: toDisplayUrl(rawUrl), name, type: mediaType };
    }
  }

  // 3. Absolute file path with known media extension
  const filePathMatch = resultStr.match(
    /\/[\w.\-/]+\.(?:png|jpg|jpeg|gif|bmp|webp|svg|mp4|avi|mov|wmv|flv|mkv|webm|mp3|wav|flac|aac|ogg)/i,
  );
  if (filePathMatch) {
    const rawUrl = filePathMatch[0];
    const ext = getFileExtFromPath(rawUrl);
    const name = rawUrl.split("/").pop() || "file";
    const mediaType = classifyMediaType(ext);
    if (mediaType !== "file") {
      return { url: toDisplayUrl(rawUrl), name, type: mediaType };
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/** Format memory_search result as markdown table */
export function formatMemorySearch(raw: string, t: TFunction): string {
  try {
    const items = JSON.parse(raw) as Array<{
      path?: string;
      snippet?: string;
      score?: number;
      start_line?: number;
      end_line?: number;
    }>;
    if (!Array.isArray(items) || items.length === 0) return raw;

    const rows = items.map((item) => {
      const fileName = item.path?.split("/").pop() || item.path || "unknown";
      const lines =
        item.start_line != null && item.end_line != null
          ? `L${item.start_line}-${item.end_line}`
          : "-";
      const score = item.score != null ? item.score.toFixed(2) : "-";
      const snippet = (item.snippet || "")
        .trim()
        .replace(/\n/g, " ")
        .slice(0, 80);
      return `| ${fileName} | ${lines} | ${score} | ${snippet} |`;
    });

    return `| ${t("tool.formatTable.file")} | ${t(
      "tool.formatTable.lineNumber",
    )} | ${t("tool.formatTable.score")} | ${t(
      "tool.formatTable.summary",
    )} |\n| --- | --- | --- | --- |\n${rows.join("\n")}`;
  } catch {
    return raw;
  }
}

/** Format list_agents result as markdown table */
export function formatAgentList(raw: string, t: TFunction): string {
  try {
    const parsed = JSON.parse(raw);
    const agents = (
      Array.isArray(parsed) ? parsed : parsed?.agents || []
    ) as Array<Record<string, unknown>>;
    if (!Array.isArray(agents) || agents.length === 0) return raw;

    const rows = agents.map((agent) => {
      const name = (agent.name ||
        agent.display_name ||
        agent.id ||
        "") as string;
      const id = (agent.id || agent.agent_id || "") as string;
      const desc = (agent.description || "") as string;
      const status = (agent.status || "") as string;
      return `| ${name} | \`${id}\` | ${desc} | ${status} |`;
    });

    return `| ${t("tool.formatTable.name")} | ${t("tool.formatTable.id")} | ${t(
      "tool.formatTable.description",
    )} | ${t(
      "tool.formatTable.status",
    )} |\n| --- | --- | --- | --- |\n${rows.join("\n")}`;
  } catch {
    return raw;
  }
}

/** Detect if content looks like markdown */
export function looksLikeMarkdown(text: string): boolean {
  if (/\|.+\|/.test(text) && /\|[\s-:]+\|/.test(text)) return true;
  const mdPatterns = /^(#{1,6}\s|[-*]\s|\d+\.\s|\*\*.+\*\*)/m;
  return mdPatterns.test(text);
}

/** Stringify tool result safely */
/**
 * Extract text from MCP content blocks: `[{ type: "text", text: "..." }, ...]`.
 * Returns joined text or null if the input is not MCP format.
 */
function extractMcpText(arr: unknown[]): string | null {
  const textParts = arr
    .filter(
      (item): item is { type: string; text: string } =>
        item != null &&
        typeof item === "object" &&
        (item as Record<string, unknown>).type === "text" &&
        typeof (item as Record<string, unknown>).text === "string",
    )
    .map((item) => item.text);
  return textParts.length > 0 ? textParts.join("\n") : null;
}

/**
 * Convert a tool result to a display string.
 *
 * Handles three cases:
 * 1. String that is a JSON-serialized MCP content block array → extract text
 * 2. Array of MCP content blocks → extract text
 * 3. Anything else → JSON.stringify or return as-is
 */
export function stringifyResult(result: unknown): string {
  if (typeof result === "string") {
    const trimmed = result.trim();
    if (trimmed.startsWith("[")) {
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed)) {
          const extracted = extractMcpText(parsed);
          if (extracted) return extracted;
        }
      } catch {
        // not valid JSON, return as-is
      }
    }
    return result;
  }
  if (Array.isArray(result)) {
    const extracted = extractMcpText(result);
    if (extracted) return extracted;
  }
  if (result != null) return JSON.stringify(result, null, 2);
  return "";
}
