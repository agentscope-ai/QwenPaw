import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Spin, Typography } from "antd";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

const { Text } = Typography;

// ── Helpers ───────────────────────────────────────────────────────────────

function escapeRegExp(input: string): string {
  return input.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightLine(line: string, needle: string): ReactNode {
  const q = needle.trim();
  if (!q) return line;
  const re = new RegExp(escapeRegExp(q), "ig");
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(line))) {
    const start = match.index;
    const end = start + match[0].length;
    if (start > lastIndex) {
      parts.push(line.slice(lastIndex, start));
    }
    parts.push(
      <mark key={`${start}-${end}`} className={styles.highlight}>
        {line.slice(start, end)}
      </mark>,
    );
    lastIndex = end;
  }
  if (lastIndex < line.length) parts.push(line.slice(lastIndex));
  return parts;
}

// ── Component ─────────────────────────────────────────────────────────────

interface LogViewerProps {
  lines: string[];
  query: string;
  loading: boolean;
  newestFirst: boolean;
  onDisplayedLines: (lines: string[]) => void;
}

export function LogViewer({
  lines,
  query,
  loading,
  newestFirst,
  onDisplayedLines,
}: LogViewerProps) {
  const { t } = useTranslation();
  const viewport = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const [displayed, setDisplayed] = useState(lines);
  const hasUpdates =
    lines.length !== displayed.length ||
    lines.some((line, index) => line !== displayed[index]);
  useLayoutEffect(() => {
    if (following) setDisplayed(lines);
  }, [lines, following]);
  useLayoutEffect(() => {
    const node = viewport.current;
    if (following && node) node.scrollTop = newestFirst ? 0 : node.scrollHeight;
  }, [displayed, following, newestFirst]);

  useLayoutEffect(
    () => onDisplayedLines(displayed),
    [displayed, onDisplayedLines],
  );

  return (
    <Spin spinning={loading} tip={t("common.loading", "Loading")}>
      <div className={styles.logFrame}>
        {!following && (
          <div className={styles.followNotice} role="status">
            <button type="button" onClick={() => setFollowing(true)}>
              {t(
                hasUpdates
                  ? "debug.backend.newLogsAvailable"
                  : "debug.backend.returnLatest",
              )}
            </button>
          </div>
        )}
        <div
          ref={viewport}
          className={styles.logViewer}
          role="region"
          aria-label={t("debug.backend.title")}
          tabIndex={0}
          onScroll={(event) => {
            const node = event.currentTarget;
            const atLatest = newestFirst
              ? node.scrollTop <= 4
              : node.scrollHeight - node.scrollTop - node.clientHeight <= 4;
            setFollowing(atLatest);
          }}
        >
          {displayed.length ? (
            displayed.map((line, idx) => (
              <div key={idx}>{highlightLine(line, query)}</div>
            ))
          ) : (
            <Text type="secondary">
              {t(
                "debug.backend.placeholder",
                "Backend log output will appear here.",
              )}
            </Text>
          )}
        </div>
      </div>
    </Spin>
  );
}
