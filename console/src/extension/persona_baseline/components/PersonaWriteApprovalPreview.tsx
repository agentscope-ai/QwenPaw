import { Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { PersonaWriteApprovalDetails } from "../lib/personaWriteApproval";
import {
  resolvePersonaWriteCurrentContent,
  resolvePersonaWriteProposedContent,
} from "../lib/personaWriteApproval";
import styles from "./PersonaWriteApprovalPreview.module.less";

const { Text } = Typography;

interface PersonaWriteApprovalPreviewProps {
  details: PersonaWriteApprovalDetails;
}

function shortSha(value: string): string {
  if (!value) return "-";
  return value.length <= 12 ? value : `${value.slice(0, 12)}…`;
}

export function PersonaWriteApprovalPreview({
  details,
}: PersonaWriteApprovalPreviewProps) {
  const { t } = useTranslation();
  const currentContent = resolvePersonaWriteCurrentContent(details);
  const proposedContent = resolvePersonaWriteProposedContent(details);
  const operationLabel = t(
    `approval.personaWrite.operation.${details.operation}`,
    details.operation,
  );

  return (
    <div className={styles.personaWritePreview}>
      <div className={styles.headerRow}>
        <Text className={styles.pathLabel}>
          {t("approval.personaWrite.path", "Protected file")}:
        </Text>
        <Text className={styles.pathValue}>{details.relative_path}</Text>
        <Tag color="gold">{operationLabel}</Tag>
      </div>

      <div className={styles.metaRow}>
        <Text className={styles.shaText}>
          {t("approval.personaWrite.oldSha", "Current SHA")}:{" "}
          {shortSha(details.old_sha256)}
        </Text>
        <Text className={styles.shaText}>
          {t("approval.personaWrite.newSha", "Proposed SHA")}:{" "}
          {shortSha(details.new_sha256)}
        </Text>
      </div>

      <div className={styles.contentGrid}>
        <div className={styles.contentPanel}>
          <Text className={styles.panelTitle}>
            {t("approval.personaWrite.currentContent", "Current content")}
          </Text>
          <pre className={styles.contentBox}>
            {currentContent || (
              <span className={styles.emptyContent}>
                {t("approval.personaWrite.emptyCurrent", "(file empty or new)")}
              </span>
            )}
          </pre>
          {details.current_truncated ? (
            <Text className={styles.truncatedHint}>
              {t(
                "approval.personaWrite.truncated",
                "Content truncated for preview.",
              )}
            </Text>
          ) : null}
        </div>

        <div className={styles.contentPanel}>
          <Text className={styles.panelTitle}>
            {t("approval.personaWrite.proposedContent", "Proposed content")}
          </Text>
          <pre className={styles.contentBox}>{proposedContent}</pre>
          {details.proposed_truncated ? (
            <Text className={styles.truncatedHint}>
              {t(
                "approval.personaWrite.truncated",
                "Content truncated for preview.",
              )}
            </Text>
          ) : null}
        </div>
      </div>
    </div>
  );
}
