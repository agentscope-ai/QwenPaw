import React, { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Attachments, Markdown } from "@agentscope-ai/chat";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import {
  FileTextOutlined,
  EditOutlined,
  FileAddOutlined,
  SearchOutlined,
  FolderOpenOutlined,
  PictureOutlined,
  VideoCameraOutlined,
  ClockCircleOutlined,
  GlobalOutlined,
  DashboardOutlined,
  SendOutlined,
  DesktopOutlined,
  ThunderboltOutlined,
  ChromeOutlined,
  TeamOutlined,
  MessageOutlined,
  RocketOutlined,
  SyncOutlined,
  ApiOutlined,
  BulbOutlined,
  ToolOutlined,
  DownloadOutlined,
} from "@ant-design/icons";
import { chatApi } from "@/api/modules/chat";
import type { ToolCallContent, ToolCardProps } from "../types";
import ShellExecutionCard, {
  SHELL_TOOL_NAMES,
} from "../ToolCards/ShellExecutionCard";
import styles from "./MessageList.module.less";

/** Convert a backend file/image URL to a displayable URL */
function toDisplayUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("data:")) return url;
  if (url.startsWith("file://")) url = url.replace("file://", "");
  return chatApi.filePreviewUrl(url.startsWith("/") ? url : `/${url}`);
}

/** Extract short file name from a path */
function shortFileName(filePath: string): string {
  const parts = filePath.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || filePath;
}

/** Count lines in a string */
function countLines(text: unknown): number {
  if (typeof text !== "string" || !text) return 0;
  return text.split("\n").length;
}

