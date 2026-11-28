import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import InlineHelp from "@/components/InlineHelp";
import { Button, Checkbox, Tooltip } from "@agentscope-ai/design";
import { Dropdown } from "antd";
import { Check, MoreHorizontal, RefreshCw, Send, Trash2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import cardStyles from "./PoolSkillCard.module.less";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import {
  CommunityFeedback,
  hasCommunityFeedback,
} from "@/components/CommunityFeedback";
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
  onAutomationQuickAction: (
    skill: PoolSkillSpec,
    setting: "auto_sync" | "auto_update",
  ) => void | Promise<void>;
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
  const description = skill.description || t("skills.noDescription");

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
            !event.currentTarget.contains(event.target as Node) ||
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
                    key: "auto_sync",
                    label: (
                      <span className={cardStyles.menuAction}>
                        {t("skillPool.autoSync")}
                        {skill.auto_sync && (
                          <Check size={14} aria-label={t("common.enabled")} />
                        )}
                      </span>
                    ),
                    icon: <RefreshCw size={15} />,
                    disabled: automationPending,
                  },
                  ...(isBuiltin
                    ? [
                        {
                          key: "auto_update",
                          label: (
                            <span className={cardStyles.menuAction}>
                              {t("skillPool.builtinAutoUpdate")}
                              {skill.auto_update && (
                                <Check
                                  size={14}
                                  aria-label={t("common.enabled")}
                                />
                              )}
                            </span>
                          ),
                          icon: <RefreshCw size={15} />,
                          disabled: automationPending,
                        },
                      ]
                    : []),
                  {
                    key: "broadcast",
                    label: t("skillPool.broadcast"),
                    icon: <Send size={15} />,
                    disabled: automationPending,
                  },
                  { type: "divider" },
                  {
                    key: "delete",
                    label: t("skillPool.delete"),
                    danger: true,
                    icon: <Trash2 size={15} />,
                    disabled: automationPending,
                  },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation();
                  if (key === "auto_sync" || key === "auto_update") {
                    void onAutomationQuickAction(skill, key);
                  } else if (key === "broadcast") {
                    onBroadcast(skill);
                  } else if (key === "delete") {
                    onDelete(skill);
                  }
                },
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
            title={skill.name}
            onClick={() =>
              batchModeEnabled ? onToggleSelect(skill.name) : onEdit(skill)
            }
          >
            {skill.name}
          </button>
          <InlineHelp>{description}</InlineHelp>
        </div>
        {hasCommunityFeedback(skill.installation_origin) && (
          <CommunityFeedback
            origin={skill.installation_origin}
            resourceName={skill.name}
            variant="inline"
          />
        )}
        <div className={cardStyles.metadata}>
          <Tooltip
            title={
              skill.sync_status === "removed"
                ? t("skillPool.statusRemovedHint")
                : undefined
            }
            trigger={["hover", "focus"]}
          >
            <span
              className={`${styles.statusBadge} ${
                styles[`status_${syncTone}`]
              }`}
              tabIndex={skill.sync_status === "removed" ? 0 : undefined}
            >
              {getPoolBuiltinStatusLabel(skill.sync_status, t)}
            </span>
          </Tooltip>
          {skill.last_updated && (
            <time
              className={cardStyles.updatedAt}
              dateTime={skill.last_updated}
            >
              {t("skillPool.updatedAgo", {
                time: dayjs(skill.last_updated).fromNow(),
              })}
            </time>
          )}
        </div>
        <p className={cardStyles.description}>{description}</p>
        {!!skill.tags?.length && (
          <div className={cardStyles.tags}>
            {skill.tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        )}
      </InteractiveCard>
    </motion.div>
  );
}
