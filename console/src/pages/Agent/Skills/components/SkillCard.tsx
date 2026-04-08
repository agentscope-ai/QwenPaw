import React from "react";
import { Card, Button, Checkbox, Tooltip } from "@agentscope-ai/design";
import { SkillTags } from "../../../Settings/SkillPool/components/SkillMeta";
import {
  CalendarFilled,
  ApiOutlined,
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
import dayjs from "dayjs";
import type { SkillSpec } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface SkillCardProps {
  skill: SkillSpec;
  isHover: boolean;
  selected?: boolean;
  onSelect?: (e: React.MouseEvent) => void;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onToggleEnabled: (e: React.MouseEvent) => void;
  onDelete?: (e?: React.MouseEvent) => void;
}

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
      return <FileWordFilled style={{ color: "#2B8DFF" }} />;
    case "xlsx":
      return <FileExcelFilled style={{ color: "#44C161" }} />;
    case "pptx":
      return <FilePptFilled style={{ color: "#FF5B3B" }} />;
    case "pdf":
      return <FilePdfFilled style={{ color: "#F04B57" }} />;
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
      return <FilePdfFilled style={{ color: "#F04B57" }} />;
    case "doc":
    case "docx":
      return <FileWordFilled style={{ color: "#2B8DFF" }} />;
    case "xls":
    case "xlsx":
      return <FileExcelFilled style={{ color: "#44C161" }} />;
    case "ppt":
    case "pptx":
      return <FilePptFilled style={{ color: "#FF5B3B" }} />;
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

export const getSkillVisual = (name: string, emoji?: string) => {
  if (emoji) {
    return <span className={styles.skillEmoji}>{emoji}</span>;
  }
  return getFileIcon(name);
};

export const SkillCard = React.memo(function SkillCard({
  skill,
  isHover,
  selected,
  onSelect,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onToggleEnabled,
  onDelete,
}: SkillCardProps) {
  const { t } = useTranslation();
  const batchMode = selected !== undefined;

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggleEnabled(e);
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onDelete?.(e);
  };

  const handleSelectClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelect?.(e);
  };

  const handleCardClick = (e: React.MouseEvent) => {
    if (batchMode && onSelect) {
      onSelect(e);
    } else {
      onClick();
    }
  };

  return (
    <Card
      hoverable
      onClick={handleCardClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`${styles.skillCard} ${
        skill.enabled ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal} ${
        selected ? styles.selectedCard : ""
      }`}
    >
      {/* Header: Icon + Title + Status */}
      <div className={styles.cardHeader}>
        <div className={styles.leftSection}>
          <span className={styles.fileIcon}>
            {getSkillVisual(skill.name, skill.emoji)}
          </span>
          <div className={styles.titleInfoContainer}>
            <div className={styles.titleRow}>
              <h3 className={styles.skillTitle}>{skill.name}</h3>
              <span
                className={`${styles.statusValue} ${
                  skill.enabled ? styles.enabled : styles.disabled
                }`}
              >
                {skill.enabled ? t("common.enabled") : t("common.disabled")}
              </span>
            </div>
            {skill.last_updated && (
              <div className={styles.updatedTime}>
                <CalendarFilled className={styles.calendarIcon} />
                <span>{dayjs(skill.last_updated).fromNow()}</span>
              </div>
            )}
          </div>
        </div>
        {batchMode && (
          <Checkbox checked={selected} onClick={handleSelectClick} />
        )}
      </div>

      {/* Channels Section */}
      <div className={styles.channelsRow}>
        <Tooltip title={t("skills.channels")}>
          <ApiOutlined className={styles.channelIcon} />
        </Tooltip>
        <span className={styles.channelValue}>
          {(skill.channels || ["all"])
            .map((ch) => (ch === "all" ? t("skills.allChannels") : ch))
            .join(", ")}
        </span>
      </div>

      {/* Description Section */}
      <div className={styles.descriptionContainer}>
        <SkillTags tags={skill.tags} styles={styles} />
        <p className={styles.descriptionText}>{skill.description || "-"}</p>
      </div>

      {/* Footer with buttons - always show, disabled in batch mode */}
      <div className={styles.cardFooter}>
        <Button
          className={styles.actionButton}
          onClick={handleToggleClick}
          icon={skill.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />}
          disabled={batchMode}
        >
          {skill.enabled ? t("common.disable") : t("common.enable")}
        </Button>
        {onDelete && (
          <Button
            danger
            className={styles.deleteButton}
            onClick={handleDeleteClick}
            disabled={batchMode}
          >
            {t("common.delete")}
          </Button>
        )}
      </div>
    </Card>
  );
});
