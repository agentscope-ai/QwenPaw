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

function compactNumber(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : "";
}

const MemorySearchCard: React.FC<MemorySearchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const query = (params.query || params.text || "") as string;
  const queryShort = query.length > 20 ? query.slice(0, 20) + "…" : query;
  const limit = compactNumber(params.limit ?? params.max_results);
  const minScore = compactNumber(params.min_score);
  const meta = [limit && `limit=${limit}`, minScore && `min_score=${minScore}`]
    .filter(Boolean)
    .join(" ");
  const baseTitle = queryShort
    ? t("tool.memorySearch", { query: queryShort })
    : t("tool.memorySearchDefault");
  const title = meta ? `${baseTitle} · ${meta}` : baseTitle;

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<BulbOutlined />}
        title={title}
      />
    );
  }

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
