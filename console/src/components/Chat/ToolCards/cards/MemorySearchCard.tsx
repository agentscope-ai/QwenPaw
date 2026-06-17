import React from "react";
import { useTranslation } from "react-i18next";
import { BulbOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { formatMemorySearch } from "../shared/utils";

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

  // Use the raw result string for formatMemorySearch — it expects JSON to parse.
  // Fall back to stringifyResult if result is not a string.
  const rawResult =
    typeof content.result === "string"
      ? content.result
      : content.result != null
      ? JSON.stringify(content.result)
      : "";
  const formattedResult = rawResult ? formatMemorySearch(rawResult, t) : "";

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<BulbOutlined />}
      title={title}
    >
      {formattedResult && (
        <DefaultBlock title="Output" content={formattedResult} />
      )}
    </ToolCardShell>
  );
};

export default MemorySearchCard;
