import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import React from "react";
import { Card, Button, Checkbox, Tooltip, Switch } from "@agentscope-ai/design";
import { Trash2 } from "lucide-react";
import InlineHelp from "@/components/InlineHelp";
import { motion, useReducedMotion } from "motion/react";
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
  const { t, i18n } = useTranslation();
  const batchMode = selected !== undefined;
  const reducedMotion = useReducedMotion();

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
    <motion.div
      layout
      layoutId={`skill-${skill.name}`}
      transition={{
        layout: reducedMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 340, damping: 36 },
      }}
    >
      <InteractiveCard tilt={0} className={styles.skillSurface}>
        <Card
          onClick={handleCardClick}
          onMouseEnter={() => {
            onMouseEnter?.();
          }}
          onMouseLeave={() => {
            onMouseLeave?.();
          }}
          className={`${styles.skillCard} ${
            selected ? styles.selectedCard : ""
          }`}
          style={{ cursor: "pointer" }}
        >
          {batchMode && (
            <Checkbox
              aria-label={skill.name}
              checked={selected}
              onClick={handleSelectClick}
            />
          )}
          {/* Title + Built-in/Custom tag */}
          <div className={styles.titleRow}>
            <h3 className={styles.skillTitle}>
              <button
                type="button"
                className={styles.skillNameButton}
                onClick={(event) => {
                  event.stopPropagation();
                  handleCardClick(event);
                }}
              >
                {skill.name}
              </button>
            </h3>
            <InlineHelp>
              {skill.description || t("skills.noDescription")}
            </InlineHelp>
          </div>

          <div className={styles.skillSummaryMeta}>
            <span className={styles.typeBadge}>
              {t(isBuiltin ? "skills.builtin" : "skills.custom")}
            </span>
            {skill.preload && (
              <span className={styles.preloadTag}>{t("skills.preload")}</span>
            )}

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
          <div className={styles.skillActions}>
            <span className={styles.skillUpdated}>
              {skill.last_updated
                ? new Date(skill.last_updated).toLocaleDateString(i18n.language)
                : ""}
            </span>
            <Switch
              aria-label={`${t(
                skill.enabled ? "common.disable" : "common.enable",
              )}: ${skill.name}`}
              checked={skill.enabled}
              disabled={batchMode}
              onClick={(_, event) =>
                handleToggleClick(event as React.MouseEvent)
              }
            />
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
    </motion.div>
  );
});
