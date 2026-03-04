import { Card, Button } from "@agentscope-ai/design";
import {
  DeleteOutlined,
  FileTextFilled,
  FileZipFilled,
  FilePdfFilled,
  FileWordFilled,
  FileExcelFilled,
  FilePptFilled,
  FileImageFilled,
  CodeFilled,
} from "@ant-design/icons";
import type { SkillSpec } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface SkillCardProps {
  skill: SkillSpec;
  isHover: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onToggleEnabled: (e: React.MouseEvent) => void;
  onDelete?: (e?: React.MouseEvent) => void;
}

const getFileIcon = (filePath: string) => {
  const extension = filePath.split(".").pop()?.toLowerCase() || "";

  switch (extension) {
    case "txt":
    case "md":
    case "markdown":
      return <FileTextFilled style={{ color: "#1890ff" }} />;
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return <FileZipFilled style={{ color: "#fa8c16" }} />;
    case "pdf":
      return <FilePdfFilled style={{ color: "#f5222d" }} />;
    case "doc":
    case "docx":
      return <FileWordFilled style={{ color: "#2b579a" }} />;
    case "xls":
    case "xlsx":
      return <FileExcelFilled style={{ color: "#217346" }} />;
    case "ppt":
    case "pptx":
      return <FilePptFilled style={{ color: "#d24726" }} />;
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "svg":
    case "webp":
      return <FileImageFilled style={{ color: "#eb2f96" }} />;
    case "py":
    case "js":
    case "ts":
    case "jsx":
    case "tsx":
    case "java":
    case "cpp":
    case "c":
    case "go":
    case "rs":
    case "rb":
    case "php":
      return <CodeFilled style={{ color: "#52c41a" }} />;
    default:
      return <FileTextFilled style={{ color: "#1890ff" }} />;
  }
};

export function SkillCard({
  skill,
  isHover,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onToggleEnabled,
  onDelete,
}: SkillCardProps) {
  const { t } = useTranslation();
  const isCustomized = skill.source === "customized";

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!skill.enabled && onDelete) {
      onDelete(e);
    }
  };

  return (
    <Card
      hoverable
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`${styles.skillCard} ${
        skill.enabled ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal}`}
    >
      <div
        style={{
          marginBottom: 16,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={styles.fileIcon}>{getFileIcon(skill.name)}</span>
            <h3 className={styles.skillTitle}>{skill.name}</h3>
          </div>
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusDot} ${
                skill.enabled ? styles.enabled : styles.disabled
              }`}
            />
            <span
              className={`${styles.statusText} ${
                skill.enabled ? styles.enabled : styles.disabled
              }`}
            >
              {skill.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        <div className={styles.infoSection}>
          <div className={styles.infoLabel}>{t("skills.source")}</div>
          <code className={styles.infoCode}>{skill.source}</code>
        </div>

        <div className={styles.infoSection}>
          <div className={styles.infoLabel}>{t("skills.path")}</div>
          <code className={`${styles.infoCode} ${styles.path}`}>
            {skill.path}
          </code>
        </div>
      </div>

      <div className={styles.cardFooter}>
        <Button
          type="link"
          size="small"
          onClick={onToggleEnabled}
          className={styles.actionButton}
        >
          {skill.enabled ? t("common.disable") : t("common.enable")}
        </Button>

        {isCustomized && onDelete && (
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            className={styles.deleteButton}
            onClick={handleDeleteClick}
            disabled={skill.enabled}
          />
        )}
      </div>
    </Card>
  );
}
