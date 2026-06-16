import React from "react";
import { useTranslation } from "react-i18next";
import { TeamOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { formatAgentList } from "../shared/utils";

export interface ListAgentsCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ListAgentsCard: React.FC<ListAgentsCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const title = t("tool.listAgents");

  // Use the raw result for formatAgentList — it expects JSON to parse.
  const rawResult =
    typeof content.result === "string"
      ? content.result
      : content.result != null
      ? JSON.stringify(content.result)
      : "";
  const formattedResult = rawResult ? formatAgentList(rawResult, t) : "";

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<TeamOutlined />}
      title={title}
    >
      {formattedResult && (
        <DefaultBlock title="Output" content={formattedResult} />
      )}
    </ToolCardShell>
  );
};

export default ListAgentsCard;
