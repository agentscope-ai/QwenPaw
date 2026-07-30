/** BrowserCard — presentation for the Unified Browser SDK tool. */

import React from "react";
import { ChromeOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import type { ToolCallContent } from "../shared/types";
import { DefaultBlock, ToolCardShell } from "../shared";
import { stringifyResult } from "../shared/utils";
import BrowserUseCard from "./deprecated/BrowserUseCard";

export interface BrowserCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

export function resolveBrowserCardVariant(
  payload: unknown,
): "legacy" | "unified" {
  return payload &&
    typeof payload === "object" &&
    !Array.isArray(payload) &&
    "action" in payload
    ? "legacy"
    : "unified";
}

const TEACHING_PREFIXES = ["[RETRYABLE]", "[ASK_HUMAN]"];

/** Teaching-class outcomes read as in-loop guidance, not failures. */
export function isTeachingBrowserError(resultText: string): boolean {
  const trimmed = resultText.trimStart();
  return TEACHING_PREFIXES.some((prefix) => trimmed.startsWith(prefix));
}

const BrowserCard: React.FC<BrowserCardProps> = ({ content, isStreaming }) => {
  const { t } = useTranslation();
  if (resolveBrowserCardVariant(content.params) === "legacy") {
    return <BrowserUseCard content={content} isStreaming={isStreaming} />;
  }
  const params = content.params || {};
  const code = typeof params.code === "string" ? params.code : "";
  const resultText = stringifyResult(content.result);
  const title = t("tool.execute", { tool: "browser" });

  const shellContent: ToolCallContent =
    content.status === "error" && isTeachingBrowserError(resultText)
      ? { ...content, status: "done" }
      : content;

  return (
    <ToolCardShell
      content={shellContent}
      isStreaming={isStreaming}
      icon={<ChromeOutlined />}
      title={title}
    >
      {code && <DefaultBlock title="Code" content={code} language="python" />}
      {resultText && (
        <DefaultBlock title="Output" content={resultText} language="text" />
      )}
    </ToolCardShell>
  );
};

export default BrowserCard;
