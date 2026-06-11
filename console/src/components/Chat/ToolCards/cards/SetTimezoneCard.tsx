import React from "react";
import { useTranslation } from "react-i18next";
import { GlobalOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";

export interface SetTimezoneCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const SetTimezoneCard: React.FC<SetTimezoneCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const title = t("tool.setTimezone", {
    timezone: (params.timezone_name || "") as string,
  });

  const inlineResult = (() => {
    if (content.status !== "done" || !content.result) return null;
    const result = typeof content.result === "string" ? content.result : "";
    if (!result) return null;
    return result.length > 60 ? result.slice(0, 60) + "…" : result;
  })();

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<GlobalOutlined />}
      title={title}
      inlineResult={inlineResult}
    />
  );
};

export default SetTimezoneCard;