/** Generate human-readable label for known tool calls */
function getToolLabel(
  name: string,
  params: Record<string, unknown>,
  _result: unknown,
  t: TFunction,
): string | null {
  const p = params || {};

  switch (name) {
    // --- File I/O ---
    case "read_file": {
      const file = shortFileName((p.file_path || p.path || "") as string);
      return file ? t("tool.readFile", { file }) : t("tool.readFileDefault");
    }
    case "write_file": {
      const file = shortFileName((p.file_path || p.path || "") as string);
      return file ? t("tool.writeFile", { file }) : t("tool.writeFileDefault");
    }
    case "edit_file": {
      const file = shortFileName((p.file_path || p.path || "") as string);
      return file ? t("tool.editFile", { file }) : t("tool.editFileDefault");
    }
    case "append_file": {
      const file = shortFileName((p.file_path || p.path || "") as string);
      return file
        ? t("tool.appendFile", { file })
        : t("tool.appendFileDefault");
    }

    // --- File Search ---
    case "grep_search": {
      const pattern = (p.pattern || "") as string;
      return pattern
        ? t("tool.grepSearch", { pattern })
        : t("tool.grepSearchDefault");
    }
    case "glob_search": {
      const pattern = (p.pattern || "") as string;
      return pattern
        ? t("tool.globSearch", { pattern })
        : t("tool.globSearchDefault");
    }

    // --- View Media ---
    case "view_image": {
      const img = shortFileName((p.image_path || "") as string);
      return img
        ? t("tool.viewImage", { file: img })
        : t("tool.viewImageDefault");
    }
    case "view_video": {
      const vid = shortFileName((p.video_path || "") as string);
      return vid
        ? t("tool.viewVideo", { file: vid })
        : t("tool.viewVideoDefault");
    }

    // --- Other built-in ---
    case "get_current_time":
      return t("tool.getCurrentTime");
    case "set_user_timezone":
      return t("tool.setTimezone", {
        timezone: (p.timezone_name || "") as string,
      });
    case "get_token_usage":
      return t("tool.getTokenUsage");
    case "send_file_to_user": {
      const file = shortFileName((p.file_path || "") as string);
      return file ? t("tool.sendFile", { file }) : t("tool.sendFileDefault");
    }
    case "desktop_screenshot":
      return t("tool.desktopScreenshot");
    case "materialize_skill": {
      const skill = (p.name || "") as string;
      return skill
        ? t("tool.materializeSkill", { skill })
        : t("tool.materializeSkillDefault");
    }

    // --- Browser ---
    case "browser_use": {
      const action = (p.action || "") as string;
      const url = (p.url || "") as string;
      const selector = (p.selector || p.element || "") as string;
      const text = (p.text || "") as string;
      const w = p.width as number | undefined;
      const h = p.height as number | undefined;
      const key = (p.key || "") as string;
      const path = (p.path || "") as string;
      const code = (p.code || "") as string;
      const filename = (p.filename || "") as string;
      const tabAction = (p.tab_action || "") as string;
      const detail = (() => {
        switch (action) {
          case "start":
            return p.headed
              ? t("tool.browserAction.startHeaded")
              : t("tool.browserAction.start");
          case "stop":
            return t("tool.browserAction.stop");
          case "open":
            return url
              ? t("tool.browserAction.open", { url })
              : t("tool.browserAction.openDefault");
          case "navigate":
            return url
              ? t("tool.browserAction.navigate", { url })
              : t("tool.browserAction.navigateDefault");
          case "navigate_back":
            return t("tool.browserAction.navigateBack");
          case "click":
            return selector
              ? t("tool.browserAction.click", { selector })
              : t("tool.browserAction.clickDefault");
          case "type":
            return text
              ? t("tool.browserAction.type", {
                  text: text.length > 20 ? text.slice(0, 20) + "…" : text,
                })
              : t("tool.browserAction.typeDefault");
          case "snapshot":
            return t("tool.browserAction.snapshot");
          case "screenshot":
            return path
              ? t("tool.browserAction.screenshot", { path })
              : t("tool.browserAction.screenshotDefault");
          case "eval":
          case "evaluate":
            return code
              ? t("tool.browserAction.eval", {
                  code: code.length > 30 ? code.slice(0, 30) + "…" : code,
                })
              : t("tool.browserAction.evalDefault");
          case "run_code":
            return code
              ? t("tool.browserAction.runCode", {
                  code: code.length > 30 ? code.slice(0, 30) + "…" : code,
                })
              : t("tool.browserAction.runCodeDefault");
          case "close":
            return t("tool.browserAction.closePage");
          case "tabs":
            return tabAction
              ? t("tool.browserAction.tabs", { action: tabAction })
              : t("tool.browserAction.tabsDefault");
          case "fill_form":
            return t("tool.browserAction.fillForm");
          case "file_upload":
            return filename
              ? t("tool.browserAction.fileUpload", { filename })
              : t("tool.browserAction.fileUploadDefault");
          case "file_download":
            return filename
              ? t("tool.browserAction.fileDownload", { target: filename })
              : url
              ? t("tool.browserAction.fileDownload", { target: url })
              : t("tool.browserAction.fileDownloadDefault");
          case "press_key":
            return key
              ? t("tool.browserAction.pressKey", { key })
              : t("tool.browserAction.pressKeyDefault");
          case "hover":
            return selector
              ? t("tool.browserAction.hover", { selector })
              : t("tool.browserAction.hoverDefault");
          case "drag":
            return t("tool.browserAction.drag");
          case "select_option":
            return t("tool.browserAction.selectOption");
          case "wait_for":
            return text
              ? t("tool.browserAction.waitFor", { target: text })
              : selector
              ? t("tool.browserAction.waitFor", { target: selector })
              : t("tool.browserAction.waitForDefault");
          case "resize":
            return w && h
              ? t("tool.browserAction.resize", { w, h })
              : t("tool.browserAction.resizeDefault");
          case "pdf":
            return path
              ? t("tool.browserAction.pdf", { path })
              : t("tool.browserAction.pdfDefault");
          case "install":
            return t("tool.browserAction.install");
          case "batch":
            return t("tool.browserAction.batch");
          default:
            return action;
        }
      })();
      return t("tool.browserUse", { detail });
    }
    case "browser_navigate":
    case "navigate": {
      const url = (p.url || "") as string;
      return url
        ? t("tool.browserNavigate", { url })
        : t("tool.browserNavigateDefault");
    }
    case "browser_click":
    case "click":
      return t("tool.browserClick");
    case "browser_type":
    case "type":
      return t("tool.browserType");
    case "browser_snapshot":
    case "snapshot":
      return t("tool.browserSnapshot");
    case "browser_scroll":
    case "scroll":
      return t("tool.browserScroll");

    // --- Memory ---
    case "memory_search": {
      const query = (p.query || p.text || "") as string;
      const queryShort = query.length > 20 ? query.slice(0, 20) + "…" : query;
      return queryShort
        ? t("tool.memorySearch", { query: queryShort })
        : t("tool.memorySearchDefault");
    }

    // --- Agent management ---
    case "list_agents":
      return t("tool.listAgents");
    case "chat_with_agent": {
      const agent = (p.to_agent || "") as string;
      return agent
        ? t("tool.chatWithAgent", { agent })
        : t("tool.chatWithAgentDefault");
    }
    case "submit_to_agent": {
      const agent = (p.to_agent || "") as string;
      const task = (p.text || "") as string;
      const taskShort = task.length > 20 ? task.slice(0, 20) + "…" : task;
      return agent
        ? t("tool.submitToAgent", {
            agent,
            task: taskShort ? " " + taskShort : "",
          })
        : t("tool.submitToAgentDefault");
    }
    case "check_agent_task": {
      const agent = (p.agent_id || p.to_agent || "") as string;
      const taskId = (p.task_id || "") as string;
      if (agent && taskId) return t("tool.checkAgentTask", { agent, taskId });
      if (agent) return t("tool.checkAgentTaskAgent", { agent });
      return t("tool.checkAgentTaskDefault");
    }
    case "delegate_external_agent": {
      const runner = (p.runner || "") as string;
      return runner
        ? t("tool.delegateExternalAgent", { runner })
        : t("tool.delegateExternalAgentDefault");
    }

    default:
      return null;
  }
}

