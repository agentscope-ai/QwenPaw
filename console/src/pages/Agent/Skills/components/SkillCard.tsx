import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import React from "react";
import { Card, Button, Checkbox, Tooltip } from "@agentscope-ai/design";
import {
  Trash2,
  Eye as EyeOutlined,
  EyeOff as EyeInvisibleOutlined,
} from "lucide-react";
import { getFileIcon } from "@/components/SkillVisual";
import dayjs from "dayjs";
import type { SkillSpec } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { normalizeSkillChannels } from "../../../../utils/skill";
import styles from "../index.module.less";

interface SkillCardProps {
  skill: SkillSpec;
  getChannelName?: (key: string) => string;
  selected?: boolean;
  onSelect?: (e: React.MouseEvent) => void;
  onClick: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  onToggleEnabled: (e: React.MouseEvent) => void;
  onDelete?: (e?: React.MouseEvent) => void;
}

export const getSkillVisual = (name: string) => getFileIcon(name);

export const SkillCard = React.memo(function SkillCard({
  skill,
  getChannelName,
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

  const isBuiltin =
    skill.source === "builtin" ||
    skill.source?.startsWith("builtin:") ||
    skill.source === "system";

  return (
    <InteractiveCard tilt={3} style={{ width: "100%" }}>
      <Card
        hoverable
        onClick={handleCardClick}
        role="button"
        tabIndex={0}
        aria-label={skill.name}
        onKeyDown={(event) => {
          if (
            event.target === event.currentTarget &&
            ["Enter", " "].includes(event.key)
          ) {
            event.preventDefault();
            event.currentTarget.click();
          }
        }}
        onMouseEnter={() => {
          onMouseEnter?.();
        }}
        onMouseLeave={() => {
          onMouseLeave?.();
        }}
        className={`${styles.skillCard} ${selected ? styles.selectedCard : ""}`}
        style={{ cursor: "pointer" }}
      >
        {/* Top row: Icon (left) + Status badge + Checkbox (right) */}
        <div className={styles.cardTopRow}>
          <span className={styles.fileIcon}>{getSkillVisual(skill.name)}</span>
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
              <Checkbox checked={selected} onClick={handleSelectClick} />
            )}
          </div>
        </div>

        {/* Title + Built-in/Custom tag */}
        <div className={styles.titleRow}>
          <Tooltip title={skill.name}>
            <h3 className={styles.skillTitle}>
              {skill.name}{" "}
              {isBuiltin ? (
                <span className={styles.builtinTag}>{t("skills.builtin")}</span>
              ) : (
                <span className={styles.customTag}>{t("skills.custom")}</span>
              )}
              {skill.preload && (
                <span className={styles.preloadTag}>{t("skills.preload")}</span>
              )}
            </h3>
          </Tooltip>
        </div>

        <div className={styles.skillSummaryMeta}>
          {skill.version_text && <span>v{skill.version_text}</span>}
          <span title={t("skills.channels")}>
            {normalizeSkillChannels(skill.channels)
              .map((ch) =>
                getChannelName
                  ? getChannelName(ch)
                  : ch === "all"
                  ? t("skills.allChannels")
                  : ch,
              )
              .join(", ")}
          </span>
        </div>
        {skill.tags?.length ? (
          <div className={styles.tagChips}>
            {skill.tags.slice(0, 3).map((tag) => (
              <span className={styles.tagChip} key={tag}>
                {tag}
              </span>
            ))}
          </div>
        ) : null}
        {/* Description */}
        <div className={styles.descriptionSection}>
          <p className={styles.descriptionText}>{skill.description || "-"}</p>
        </div>

        <div className={styles.skillActions}>
          <span className={styles.skillUpdated}>
            {skill.last_updated ? dayjs(skill.last_updated).fromNow() : ""}
          </span>
          <Tooltip
            title={skill.enabled ? t("common.disable") : t("common.enable")}
          >
            <Button
              type="text"
              aria-label={
                skill.enabled ? t("common.disable") : t("common.enable")
              }
              disabled={batchMode}
              onClick={handleToggleClick}
              icon={
                skill.enabled ? (
                  <EyeInvisibleOutlined size={16} />
                ) : (
                  <EyeOutlined size={16} />
                )
              }
            />
          </Tooltip>
          {onDelete && (
            <Tooltip title={t("common.delete")}>
              <Button
                type="text"
                danger
                aria-label={t("common.delete")}
                disabled={batchMode}
                onClick={handleDeleteClick}
                icon={<Trash2 size={16} />}
              />
            </Tooltip>
          )}
        </div>
      </Card>
    </InteractiveCard>
  );
});
