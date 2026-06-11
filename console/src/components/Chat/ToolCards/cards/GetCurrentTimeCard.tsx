import React from "react";
import { useTranslation } from "react-i18next";
import { ClockCircleOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";

export interface GetCurrentTimeCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const GetCurrentTimeCard: React.FC<GetCurrentTimeCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const title = t("tool.getCurrentTime");

  const inlineResult = (() => {
    if (content.status !== "done" || !content.result) return null;
    const raw = content.result;

    // Extract readable text from structured result like {"type":"text","text":"..."}
    // or [{"type":"text","text":"..."}]
    let text = "";
    try {
      const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (Array.isArray(parsed)) {
        text = parsed
          .filter((item: Record<string, unknown>) => item?.type === "text")
          .map((item: Record<string, unknown>) => item.text)
          .join(" ");
      } else if (parsed?.type === "text" && parsed?.text) {
        text = String(parsed.text);
      }
    } catch {
      // not JSON, use as-is
    }

    if (!text) {
      text = typeof raw === "string" ? raw : JSON.stringify(raw);
    }

    return text.length > 80 ? text.slice(0, 80) + "…" : text;
  })();

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<ClockCircleOutlined />}
      title={title}
      inlineResult={inlineResult}
    />
  );
};

export default GetCurrentTimeCard;