/** Get line count badge info for file/search tools */
function getLineBadge(
  tc: ToolCallContent,
  t: TFunction,
): { label: string; type: "read" | "write" | "search" } | null {
  const name = tc.name;
  const p = tc.params || {};

  switch (name) {
    case "read_file": {
      if (tc.result == null) return null;
      const lines = countLines(tc.result);
      return lines > 0
        ? { label: t("tool.lineBadge.lines", { count: lines }), type: "read" }
        : null;
    }
    case "write_file": {
      const content = (p.content as string) || "";
      if (!content) return null;
      return {
        label: t("tool.lineBadge.lines", { count: countLines(content) }),
        type: "write",
      };
    }
    case "append_file": {
      const content = (p.content as string) || "";
      if (!content) return null;
      return {
        label: t("tool.lineBadge.lines", { count: countLines(content) }),
        type: "write",
      };
    }
    case "grep_search": {
      if (tc.result == null) return null;
      const lines = countLines(tc.result);
      return lines > 0
        ? {
            label: t("tool.lineBadge.matches", { count: lines }),
            type: "search",
          }
        : null;
    }
    case "glob_search": {
      if (tc.result == null) return null;
      const lines = countLines(tc.result);
      return lines > 0
        ? { label: t("tool.lineBadge.files", { count: lines }), type: "search" }
        : null;
    }
    default:
      return null;
  }
}

/** Get icon for a tool, fallback to ToolOutlined */
function getToolIcon(name: string): React.ReactNode {
  switch (name) {
    case "read_file":
      return <FileTextOutlined />;
    case "write_file":
      return <FileAddOutlined />;
    case "edit_file":
      return <EditOutlined />;
    case "append_file":
      return <FileAddOutlined />;
    case "grep_search":
      return <SearchOutlined />;
    case "glob_search":
      return <FolderOpenOutlined />;
    case "view_image":
      return <PictureOutlined />;
    case "view_video":
      return <VideoCameraOutlined />;
    case "get_current_time":
      return <ClockCircleOutlined />;
    case "set_user_timezone":
      return <GlobalOutlined />;
    case "get_token_usage":
      return <DashboardOutlined />;
    case "send_file_to_user":
      return <SendOutlined />;
    case "desktop_screenshot":
      return <DesktopOutlined />;
    case "materialize_skill":
      return <ThunderboltOutlined />;
    case "browser_use":
    case "browser_navigate":
    case "navigate":
    case "browser_click":
    case "click":
    case "browser_type":
    case "type":
    case "browser_snapshot":
    case "snapshot":
    case "browser_scroll":
    case "scroll":
      return <ChromeOutlined />;
    case "memory_search":
      return <BulbOutlined />;
    case "list_agents":
      return <TeamOutlined />;
    case "chat_with_agent":
      return <MessageOutlined />;
    case "submit_to_agent":
      return <RocketOutlined />;
    case "check_agent_task":
      return <SyncOutlined />;
    case "delegate_external_agent":
      return <ApiOutlined />;
    default:
      return <ToolOutlined />;
  }
}

