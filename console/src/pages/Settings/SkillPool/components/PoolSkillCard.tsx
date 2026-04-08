import { useState } from "react";
import { Button, Card, Checkbox, Tooltip } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import { getSkillVisual } from "../../../Agent/Skills/components";
import styles from "../index.module.less";

interface PoolSkillCardProps {
  skill: PoolSkillSpec;
  isSelected: boolean;
  batchModeEnabled: boolean;
  onToggleSelect: (name: string) => void;
  onEdit: (skill: PoolSkillSpec) => void;
  onBroadcast: (skill: PoolSkillSpec) => void;
  onDelete: (skill: PoolSkillSpec) => void;
}

export function PoolSkillCard({
  skill,
  isSelected,
  batchModeEnabled,
  onToggleSelect,
  onEdit,
  onBroadcast,
  onDelete,
}: PoolSkillCardProps) {
  const { t } = useTranslation();
  const [isHover, setIsHover] = useState(false);
  const syncTone = getPoolBuiltinStatusTone(skill.sync_status);
  const isBuiltin = isSkillBuiltin(skill.source);

  return (
    <Card
      key={skill.name}
      hoverable
      className={`${styles.skillCard} ${isSelected ? styles.selectedCard : ""}`}
      onMouseEnter={() => setIsHover(true)}
      onMouseLeave={() => setIsHover(false)}
      onClick={() => {
        if (batchModeEnabled) {
          onToggleSelect(skill.name);
        } else {
          onEdit(skill);
        }
      }}
      style={{ cursor: "pointer" }}
    >
      {/* Top row: Icon (left) + Status badge + Checkbox (right) */}
      <div className={styles.cardTopRow}>
        <span className={styles.fileIcon}>
          {getSkillVisual(skill.name, skill.emoji)}
        </span>
        <div className={styles.cardTopRight}>
          <span
            className={`${styles.statusBadge} ${styles[`status_${syncTone}`]}`}
          >
            <span className={styles.statusDot} />
            {getPoolBuiltinStatusLabel(skill.sync_status, t)}
          </span>
          {batchModeEnabled && (
            <Checkbox
              checked={isSelected}
              onClick={(e) => {
                e.stopPropagation();
                onToggleSelect(skill.name);
              }}
            />
          )}
        </div>
      </div>

      {/* Title + Built-in/Custom tag */}
      <div className={styles.titleRow}>
        <Tooltip title={skill.name}>
          <h3 className={styles.skillTitle}>
            {skill.name}{" "}
            {isBuiltin ? (
              <span className={styles.builtinTag}>
                {t("skillPool.builtin")}
              </span>
            ) : (
              <span className={styles.customTag}>{t("skillPool.custom")}</span>
            )}
          </h3>
        </Tooltip>
      </div>

      {/* Updated row */}
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

      {/* Tags row */}
      {
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
            "-"
          )}
        </div>
      }

      {/* Description */}
      <div className={styles.descriptionSection}>
        <span className={styles.descriptionSectionLabel}>
          {t("skills.skillDescription")}
        </span>
        <p className={styles.descriptionText}>{skill.description || "-"}</p>
      </div>

      {/* Footer - only show on hover or batch mode */}
      {(isHover || batchModeEnabled) && (
        <div className={styles.cardFooter}>
          <Button
            className={styles.actionButton}
            disabled={batchModeEnabled}
            onClick={(e) => {
              e.stopPropagation();
              onBroadcast(skill);
            }}
          >
            {t("skillPool.broadcast")}
          </Button>
          <Button
            danger
            className={styles.deleteButton}
            disabled={batchModeEnabled}
            onClick={(e) => {
              e.stopPropagation();
              void onDelete(skill);
            }}
          >
            {t("skillPool.delete")}
          </Button>
        </div>
      )}
    </Card>
  );
}
