import { useEffect, useState } from "react";
import { Button, Card, Checkbox, Tooltip } from "@agentscope-ai/design";
import { SyncOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolSkillAutomationState,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import { SkillVisual } from "@/components/SkillVisual";
import styles from "../index.module.less";

interface PoolSkillCardProps {
  skill: PoolSkillSpec;
  isSelected: boolean;
  batchModeEnabled: boolean;
  automationPending?: boolean;
  onToggleSelect: (name: string) => void;
  onEdit: (skill: PoolSkillSpec) => void;
  onBroadcast: (skill: PoolSkillSpec) => void;
  onDelete: (skill: PoolSkillSpec) => void;
  onAutomationQuickAction: (skill: PoolSkillSpec) => void | Promise<void>;
}

export function PoolSkillCard({
  skill,
  isSelected,
  batchModeEnabled,
  automationPending = false,
  onToggleSelect,
  onEdit,
  onBroadcast,
  onDelete,
  onAutomationQuickAction,
}: PoolSkillCardProps) {
  const { t } = useTranslation();
  const [isHover, setIsHover] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const syncTone = getPoolBuiltinStatusTone(skill.sync_status);
  const isBuiltin = isSkillBuiltin(skill.source);
  const automationState = getPoolSkillAutomationState(skill);
  let automationTag = "";
  let automationTagHint = "";
  let automationActionKey = "skillPool.autoSyncEnableHint";

  if (!isBuiltin) {
    if (skill.auto_sync) {
      automationTag = t("skillPool.autoSync");
      automationTagHint = t("skillPool.autoSyncFlow");
      automationActionKey = "skillPool.autoSyncDisableHint";
    }
  } else if (automationState === "mixed") {
    automationTag = t(
      skill.auto_update ? "skillPool.builtinAutoUpdate" : "skillPool.autoSync",
    );
    automationTagHint = t(
      skill.auto_update
        ? "skillPool.builtinAutoUpdateFlow"
        : "skillPool.autoSyncFlow",
    );
    automationActionKey = "skillPool.automationMixedHint";
  } else if (automationState === "on") {
    automationTag = t("skillPool.automationBoth");
    automationTagHint = `${t("skillPool.builtinAutoUpdateFlow")}; ${t(
      "skillPool.autoSyncFlow",
    )}`;
    automationActionKey = "skillPool.automationDisableHint";
  } else {
    automationActionKey = "skillPool.automationEnableHint";
  }
  const automationActionHint = t(automationActionKey);

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 768px)");
    const handleChange = (event: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(event.matches);
    };
    handleChange(mql);
    mql.addEventListener("change", handleChange);
    return () => {
      mql.removeEventListener("change", handleChange);
    };
  }, []);

  return (
    <Card
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
          <SkillVisual
            name={skill.name}
            emoji={skill.emoji}
            emojiClassName={styles.skillEmoji}
          />
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
            {automationTag && (
              <Tooltip title={automationTagHint}>
                <span className={styles.automationTag}>{automationTag}</span>
              </Tooltip>
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
      <div className={styles.metaInfoRow}>
        <span className={styles.metaInfoLabel}>{t("skills.tags")}</span>
        {skill.tags?.length ? (
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

      {/* Description */}
      <div className={styles.descriptionSection}>
        <p className={styles.descriptionText}>{skill.description || "-"}</p>
      </div>

      {/* Footer - show on hover, batch mode, or mobile (no hover) */}
      {(isHover || batchModeEnabled || isMobile) && (
        <div className={styles.cardFooter}>
          <Tooltip title={automationActionHint}>
            <Button
              data-testid={`skill-automation-${skill.name}`}
              aria-label={automationActionHint}
              aria-pressed={
                automationState === "mixed" ? "mixed" : automationState === "on"
              }
              className={`${styles.automationButton} ${
                automationState === "mixed" ? styles.automationMixedButton : ""
              }`}
              type={automationState === "on" ? "primary" : "default"}
              icon={<SyncOutlined />}
              loading={automationPending}
              disabled={batchModeEnabled || automationPending}
              onClick={(e) => {
                e.stopPropagation();
                void onAutomationQuickAction(skill);
              }}
            />
          </Tooltip>
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
