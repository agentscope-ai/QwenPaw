import { Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { FileBaselineWriteApprovalDetails } from "../lib/fileBaselineWriteApproval";
import {
  resolveFileBaselineWriteCurrentContent,
  resolveFileBaselineWriteProposedContent,
} from "../lib/fileBaselineWriteApproval";
import styles from "./FileBaselineWriteApprovalPreview.module.less";

const { Text } = Typography;

interface FileBaselineWriteApprovalPreviewProps {
  details: FileBaselineWriteApprovalDetails;
}

function shortSha(value: string): string {
  if (!value) return "-";
  return value.length <= 12 ? value : `${value.slice(0, 12)}…`;
}

export function FileBaselineWriteApprovalPreview({
  details,
}: FileBaselineWriteApprovalPreviewProps) {
  const { t } = useTranslation();
  const currentContent = resolveFileBaselineWriteCurrentContent(details);
  const proposedContent = resolveFileBaselineWriteProposedContent(details);
  const operationLabel = t(
    `approval.fileBaselineWrite.operation.${details.operation}`,
    details.operation,
  );

  return (
    <div className={styles.fileBaselineWritePreview}>
      <div className={styles.headerRow}>
        <Text className={styles.pathLabel}>
          {t("approval.fileBaselineWrite.path", "Protected file")}:
        </Text>
        <Text className={styles.pathValue}>{details.relative_path}</Text>
        <Tag color="gold">{operationLabel}</Tag>
      </div>

      <div className={styles.metaRow}>
        <Text className={styles.shaText}>
          {t("approval.fileBaselineWrite.oldSha", "Current SHA")}:{" "}
          {shortSha(details.old_sha256)}
        </Text>
        <Text className={styles.shaText}>
          {t("approval.fileBaselineWrite.newSha", "Proposed SHA")}:{" "}
          {shortSha(details.new_sha256)}
        </Text>
      </div>

      <div className={styles.contentGrid}>
        <div className={styles.contentPanel}>
          <Text className={styles.panelTitle}>
            {t("approval.fileBaselineWrite.currentContent", "Current content")}
          </Text>
          <pre className={styles.contentBox}>
            {currentContent || (
              <span className={styles.emptyContent}>
                {t("approval.fileBaselineWrite.emptyCurrent", "(file empty or new)")}
              </span>
            )}
          </pre>
          {details.current_truncated ? (
            <Text className={styles.truncatedHint}>
              {t(
                "approval.fileBaselineWrite.truncated",
                "Content truncated for preview.",
              )}
            </Text>
          ) : null}
        </div>

        <div className={styles.contentPanel}>
          <Text className={styles.panelTitle}>
            {t("approval.fileBaselineWrite.proposedContent", "Proposed content")}
          </Text>
          <pre className={styles.contentBox}>{proposedContent}</pre>
          {details.proposed_truncated ? (
            <Text className={styles.truncatedHint}>
              {t(
                "approval.fileBaselineWrite.truncated",
                "Content truncated for preview.",
              )}
            </Text>
          ) : null}
        </div>
      </div>
    </div>
  );
}