// ---------------------------------------------------------------------------
// Render type classification
// ---------------------------------------------------------------------------

type RenderMode = "code" | "diff" | "media" | "inline" | "markdown" | "default";

/** Decide how to render the tool content */
function getRenderMode(name: string): RenderMode {
  switch (name) {
    // Code/monospace: file content, search results
    case "read_file":
    case "grep_search":
    case "glob_search":
    case "browser_snapshot":
    case "snapshot":
      return "code";

    // Diff view
    case "edit_file":
      return "diff";

    // Write tools: show written content as code
    case "write_file":
    case "append_file":
      return "code";

    // Media preview (image/audio/video/file with inline player/preview)
    case "view_image":
    case "desktop_screenshot":
    case "send_file_to_user":
    case "view_video":
      return "media";

    // Inline result (shown in title)
    case "get_current_time":
    case "set_user_timezone":
    case "submit_to_agent":
      return "inline";

    // Markdown for structured text
    case "get_token_usage":
    case "chat_with_agent":
    case "check_agent_task":
    case "memory_search":
    case "list_agents":
      return "markdown";

    default:
      return "default";
  }
}

/** Get language identifier from file extension for syntax highlighting */
function getFileLanguage(tc: ToolCallContent): string {
  const p = tc.params || {};
  const filePath = ((p.file_path || p.path || "") as string).toLowerCase();
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

/** Format memory_search result as markdown table */
function formatMemorySearch(raw: string, t: TFunction): string {
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
function formatAgentList(raw: string, t: TFunction): string {
  try {
    const parsed = JSON.parse(raw);
    const agents = (
      Array.isArray(parsed) ? parsed : parsed?.agents || []
    ) as Array<Record<string, unknown>>;
    if (!Array.isArray(agents) || agents.length === 0) return raw;

    const rows = agents.map((a) => {
      const name = (a.name || a.display_name || a.id || "") as string;
      const id = (a.id || a.agent_id || "") as string;
      const desc = (a.description || "") as string;
      const status = (a.status || "") as string;
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

/** Get the content to display when expanded (for built-in tools) */
function getDisplayContent(tc: ToolCallContent, t: TFunction): string {
  const p = tc.params || {};
  const name = tc.name;

  // Write tools: show what was written
  if (name === "write_file" || name === "append_file") {
    return (p.content as string) || "";
  }

  // edit_file handled by diff renderer
  if (name === "edit_file") return "";

  // memory_search: format as table
  if (name === "memory_search") {
    const raw =
      typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result);
    return formatMemorySearch(raw, t);
  }

  // list_agents: format as table
  if (name === "list_agents") {
    const raw =
      typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result);
    return formatAgentList(raw, t);
  }

  // Default: show tool result
  const raw = tc.result;
  if (typeof raw === "string") return raw;
  if (raw != null) return JSON.stringify(raw, null, 2);
  return "";
}

/** For inline tools, extract a short result to show in the title */
function getInlineResult(tc: ToolCallContent, t: TFunction): string | null {
  if (tc.status !== "done" || !tc.result) return null;
  const result = typeof tc.result === "string" ? tc.result : "";
  if (!result) return null;

  // submit_to_agent: extract TASK_ID
  if (tc.name === "submit_to_agent") {
    const match = result.match(/\[TASK_ID:\s*(.+?)\]/);
    return match
      ? t("tool.inlineResult.taskId", { id: match[1] })
      : t("tool.inlineResult.submitted");
  }

  // Truncate long results
  return result.length > 60 ? result.slice(0, 60) + "…" : result;
}

// Media type detection
const IMG_EXTS = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"];
const VIDEO_EXTS = ["mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"];
const AUDIO_EXTS = ["mp3", "wav", "flac", "ape", "aac", "ogg", "wma"];

function getFileExtFromPath(path: string): string {
  const match = path.match(/\.([^.?#]+)(?:[?#]|$)/);
  return match ? match[1].toLowerCase() : "";
}

type MediaType = "image" | "video" | "audio" | "file";

interface MediaInfo {
  url: string;
  name: string;
  type: MediaType;
  size?: number;
}

/** Extract media info from tool params/result */
function getMediaInfo(tc: ToolCallContent): MediaInfo | null {
  const p = tc.params || {};

  // send_file_to_user: file_path in params, result may have path/url
  if (tc.name === "send_file_to_user") {
    const filePath = (p.file_path || p.path || "") as string;
    if (!filePath) return null;
    const ext = getFileExtFromPath(filePath);
    const name = filePath.split("/").pop() || filePath;
    let mediaType: MediaType = "file";
    if (IMG_EXTS.includes(ext)) mediaType = "image";
    else if (VIDEO_EXTS.includes(ext)) mediaType = "video";
    else if (AUDIO_EXTS.includes(ext)) mediaType = "audio";

    // Try to get URL from result
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

  // view_video
  if (tc.name === "view_video") {
    const videoPath = (p.video_path || p.path || "") as string;
    if (!videoPath) return null;
    const name = videoPath.split("/").pop() || videoPath;
    return { url: toDisplayUrl(videoPath), name, type: "video" };
  }

  // view_image
  if (tc.name === "view_image") {
    const imgPath = (p.image_path || p.path || "") as string;
    if (!imgPath) return null;
    const name = imgPath.split("/").pop() || imgPath;
    return { url: toDisplayUrl(imgPath), name, type: "image" };
  }

  // desktop_screenshot
  if (tc.name === "desktop_screenshot") {
    // Result may contain path
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
    const resultStr = tc.result;

    // 1. Try JSON parsing
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
        let mediaType: MediaType = "file";
        if (IMG_EXTS.includes(ext)) mediaType = "image";
        else if (VIDEO_EXTS.includes(ext)) mediaType = "video";
        else if (AUDIO_EXTS.includes(ext)) mediaType = "audio";
        if (mediaType !== "file") {
          return { url: toDisplayUrl(rawUrl), name, type: mediaType };
        }
      }
    } catch {
      // Not JSON — try plain text patterns
    }

    // 2. Try extracting file path from plain text (e.g. "Saved to: /path/file.png")
    const pathMatch = resultStr.match(
      /(?:saved to|Saved to|保存到|输出到)[:\s]+([^\s\n]+)/i,
    );
    if (pathMatch) {
      const rawUrl = pathMatch[1].trim();
      const ext = getFileExtFromPath(rawUrl);
      const name = rawUrl.split("/").pop() || "file";
      let mediaType: MediaType = "file";
      if (IMG_EXTS.includes(ext)) mediaType = "image";
      else if (VIDEO_EXTS.includes(ext)) mediaType = "video";
      else if (AUDIO_EXTS.includes(ext)) mediaType = "audio";
      if (mediaType !== "file") {
        return { url: toDisplayUrl(rawUrl), name, type: mediaType };
      }
    }

    // 3. Try matching any absolute file path with known media extension
    const filePathMatch = resultStr.match(
      /\/[\w.\-/]+\.(?:png|jpg|jpeg|gif|bmp|webp|svg|mp4|avi|mov|wmv|flv|mkv|webm|mp3|wav|flac|aac|ogg)/i,
    );
    if (filePathMatch) {
      const rawUrl = filePathMatch[0];
      const ext = getFileExtFromPath(rawUrl);
      const name = rawUrl.split("/").pop() || "file";
      let mediaType: MediaType = "file";
      if (IMG_EXTS.includes(ext)) mediaType = "image";
      else if (VIDEO_EXTS.includes(ext)) mediaType = "video";
      else if (AUDIO_EXTS.includes(ext)) mediaType = "audio";
      if (mediaType !== "file") {
        return { url: toDisplayUrl(rawUrl), name, type: mediaType };
      }
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// DefaultBlock: Input/Output block with title + copy button (matching Spark)
// ---------------------------------------------------------------------------

/** Detect if content looks like markdown (tables, lists, headers) */
function looksLikeMarkdown(text: string): boolean {
  // Table pattern: |---|
  if (/\|.+\|/.test(text) && /\|[\s-:]+\|/.test(text)) return true;
  // Has markdown headers, lists, or bold
  const mdPatterns = /^(#{1,6}\s|[-*]\s|\d+\.\s|\*\*.+\*\*)/m;
  if (mdPatterns.test(text)) return true;
  return false;
}

function DefaultBlock({
  title,
  content,
  copyTitle,
}: {
  title: string;
  content: string;
  copyTitle?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMd = useMemo(() => looksLikeMarkdown(content), [content]);

  const handleCopy = useCallback(() => {
    navigator.clipboard
      .writeText(content)
      .then(() => {
        if (timerRef.current) clearTimeout(timerRef.current);
        setCopied(true);
        timerRef.current = setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {});
  }, [content]);

  return (
    <div className={styles.defaultBlock}>
      <div className={styles.defaultBlockHeader}>
        <span className={styles.defaultBlockTitle}>{title}</span>
        <button
          className={styles.defaultBlockCopy}
          onClick={handleCopy}
          title={copyTitle}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
        </button>
      </div>
      {isMd ? (
        <div className={styles.defaultBlockContentMd}>
          <Markdown content={content} />
        </div>
      ) : (
        <pre className={styles.defaultBlockContent}>{content}</pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ToolCallBlockProps {
  content: ToolCallContent;
  isStreaming: boolean;
  registry: Record<string, React.FC<ToolCardProps>>;
}

const ToolCallBlock: React.FC<ToolCallBlockProps> = ({
  content,
  isStreaming,
  registry,
}) => {
  const { t } = useTranslation();

  // 1. Check custom card registry first
  const CardComponent = registry[content.name];
  if (CardComponent) {
    const data = (content.result as Record<string, unknown>) || content.params;
    return (
      <CardComponent
        data={data}
        status={content.status}
        toolName={content.name}
      />
    );
  }

  // 2. Built-in specialized cards
  if (SHELL_TOOL_NAMES.has(content.name)) {
    return (
      <ShellExecutionCard
        data={content.params}
        status={content.status}
        toolName={content.name}
        toolCallContent={content}
      />
    );
  }

  // 3. Default: compact single-line, click to expand result
  const humanLabel = getToolLabel(
    content.name,
    content.params,
    content.result,
    t,
  );
  const title = humanLabel
    ? humanLabel
    : content.serverLabel
    ? `${content.serverLabel} / ${content.name}`
    : content.name;

  const isLoading = content.status === "calling" && isStreaming;
  const isError = content.status === "error";
  const renderMode = getRenderMode(content.name);
  const inlineResult = getInlineResult(content, t);
  const displayContent = getDisplayContent(content, t);
  const mediaInfo = getMediaInfo(content);
  const icon = getToolIcon(content.name);

  return (
    <details
      className={`${styles.toolCallCompact} ${
        isLoading ? styles.toolCallCompactLoading : ""
      } ${isError ? styles.toolCallCompactError : ""}`}
    >
      <summary className={styles.toolCallCompactSummary}>
        {isLoading ? (
          <span className={styles.toolCallSpinner} />
        ) : (
          <span
            className={`${styles.toolCallIcon} ${
              isError ? styles.toolCallIconError : styles.toolCallIconSuccess
            }`}
          >
            {icon}
          </span>
        )}
        <span className={styles.toolCallLabel}>
          {title}
          {isLoading && t("tool.loading")}
        </span>
        {content.name === "edit_file" && content.params && !isLoading && (
          <>
            <span className={styles.diffAddBadge}>
              {t("tool.lineBadge.addLines", {
                count: ((content.params.new_text as string) || "").split("\n")
                  .length,
              })}
            </span>
            <span className={styles.diffDelBadge}>
              {t("tool.lineBadge.delLines", {
                count: ((content.params.old_text as string) || "").split("\n")
                  .length,
              })}
            </span>
          </>
        )}
        {content.name !== "edit_file" &&
          !isLoading &&
          (() => {
            const badge = getLineBadge(content, t);
            if (!badge) return null;
            const cls =
              badge.type === "write"
                ? styles.diffAddBadge
                : badge.type === "read"
                ? styles.lineReadBadge
                : styles.lineSearchBadge;
            return <span className={cls}>{badge.label}</span>;
          })()}
        {renderMode === "inline" && inlineResult && (
          <span className={styles.toolCallInlineResult}>{inlineResult}</span>
        )}
      </summary>

      {/* Diff: edit_file */}
      {renderMode === "diff" && content.params && (
        <div className={styles.toolCallDiff}>
          {((content.params.old_text as string) || "")
            .split("\n")
            .map((line, i) => (
              <div key={`d${i}`} className={styles.diffLineDel}>
                - {line}
              </div>
            ))}
          {((content.params.new_text as string) || "")
            .split("\n")
            .map((line, i) => (
              <div key={`a${i}`} className={styles.diffLineAdd}>
                + {line}
              </div>
            ))}
        </div>
      )}

      {/* Code: file content, search results — with language hint */}
      {renderMode === "code" && displayContent && (
        <div className={styles.toolCallResultMd}>
          {getFileLanguage(content) === "markdown" ? (
            <Markdown content={displayContent} />
          ) : (
            <Markdown
              content={`\`\`\`${getFileLanguage(
                content,
              )}\n${displayContent}\n\`\`\``}
            />
          )}
        </div>
      )}

      {/* Markdown: token usage, agent replies, etc. */}
      {renderMode === "markdown" && displayContent && (
        <div className={styles.toolCallResultMd}>
          <Markdown content={displayContent} />
        </div>
      )}

      {/* Media preview for known media tools */}
      {renderMode === "media" && mediaInfo && (
        <div className={styles.toolCallMediaPreview}>
          {mediaInfo.type === "image" && (
            <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
              <div className={styles.toolCallImage}>
                <Image
                  src={mediaInfo.url}
                  style={{ width: "100%", objectFit: "contain" }}
                  preview={{ transitionName: "" }}
                />
              </div>
            </ConfigProvider>
          )}
          {mediaInfo.type === "video" && (
            <div className={styles.bubbleVideo}>
              <Video src={mediaInfo.url} controls />
            </div>
          )}
          {mediaInfo.type === "audio" && (
            <div className={styles.bubbleAudio}>
              <Audio src={mediaInfo.url} />
            </div>
          )}
          {mediaInfo.type === "file" && (
            <div className={styles.bubbleFile}>
              <Attachments.FileCard
                item={
                  {
                    uid: mediaInfo.name,
                    name: mediaInfo.name,
                    url: mediaInfo.url,
                    status: "done",
                  } as any
                }
              />
              {mediaInfo.url && (
                <div
                  className={styles.bubbleFileDownload}
                  onClick={() => window.open(mediaInfo.url, "_blank")}
                >
                  <DownloadOutlined />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Default tools: media preview first, then Input/Output blocks */}
      {renderMode === "default" && (
        <div className={styles.toolCallDefaultBody}>
          {mediaInfo && content.status === "done" && (
            <div className={styles.toolCallMediaPreview}>
              {mediaInfo.type === "image" && (
                <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
                  <div className={styles.toolCallImage}>
                    <Image
                      src={mediaInfo.url}
                      style={{ width: "100%", objectFit: "contain" }}
                      preview={{ transitionName: "" }}
                    />
                  </div>
                </ConfigProvider>
              )}
              {mediaInfo.type === "video" && (
                <div className={styles.bubbleVideo}>
                  <Video src={mediaInfo.url} controls />
                </div>
              )}
              {mediaInfo.type === "audio" && (
                <div className={styles.bubbleAudio}>
                  <Audio src={mediaInfo.url} />
                </div>
              )}
              {mediaInfo.type === "file" && (
                <div className={styles.bubbleFile}>
                  <Attachments.FileCard
                    item={
                      {
                        uid: mediaInfo.name,
                        name: mediaInfo.name,
                        url: mediaInfo.url,
                        status: "done",
                      } as any
                    }
                  />
                  {mediaInfo.url && (
                    <div
                      className={styles.bubbleFileDownload}
                      onClick={() => window.open(mediaInfo.url, "_blank")}
                    >
                      <DownloadOutlined />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          {content.params && Object.keys(content.params).length > 0 && (
            <DefaultBlock
              title={t("tool.input")}
              content={JSON.stringify(content.params, null, 2)}
              copyTitle={t("tool.copy")}
            />
          )}
          {content.result != null && (
            <DefaultBlock
              title={t("tool.output")}
              content={
                typeof content.result === "string"
                  ? content.result
                  : JSON.stringify(content.result, null, 2)
              }
              copyTitle={t("tool.copy")}
            />
          )}
        </div>
      )}
    </details>
  );
};

export default ToolCallBlock;
