import { Button, Card, Checkbox } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  getSkillVisual,
} from "../../Skills/components";
import { SkillCategoryBadges, SkillTagChips } from "./SkillMeta";
import styles from "../index.module.less";

interface SkillPoolCardProps {
  skill: PoolSkillSpec;
  isSelected: boolean;
  batchMode: boolean;
  onToggleSelect: (name: string) => void;
  onEdit: (skill: PoolSkillSpec) => void;
  onBroadcast: (skill: PoolSkillSpec) => void;
  onDelete: (skill: PoolSkillSpec) => void;
}

export function SkillPoolCard({
  skill,
  isSelected,
  batchMode,
  onToggleSelect,
  onEdit,
  onBroadcast,
  onDelete,
}: SkillPoolCardProps) {
  const { t } = useTranslation();

  const handleClick = () => {
    if (batchMode) {
      onToggleSelect(skill.name);
    } else {
      onEdit(skill);
    }
  };

  const handleSelectClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggleSelect(skill.name);
  };

  return (
    <Card
      className={`${styles.skillCard} ${isSelected ? styles.selectedCard : ""}`}
      onClick={handleClick}
      style={{ cursor: "pointer" }}
    >
      <div className={styles.cardBody}>
        <div className={styles.cardHeader}>
          <div className={styles.leftSection}>
            <div className={styles.fileIconWrapper}>
              <span className={styles.fileIcon}>
                {getSkillVisual(skill.name, skill.emoji)}
              </span>
              {batchMode && (
                <Checkbox checked={isSelected} onClick={handleSelectClick} />
              )}
            </div>

            <div className={styles.titleRow}>
              <h3 className={styles.skillTitle}>{skill.name}</h3>
              <SkillCategoryBadges categories={skill.categories} />
            </div>
          </div>
          <div className={styles.statusWithSelect}>
            <div>
              <div className={styles.statusRow}>
                <span className={styles.statusLabel}>
                  {t("skillPool.status")}:
                </span>
                <span
                  className={`${styles.statusValue} ${
                    styles[getPoolBuiltinStatusTone(skill.sync_status)]
                  }`}
                >
                  {getPoolBuiltinStatusLabel(skill.sync_status, t)}
                </span>
              </div>
              {skill.last_updated && (
                <div className={styles.statusRow}>
                  <span className={styles.statusLabel}>
                    {t("skills.lastUpdated")}:
                  </span>
                  <span className={styles.statusValue}>
                    {dayjs(skill.last_updated).fromNow()}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className={styles.descriptionContainer}>
          <p className={styles.descriptionLabel}>
            {t("skillPool.descriptionLabel")}
          </p>
          <p className={styles.descriptionText}>{skill.description || "-"}</p>
          <SkillTagChips tags={skill.tags} />
        </div>
      </div>
      <div className={styles.cardFooter}>
        <Button
          className={styles.actionButton}
          disabled={batchMode}
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
          disabled={batchMode}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(skill);
          }}
        >
          {t("skillPool.delete")}
        </Button>
      </div>
    </Card>
  );
}
