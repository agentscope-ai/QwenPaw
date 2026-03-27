import { Card, Button, Tooltip } from "@agentscope-ai/design";
import {
  CalendarFilled,
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
import {
  getSkillDisplaySource,
  getSkillSyncStatusLabel,
} from "./skillMetadata";

interface SkillCardProps {
  skill: SkillSpec;
  isHover: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onToggleEnabled: (e: React.MouseEvent) => void;
  onDelete?: (e?: React.MouseEvent) => void;
}

const extractSkillEmoji = (content?: string) => {
  if (!content) return "";
  const match = content.match(/"emoji"\s*:\s*"([^"]+)"/);
  return match?.[1] || "";
};

const normalizeSkillIconKey = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .split(/\s+/)[0]
    ?.replace(/[^a-z0-9_-]/g, "") || "";

export const getFileIcon = (filePath: string) => {
  const skillKey = normalizeSkillIconKey(filePath);

  switch (skillKey) {
    case "docx":
      return <FileWordFilled style={{ color: "#2b579a" }} />;
    case "xlsx":
      return <FileExcelFilled style={{ color: "#217346" }} />;
    case "pptx":
      return <FilePptFilled style={{ color: "#d24726" }} />;
    case "pdf":
      return <FilePdfFilled style={{ color: "#f5222d" }} />;
    case "cron":
      return <CalendarFilled style={{ color: "#13c2c2" }} />;
    case "news":
    case "file_reader":
    case "browser_visible":
    case "guidance":
    case "himalaya":
    case "dingtalk_channel":
      return <FileTextFilled style={{ color: "#1890ff" }} />;
    default:
      break;
  }

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

export const getSkillVisual = (name: string, content?: string) => {
  const emoji = extractSkillEmoji(content);
  if (emoji) {
    return <span className={styles.skillEmoji}>{emoji}</span>;
  }
  return getFileIcon(name);
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
  const displaySource = getSkillDisplaySource(skill.source);
  const isBuiltin = displaySource === "builtin";
  const syncStatusLabel = getSkillSyncStatusLabel(
    skill.sync_to_pool?.status,
    t,
  );

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
            <span className={styles.fileIcon}>
              {getSkillVisual(skill.name, skill.content)}
            </span>
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
            overlayStyle={{ maxWidth: 360 }}
          >
            <div className={`${styles.infoBlock} ${styles.descriptionContent}`}>
              {skill.description || "-"}
            </div>
          </Tooltip>
        </div>

        <div className={styles.metaStack}>
          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.type")}</div>
            <div>
              <span
                className={isBuiltin ? styles.builtinTag : styles.customizedTag}
              >
                {displaySource}
              </span>
            </div>
          </div>

          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.channels")}</div>
            <div className={styles.infoBlock}>
              {(skill.channels || ["all"]).join(", ")}
            </div>
          </div>

          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.poolSync")}</div>
            <div className={styles.infoBlock}>{syncStatusLabel}</div>
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

        {onDelete && (
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
