import React from "react";
import { Card, Button, Tooltip } from "@agentscope-ai/design";
import { DeleteOutlined, ThunderboltOutlined } from "@ant-design/icons";
import type { SkillSpec } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface SkillCardProps {
  skill: SkillSpec;
  onToggleEnabled: (e: React.MouseEvent) => void;
  onMoveToInactive: (e: React.MouseEvent) => void;
  onMoveToBuiltin: (e: React.MouseEvent) => void;
  onDelete?: (e?: React.MouseEvent) => void;
}

export function SkillCard({
  skill,
  onToggleEnabled,
  onMoveToInactive,
  onMoveToBuiltin,
  onDelete,
}: SkillCardProps) {
  const { t } = useTranslation();
  const isBuiltin = skill.source === "builtin";
  const isInactive = skill.source === "inactive";

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onDelete) {
      onDelete(e);
    }
  };

  return (
    <Card
      className={`${styles.skillCard} ${
        skill.enabled ? styles.enabledCard : ""
      } ${isBuiltin ? styles.builtinCard : styles.inactiveCard}`}
    >
      <div className={styles.cardBody}>
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <ThunderboltOutlined className={styles.zapIcon} />
            <h3 className={styles.skillTitle}>{skill.name}</h3>
          </div>
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusDot} ${
                skill.enabled ? styles.enabled : styles.disabled
              }`}
            />
            <span
              className={`${styles.statusText} ${
                skill.enabled ? styles.enabled : styles.disabled
              }`}
            >
              {skill.enabled
                ? t("defaultSkills.statusEnabled", "当前 Agent 已启用")
                : t("defaultSkills.statusDisabled", "当前 Agent 未启用")}
            </span>
          </div>
        </div>

        <div className={styles.descriptionSection}>
          <div className={styles.infoLabel}>{t("skills.skillDescription")}</div>
          <Tooltip
            title={skill.description || "-"}
            placement="top"
            overlayStyle={{ maxWidth: 360 }}
          >
            <div className={`${styles.infoBlock} ${styles.descriptionContent}`}>
              {skill.description || "-"}
            </div>
          </Tooltip>
        </div>

        <div className={styles.metaStack}>
          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.source")}</div>
            <div>
              <span
                className={
                  isBuiltin ? styles.builtinTag : styles.inactiveTag
                }
              >
                {isBuiltin
                  ? t("defaultSkills.builtin", "内置技能")
                  : t("defaultSkills.inactive", "非内置")}
              </span>
            </div>
          </div>

          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skills.path")}</div>
            <div
              className={`${styles.infoBlock} ${styles.singleLineValue} ${styles.pathValue}`}
              title={skill.path}
            >
              {skill.path}
            </div>
          </div>
        </div>
      </div>

      <div className={styles.cardFooter}>
        <Button
          type="link"
          size="small"
          onClick={onToggleEnabled}
          className={styles.actionButton}
        >
          {skill.enabled
            ? t("common.disable")
            : t("defaultSkills.enableInAgent", "在当前 Agent 启用")}
        </Button>

        <Button
          type="link"
          size="small"
          onClick={isBuiltin ? onMoveToInactive : onMoveToBuiltin}
          className={styles.actionButton}
        >
          {isBuiltin
            ? t("defaultSkills.moveToInactive", "移动到非内置")
            : t("defaultSkills.moveToBuiltin", "移动到内置")}
        </Button>

        {isInactive && onDelete && (
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            className={styles.deleteButton}
            onClick={handleDeleteClick}
          />
        )}
      </div>
    </Card>
  );
}
