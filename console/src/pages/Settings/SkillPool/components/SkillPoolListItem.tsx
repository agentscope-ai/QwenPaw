import { Button, Checkbox } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  getSkillVisual,
} from "../../../Agent/Skills/components";
import styles from "../index.module.less";

interface SkillPoolListItemProps {
  skill: PoolSkillSpec;
  isSelected: boolean;
  batchMode: boolean;
  onToggleSelect: (name: string) => void;
  onEdit: (skill: PoolSkillSpec) => void;
  onBroadcast: (skill: PoolSkillSpec) => void;
  onDelete: (skill: PoolSkillSpec) => void;
}

export function SkillPoolListItem({
  skill,
  isSelected,
  batchMode,
  onToggleSelect,
  onEdit,
  onBroadcast,
  onDelete,
}: SkillPoolListItemProps) {
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
    <div
      className={`${styles.skillListItem} ${
        isSelected ? styles.selectedListItem : ""
      }`}
      onClick={handleClick}
    >
      {batchMode && (
        <Checkbox checked={isSelected} onClick={handleSelectClick} />
      )}
      <div className={styles.listItemLeft}>
        <span className={styles.fileIcon}>
          {getSkillVisual(skill.name, skill.content)}
        </span>
        <div className={styles.listItemInfo}>
          <div className={styles.listItemHeader}>
            <span className={styles.skillTitle}>{skill.name}</span>
            <span
              className={`${styles.statusValue} ${
                styles[getPoolBuiltinStatusTone(skill.sync_status)]
              }`}
            >
              {getPoolBuiltinStatusLabel(skill.sync_status, t)}
            </span>
            {skill.last_updated && (
              <span className={styles.listItemTime}>
                {t("skills.lastUpdated")} {dayjs(skill.last_updated).fromNow()}
              </span>
            )}
          </div>
          <p className={styles.listItemDesc}>{skill.description || "-"}</p>
        </div>
      </div>
      <div className={styles.listItemRight}>
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
    </div>
  );
}
