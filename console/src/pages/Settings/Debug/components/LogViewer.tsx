import type { ReactNode } from "react";
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
}

export function LogViewer({ lines, query, loading }: LogViewerProps) {
  const { t } = useTranslation();

  return (
    <Spin spinning={loading} tip={t("common.loading", "Loading")}>
      <div className={styles.logViewer}>
        {lines.length ? (
          lines.map((line, idx) => (
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
    </Spin>
  );
}
