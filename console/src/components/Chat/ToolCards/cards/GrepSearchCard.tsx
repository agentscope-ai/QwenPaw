import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchOutlined } from "@ant-design/icons";
import { useProjectDir } from "../../../../stores/projectDirectoryStore";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";
import GrepSearchOutput from "./GrepSearchOutput";
import {
  groupGrepFileHits,
  hasOpenableGrepPaths,
  parseGrepResultLinesForOpen,
} from "./grepSearchResult";

export interface GrepSearchCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const GrepSearchCard: React.FC<GrepSearchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const { projectDir } = useProjectDir();
  const [resultListOpen, setResultListOpen] = useState(false);
  const params = content.params || {};
  const pattern = (params.pattern || "") as string;
  const searchPath = (params.path || "") as string;
  const title = pattern
    ? t("tool.grepSearch", { pattern })
    : t("tool.grepSearchDefault");

  const resultText =
    content.status === "error" ? "" : stringifyResult(content.result);
  const pathContext = useMemo(
    () => ({
      searchPath: searchPath || null,
      projectDirectory: projectDir ?? null,
    }),
    [searchPath, projectDir],
  );
  const parsedLines = useMemo(
    () =>
      resultText ? parseGrepResultLinesForOpen(resultText, pathContext) : [],
    [resultText, pathContext],
  );
  const linkable = hasOpenableGrepPaths(parsedLines);
  const fileHits = useMemo(
    () => (linkable ? groupGrepFileHits(parsedLines) : []),
    [linkable, parsedLines],
  );
  const matchCount = useMemo(
    () => fileHits.reduce((sum, hit) => sum + hit.hitCount, 0),
    [fileHits],
  );

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<SearchOutlined />}
        title={title}
      />
    );
  }

  const badge =
    content.status === "done" && (matchCount > 0 || fileHits.length > 0) ? (
      <span className={styles.lineSearchBadge}>
        {matchCount > 0
          ? t("tool.lineBadge.matches", { count: matchCount })
          : t("tool.lineBadge.files", { count: fileHits.length })}
        {matchCount > 0 && fileHits.length > 0
          ? ` · ${t("tool.lineBadge.files", { count: fileHits.length })}`
          : ""}
      </span>
    ) : null;

  const summaryAction = linkable ? (
    <button
      type="button"
      className={styles.filePreviewLink}
      aria-expanded={resultListOpen}
      aria-label={t("tool.grepResults")}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        setResultListOpen((open) => !open);
      }}
    >
      {t("tool.grepResults")}
    </button>
  ) : null;

  return (
    <>
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<SearchOutlined />}
        title={title}
        badges={badge}
        summaryAction={summaryAction}
      >
        {resultText ? (
          <DefaultBlock title="Output" content={resultText} />
        ) : null}
      </ToolCardShell>
      {resultListOpen && linkable ? (
        <div className={styles.grepPreviewPanel}>
          <GrepSearchOutput lines={parsedLines} />
        </div>
      ) : null}
    </>
  );
};

export default GrepSearchCard;
