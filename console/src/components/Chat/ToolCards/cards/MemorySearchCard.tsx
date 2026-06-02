import React from "react";
import { useTranslation } from "react-i18next";
import { BulbOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { formatMemorySearch, stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface MemorySearchCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const MemorySearchCard: React.FC<MemorySearchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const query = (params.query || params.text || "") as string;
  const queryShort = query.length > 20 ? query.slice(0, 20) + "…" : query;
  const title = queryShort
    ? t("tool.memorySearch", { query: queryShort })
    : t("tool.memorySearchDefault");

  const rawResult = stringifyResult(content.result);
  const formattedResult = rawResult
    ? formatMemorySearch(rawResult, t)
    : "";

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<BulbOutlined />}
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

export default MemorySearchCard;
