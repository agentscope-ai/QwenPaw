import { Card, Button, Tooltip } from "@agentscope-ai/design";
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
import { useTheme } from "../../../../contexts/ThemeContext";
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

const getFileIcon = (filePath: string, isDark: boolean) => {
  const extension = filePath.split(".").pop()?.toLowerCase() || "";
  const palette = {
    doc: isDark ? "#87ceff" : "#1890ff",
    archive: isDark ? "#ffba6b" : "#fa8c16",
    pdf: isDark ? "#ff9c96" : "#f5222d",
    word: isDark ? "#9ec8ff" : "#2b579a",
    excel: isDark ? "#7cd6a0" : "#217346",
    ppt: isDark ? "#ffb089" : "#d24726",
    image: isDark ? "#ff8ecb" : "#eb2f96",
    code: isDark ? "#95de64" : "#52c41a",
  };

  switch (extension) {
    case "txt":
    case "md":
    case "markdown":
      return <FileTextFilled style={{ color: palette.doc }} />;
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return <FileZipFilled style={{ color: palette.archive }} />;
    case "pdf":
      return <FilePdfFilled style={{ color: palette.pdf }} />;
    case "doc":
    case "docx":
      return <FileWordFilled style={{ color: palette.word }} />;
    case "xls":
    case "xlsx":
      return <FileExcelFilled style={{ color: palette.excel }} />;
    case "ppt":
    case "pptx":
      return <FilePptFilled style={{ color: palette.ppt }} />;
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "svg":
    case "webp":
      return <FileImageFilled style={{ color: palette.image }} />;
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
      return <CodeFilled style={{ color: palette.code }} />;
    default:
      return <FileTextFilled style={{ color: palette.doc }} />;
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
  const { isDark } = useTheme();
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
      <div className={styles.cardBody}>
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={styles.fileIcon}>{getFileIcon(skill.name, isDark)}</span>
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

        <div className={styles.descriptionSection}>
          <div className={styles.infoLabel}>{t("skills.skillDescription")}</div>
          <Tooltip
            title={skill.description || "-"}
            placement="top"
            styles={{ root: { maxWidth: 360 } }}
          >
            <div className={`${styles.infoBlock} ${styles.descriptionContent}`}>
              {skill.description || "-"}
            </div>
          </Tooltip>
        </div>

        <div className={styles.metaStack}>
          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.source")}</div>
            <div>
              <span
                className={
                  isCustomized ? styles.customizedTag : styles.builtinTag
                }
              >
                {skill.source}
              </span>
            </div>
          </div>

          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.path")}</div>
            <div
              className={`${styles.infoBlock} ${styles.singleLineValue} ${styles.pathValue}`}
              title={skill.path}
            >
              {skill.path}
            </div>
          </div>
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
