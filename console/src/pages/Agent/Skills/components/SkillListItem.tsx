import { Button, Checkbox, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { SkillSpec } from "../../../../api/types";
import { isSkillBuiltin, normalizeSkillChannels } from "@/utils/skill";
import InlineHelp from "@/components/InlineHelp";
import { motion, useReducedMotion } from "motion/react";
import styles from "../index.module.less";

interface SkillListItemProps {
  skill: SkillSpec;
  getChannelName?: (key: string) => string;
  batchModeEnabled: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onClick: () => void;
  onToggleEnabled: () => Promise<void>;
  onDelete: () => void;
}

export function SkillListItem({
  skill,
  getChannelName,
  batchModeEnabled,
  isSelected,
  onSelect,
  onClick,
  onToggleEnabled,
  onDelete,
}: SkillListItemProps) {
  const { t, i18n } = useTranslation();
  const reducedMotion = useReducedMotion();
  const isBuiltin = isSkillBuiltin(skill.source);
  const channels = normalizeSkillChannels(skill.channels)
    .map((ch) =>
      getChannelName
        ? getChannelName(ch)
        : ch === "all"
        ? t("skills.allChannels")
        : ch,
    )
    .join(", ");

  return (
    <motion.div
      layout
      layoutId={`skill-${skill.name}`}
      transition={{
        layout: reducedMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 340, damping: 36 },
      }}
      className={`${styles.skillListItem} ${
        isSelected ? styles.selectedListItem : ""
      }`}
      onClick={() => {
        if (batchModeEnabled) onSelect();
        else onClick();
      }}
    >
      {batchModeEnabled && (
        <Checkbox
          aria-label={skill.name}
          checked={isSelected}
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
        />
      )}
      <div className={styles.listItemLeft}>
        <div className={styles.listItemInfo}>
          <div className={styles.listItemHeader}>
            <button
              type="button"
              className={styles.skillNameButton}
              onClick={(event) => {
                event.stopPropagation();
                if (batchModeEnabled) onSelect();
                else onClick();
              }}
            >
              {skill.name}
            </button>
            <InlineHelp>
              {skill.description || t("skills.noDescription")}
            </InlineHelp>
            <span className={styles.typeBadge}>
              {isBuiltin ? t("skills.builtin") : t("skills.custom")}
            </span>
            {skill.version_text && (
              <span className={styles.typeBadge}>
                {t("skillPool.version")}: {skill.version_text}
              </span>
            )}
            {skill.preload && (
              <span className={styles.preloadListTag}>
                {t("skills.preload")}
              </span>
            )}
            <span className={styles.channelBadge}>{channels}</span>
            {skill.last_updated && (
              <span className={styles.listItemTime}>
                {t("skills.lastUpdated")}{" "}
                {new Date(skill.last_updated).toLocaleDateString(i18n.language)}
              </span>
            )}
          </div>
          {!!skill.tags?.length && (
            <div className={styles.listItemTags}>
              {skill.tags.map((tag) => (
                <span key={tag} className={styles.tagChip}>
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className={styles.listItemRight}>
        <span onClick={(e) => e.stopPropagation()}>
          <Switch
            aria-label={`${t(
              skill.enabled ? "common.disable" : "common.enable",
            )}: ${skill.name}`}
            checked={skill.enabled}
            disabled={batchModeEnabled}
            onChange={onToggleEnabled}
          />
        </span>
        <Button
          danger
          disabled={batchModeEnabled}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          {t("common.delete")}
        </Button>
      </div>
    </motion.div>
  );
}
