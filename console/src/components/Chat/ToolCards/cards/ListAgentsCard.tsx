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

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<TeamOutlined />}
      title={title}
      renderBody={() => {
        const rawResult =
          typeof content.result === "string"
            ? content.result
            : content.result != null
            ? JSON.stringify(content.result)
            : "";
        const formattedResult = rawResult ? formatAgentList(rawResult, t) : "";
        return formattedResult ? (
          <DefaultBlock title="Output" content={formattedResult} />
        ) : null;
      }}
    />
  );
};

export default ListAgentsCard;
