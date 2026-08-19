import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DownOutlined,
  FileTextOutlined,
  RightOutlined,
} from "@ant-design/icons";
import styles from "../shared/toolCards.module.less";
import {
  dispatchOpenFilePreview,
  displayPartsForGrepPath,
  groupGrepFileHits,
  toOpenableFileTarget,
  type GrepFileHit,
  type GrepMatchHit,
  type GrepResultLine,
} from "./grepSearchResult";

export interface GrepSearchOutputProps {
  lines: GrepResultLine[];
}

function openPath(
  path: string,
  line: number | undefined,
  trigger: HTMLElement,
): void {
  const target = toOpenableFileTarget(path, line);
  if (!target) return;
  dispatchOpenFilePreview(target, trigger, { workspace: true });
}

const GrepMatchRow: React.FC<{
  path: string;
  match: GrepMatchHit;
}> = ({ path, match }) => (
  <button
    type="button"
    className={styles.grepMatchRow}
    title={`${path}:${match.line}`}
    aria-label={`${path}:${match.line}`}
    onClick={(event) => {
      event.preventDefault();
      event.stopPropagation();
      openPath(path, match.line, event.currentTarget);
    }}
  >
    <span className={styles.grepMatchLine}>L{match.line}</span>
    <span className={styles.grepMatchContent}>{match.content}</span>
  </button>
);

const GrepFileGroup: React.FC<{ hit: GrepFileHit }> = ({ hit }) => {
  const { t } = useTranslation();
  const { name, directory } = displayPartsForGrepPath(hit.path);
  const canExpand = hit.matches.length > 0;
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={styles.grepFileGroup}>
      <div className={styles.grepFileRowWrap}>
        {canExpand ? (
          <button
            type="button"
            className={styles.grepFileChevron}
            aria-expanded={expanded}
            aria-label={
              expanded
                ? t("tool.grepCollapseFile", { path: hit.path })
                : t("tool.grepExpandFile", { path: hit.path })
            }
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setExpanded((value) => !value);
            }}
          >
            {expanded ? (
              <DownOutlined aria-hidden />
            ) : (
              <RightOutlined aria-hidden />
            )}
          </button>
        ) : (
          <span className={styles.grepFileChevronSpacer} aria-hidden />
        )}
        <button
          type="button"
          className={styles.grepFileRow}
          title={hit.line ? `${hit.path}:${hit.line}` : hit.path}
          aria-label={hit.path}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            openPath(hit.path, hit.line, event.currentTarget);
          }}
        >
          <FileTextOutlined className={styles.grepFileIcon} aria-hidden />
          <span className={styles.grepFileName}>{name}</span>
          {directory ? (
            <span className={styles.grepFileDir}>{directory}</span>
          ) : null}
          {hit.hitCount > 1 ? (
            <span className={styles.grepFileHitCount}>{hit.hitCount}</span>
          ) : null}
        </button>
      </div>
      {canExpand && expanded ? (
        <div className={styles.grepMatchList}>
          {hit.matches.map((match) => (
            <GrepMatchRow
              key={`${hit.path}:${match.line}:${match.content}`}
              path={hit.path}
              match={match}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
};

const GrepSearchOutput: React.FC<GrepSearchOutputProps> = ({ lines }) => {
  const { t } = useTranslation();
  const fileHits = useMemo(() => groupGrepFileHits(lines), [lines]);

  return (
    <div className={styles.grepFileListBlock}>
      <div className={styles.grepFileListHeader}>
        <span className={styles.grepFileListTitle}>
          {t("tool.lineBadge.files", { count: fileHits.length })}
        </span>
      </div>
      <div className={styles.grepFileListBody}>
        {fileHits.map((hit) => (
          <GrepFileGroup key={hit.path} hit={hit} />
        ))}
      </div>
    </div>
  );
};

export default React.memo(GrepSearchOutput);
