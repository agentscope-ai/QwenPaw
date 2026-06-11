import React, { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Calendar,
  FileText,
  FileArchive,
  Code,
  Eye,
  EyeOff,
} from "lucide-react";
import dayjs from "dayjs";
import type { SkillSpec } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface SkillCardProps {
  skill: SkillSpec;
  selected?: boolean;
  onSelect?: (e: React.MouseEvent) => void;
  onClick: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
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
    return <FileText className="text-blue-500" />;
  }

  switch (skillKey) {
    case "cron":
      return <Calendar className="text-teal-500" />;
    default:
      break;
  }

  const extension = filePath.split(".").pop()?.toLowerCase() || "";

  switch (extension) {
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return <FileArchive className="text-orange-400" />;
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
      return <Code className="text-green-500" />;
    default:
      return <FileText className="text-blue-500" />;
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
  const [isHover, setIsHover] = useState(false);

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

  const isBuiltin =
    skill.source === "builtin" ||
    skill.source?.startsWith("builtin:") ||
    skill.source === "system";

  return (
    <Card
      onClick={handleCardClick}
      onMouseEnter={() => {
        setIsHover(true);
        onMouseEnter?.();
      }}
      onMouseLeave={() => {
        setIsHover(false);
        onMouseLeave?.();
      }}
      className={`${styles.skillCard} ${
        selected ? styles.selectedCard : ""
      } cursor-pointer`}
    >
      <CardContent className="p-0">
        <div className={styles.cardTopRow}>
          <span className={styles.fileIcon}>
            {getSkillVisual(skill.name, skill.emoji)}
          </span>
          <div className={styles.cardTopRight}>
            <span
              className={`${styles.statusBadge} ${
                skill.enabled ? styles.status_enabled : styles.status_disabled
              }`}
            >
              <span className={styles.statusDot} />
              {skill.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
            {batchMode && (
              <input
                type="checkbox"
                checked={selected}
                onClick={handleSelectClick}
                onChange={() => {}}
                className="h-4 w-4 cursor-pointer"
              />
            )}
          </div>
        </div>

        <div className={styles.titleRow}>
          <h3 className={styles.skillTitle} title={skill.name}>
            {skill.name}{" "}
            {isBuiltin ? (
              <span className={styles.builtinTag}>{t("skills.builtin")}</span>
            ) : (
              <span className={styles.customTag}>{t("skills.custom")}</span>
            )}
          </h3>
        </div>

        <div className={styles.metaInfoRow}>
          <span className={styles.metaInfoLabel}>{t("skills.channels")}</span>
          <span className={styles.metaInfoValue}>
            {(skill.channels || ["all"])
              .map((ch) => (ch === "all" ? t("skills.allChannels") : ch))
              .join(", ")}
          </span>
        </div>

        {skill.last_updated && (
          <div className={styles.metaInfoRow}>
            <span className={styles.metaInfoLabel}>
              {t("skills.lastUpdated")}
            </span>
            <span className={styles.metaInfoValue}>
              {dayjs(skill.last_updated).fromNow()}
            </span>
          </div>
        )}

        <div className={styles.metaInfoRow}>
          <span className={styles.metaInfoLabel}>{t("skills.tags")}</span>
          {!!skill.tags?.length ? (
            <div className={styles.tagChips}>
              {skill.tags.map((tag) => (
                <span key={tag} className={styles.tagChip}>
                  {tag}
                </span>
              ))}
            </div>
          ) : (
            <span style={{ color: "rgba(20,20,19,0.35)" }}>-</span>
          )}
        </div>

        <div className={styles.descriptionSection}>
          <span className={styles.descriptionSectionLabel}>
            {t("skills.skillDescription")}
          </span>
          <p className={styles.descriptionText}>{skill.description || "-"}</p>
        </div>

        {(isHover || batchMode) && (
          <div className={styles.cardFooter}>
            <Button
              variant="outline"
              size="sm"
              className={styles.actionButton}
              disabled={batchMode}
              onClick={handleToggleClick}
            >
              {skill.enabled ? (
                <EyeOff size={14} className="mr-1" />
              ) : (
                <Eye size={14} className="mr-1" />
              )}
              {skill.enabled ? t("common.disable") : t("common.enable")}
            </Button>
            {onDelete && (
              <Button
                variant="destructive"
                size="sm"
                className={styles.deleteButton}
                disabled={batchMode}
                onClick={handleDeleteClick}
              >
                {t("common.delete")}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
});
