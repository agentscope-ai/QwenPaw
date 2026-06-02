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
    const result =
      typeof content.result === "string" ? content.result : "";
    if (!result) return null;
    return result.length > 60 ? result.slice(0, 60) + "…" : result;
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
