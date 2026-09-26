import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import InlineHelp from "@/components/InlineHelp";
import { Button, Checkbox, Tooltip } from "@agentscope-ai/design";
import { Dropdown } from "antd";
import { MoreHorizontal, Send, Trash2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import cardStyles from "./PoolSkillCard.module.less";
import { RefreshCw as SyncOutlined } from "lucide-react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolSkillAutomationState,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
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
  const reduced = useReducedMotion();
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

  return (
    <motion.div
      layout
      transition={{
        layout: reduced
          ? { duration: 0 }
          : { type: "spring", stiffness: 340, damping: 36 },
      }}
    >
      <InteractiveCard
        tilt={0}
        className={cardStyles.card}
        onClick={(event) => {
          if (
            (event.target as Element).closest(
              'button, input, [role="button"], [role="checkbox"]',
            )
          )
            return;
          if (batchModeEnabled) onToggleSelect(skill.name);
          else onEdit(skill);
        }}
        data-selected={isSelected || undefined}
      >
        <div className={cardStyles.heading}>
          <div className={cardStyles.origin}>
            {t(isBuiltin ? "skillPool.builtin" : "skillPool.custom")}
            {skill.version_text && <span>v{skill.version_text}</span>}
          </div>
          {batchModeEnabled ? (
            <Checkbox
              aria-label={skill.name}
              checked={isSelected}
              onChange={() => onToggleSelect(skill.name)}
            />
          ) : (
            <Dropdown
              trigger={["click"]}
              menu={{
                items: [
                  {
                    key: "delete",
                    label: t("skillPool.delete"),
                    danger: true,
                    icon: <Trash2 size={15} />,
                  },
                ],
                onClick: () => onDelete(skill),
              }}
            >
              <Button
                type="text"
                aria-label={t("common.actions")}
                icon={<MoreHorizontal size={18} />}
              />
            </Dropdown>
          )}
        </div>
        <div className={cardStyles.title}>
          <button
            type="button"
            onClick={() =>
              batchModeEnabled ? onToggleSelect(skill.name) : onEdit(skill)
            }
          >
            {skill.name}
          </button>
          <InlineHelp>
            {skill.description || t("skills.noDescription")}
          </InlineHelp>
        </div>
        <div className={cardStyles.metadata}>
          <span
            className={`${styles.statusBadge} ${styles[`status_${syncTone}`]}`}
          >
            {getPoolBuiltinStatusLabel(skill.sync_status, t)}
          </span>
          {skill.last_updated && (
            <span>{dayjs(skill.last_updated).fromNow()}</span>
          )}
        </div>
        {!!skill.tags?.length && (
          <div className={cardStyles.tags}>
            {skill.tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        )}
        <div className={cardStyles.footer}>
          <Tooltip title={automationTagHint || automationActionHint}>
            <Button
              data-testid={`skill-automation-${skill.name}`}
              aria-label={automationActionHint}
              aria-pressed={
                automationState === "mixed" ? "mixed" : automationState === "on"
              }
              type="text"
              icon={<SyncOutlined size={16} />}
              loading={automationPending}
              disabled={batchModeEnabled || automationPending}
              onClick={() => void onAutomationQuickAction(skill)}
            >
              {automationTag || t("skillPool.autoSync")}
            </Button>
          </Tooltip>
          <Button
            disabled={batchModeEnabled}
            icon={<Send size={15} />}
            onClick={() => onBroadcast(skill)}
          >
            {t("skillPool.broadcast")}
          </Button>
        </div>
      </InteractiveCard>
    </motion.div>
  );
}
