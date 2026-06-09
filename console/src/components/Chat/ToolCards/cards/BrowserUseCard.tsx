import React from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { ChromeOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

/**
 * Try to extract meaningful fields from a browser tool result object.
 * Returns extracted text or null if the object doesn't have known fields.
 */
/** Unescape literal \n \t sequences that survived double-serialization. */
function unescapeLiterals(text: string): string {
  return text.replace(/\\n/g, "\n").replace(/\\t/g, "\t");
}

function extractBrowserFields(obj: Record<string, unknown>): string | null {
  const parts: string[] = [];
  if (obj.snapshot && typeof obj.snapshot === "string") {
    parts.push(unescapeLiterals(obj.snapshot));
  }
  if (obj.message && typeof obj.message === "string") {
    parts.push(obj.message);
  }
  if (obj.url && typeof obj.url === "string" && !obj.snapshot) {
    parts.push(`URL: ${obj.url}`);
  }
  return parts.length > 0 ? parts.join("\n\n") : null;
}

/**
 * Extract human-readable text from browser tool results.
 * Handles: string JSON, parsed object, MCP content blocks wrapping JSON.
 */
function formatBrowserResult(result: unknown): string {
  if (result == null) return "";

  // Case 1: result is already an object with snapshot/message/url
  if (typeof result === "object" && !Array.isArray(result)) {
    const extracted = extractBrowserFields(result as Record<string, unknown>);
    if (extracted) return extracted;
  }

  // Case 2: result is a string — try parsing as JSON
  if (typeof result === "string") {
    const trimmed = result.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        const parsed = JSON.parse(trimmed);
        // Could be a direct object
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          const extracted = extractBrowserFields(
            parsed as Record<string, unknown>,
          );
          if (extracted) return extracted;
        }
        // Could be MCP content blocks wrapping a JSON string
        if (Array.isArray(parsed)) {
          for (const item of parsed) {
            if (item?.type === "text" && typeof item.text === "string") {
              try {
                const inner = JSON.parse(item.text);
                if (
                  inner &&
                  typeof inner === "object" &&
                  !Array.isArray(inner)
                ) {
                  const extracted = extractBrowserFields(
                    inner as Record<string, unknown>,
                  );
                  if (extracted) return extracted;
                }
              } catch {
                // text is not JSON, use it directly
              }
            }
          }
        }
      } catch {
        // not valid JSON
      }
    }
  }

  // Fallback: use stringifyResult
  return stringifyResult(result);
}

/** All tool names this card handles */
export const BROWSER_TOOL_NAMES = new Set([
  "browser_use",
  "browser_navigate",
  "navigate",
  "browser_click",
  "click",
  "browser_type",
  "type",
  "browser_snapshot",
  "snapshot",
  "browser_scroll",
  "scroll",
]);

function getBrowserTitle(
  name: string,
  params: Record<string, unknown>,
  t: TFunction,
): string {
  if (name === "browser_use") {
    const action = (params.action || "") as string;
    const url = (params.url || "") as string;
    const selector = (params.selector || params.element || "") as string;
    const text = (params.text || "") as string;
    const width = params.width as number | undefined;
    const height = params.height as number | undefined;
    const key = (params.key || "") as string;
    const path = (params.path || "") as string;
    const code = (params.code || "") as string;
    const filename = (params.filename || "") as string;
    const tabAction = (params.tab_action || "") as string;

    const detail = (() => {
      switch (action) {
        case "start":
          return params.headed
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
          return width && height
            ? t("tool.browserAction.resize", { w: width, h: height })
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

  switch (name) {
    case "browser_navigate":
    case "navigate": {
      const url = (params.url || "") as string;
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
    default:
      return name;
  }
}

export interface BrowserUseCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const BrowserUseCard: React.FC<BrowserUseCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const title = getBrowserTitle(content.name, content.params || {}, t);
  const resultText = formatBrowserResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<ChromeOutlined />}
      title={title}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default BrowserUseCard;
