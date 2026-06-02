import React from "react";
import { useTranslation } from "react-i18next";
import { TeamOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { formatAgentList, stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

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

  const rawResult = stringifyResult(content.result);
  const formattedResult = rawResult ? formatAgentList(rawResult, t) : "";

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<TeamOutlined />}
      title={title}
    >
      {formattedResult && (
        <div className={styles.toolCallResultMd}>
          <Markdown content={formattedResult} />
        </div>
      )}
    </ToolCardShell>
  );
};

export default ListAgentsCard;
