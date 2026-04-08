import React from "react";
import { Card, Button } from "@agentscope-ai/design";
import {
  CalendarFilled,
  FileTextFilled,
  FileZipFilled,
  FilePdfFilled,
  FileWordFilled,
  FileExcelFilled,
  FilePptFilled,
  FileImageFilled,
  CodeFilled,
  EyeOutlined,
  EyeInvisibleOutlined,
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
  const textSkillIcons = new Set([
    "news",
    "file_reader",
    "browser_visible",
    "guidance",
    "himalaya",
    "dingtalk_channel",
  ]);

  if (textSkillIcons.has(skillKey)) {
    return <FileTextFilled style={{ color: "#1890ff" }} />;
  }

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

export const SkillCard = React.memo(function SkillCard({
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

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggleEnabled(e);
  };

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
      {/* Header: Icon + Title + Badge + Status */}
      <div className={styles.cardHeader}>
        <div className={styles.leftSection}>
          <span className={styles.fileIcon}>
            {getSkillVisual(skill.name, skill.content)}
          </span>
          <div className={styles.titleRow}>
            <h3 className={styles.skillTitle}>{skill.name}</h3>
            <span className={styles.typeBadge}>
              {isBuiltin ? t("skills.builtin") : t("skills.custom")}
            </span>
          </div>
          {/* Meta Info: Channels, Pool Sync - moved here */}
          <div className={styles.metaContainer}>
            <div className={styles.metaItem}>
              <span className={styles.metaLabel}>{t("skills.channels")}</span>
              <span className={styles.metaValue}>
                {(skill.channels || ["all"])
                  .map((ch) => (ch === "all" ? t("skills.allChannels") : ch))
                  .join(", ")}
              </span>
            </div>
            {skill.sync_to_pool && (
              <div className={styles.metaItem}>
                <span className={styles.metaLabel}>{t("skills.poolSync")}</span>
                <span className={styles.metaValue}>
                  {getSkillSyncStatusLabel(skill.sync_to_pool.status, t)}
                </span>
              </div>
            )}
          </div>
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

      {/* Description Section */}
      <div className={styles.descriptionContainer}>
        <p className={styles.descriptionLabel}>
          {t("skills.skillDescription")}
        </p>
        <p className={styles.descriptionText}>{skill.description || "-"}</p>
      </div>

      {/* Footer with buttons - always show */}
      <div className={styles.cardFooter}>
        <Button
          className={styles.actionButton}
          onClick={handleToggleClick}
          icon={skill.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />}
        >
          {skill.enabled ? t("common.disable") : t("common.enable")}
        </Button>
        {onDelete && (
          <Button
            danger
            className={styles.deleteButton}
            onClick={handleDeleteClick}
            disabled={skill.enabled}
          >
            {t("common.delete")}
          </Button>
        )}
      </div>
    </Card>
  );
});
