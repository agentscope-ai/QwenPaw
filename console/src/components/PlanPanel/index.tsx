import React from "react";
import { Drawer, Progress, Spin } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkOperateRightLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import { useCurrentPlan } from "./useCurrentPlan";
import styles from "./index.module.less";

interface PlanPanelProps {
  open: boolean;
  onClose: () => void;
}

const STATE_ICONS: Record<string, string> = {
  done: "✅",
  in_progress: "🔄",
  abandoned: "⛔",
  todo: "⬜",
};

const STATE_CLASS: Record<string, string> = {
  todo: styles.stateTodo,
  in_progress: styles.stateInProgress,
  done: styles.stateDone,
  abandoned: styles.stateAbandoned,
};

const PlanPanel: React.FC<PlanPanelProps> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const { plan, loading } = useCurrentPlan(open);

  const doneCount =
    plan?.subtasks.filter((s) => s.state === "done" || s.state === "abandoned")
      .length ?? 0;
  const totalCount = plan?.subtasks.length ?? 0;
  const percent =
    totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  return (
    <Drawer
      className={styles.drawer}
      open={open}
      onClose={onClose}
      placement="right"
      width={380}
      closable={false}
      title={null}
      styles={{ body: { padding: 0 } }}
    >
      <div className={styles.header}>
        <span className={styles.headerTitle}>{t("plan.title", "Plan")}</span>
        <IconButton
          bordered={false}
          icon={<SparkOperateRightLine />}
          onClick={onClose}
        />
      </div>

      <div className={styles.content}>
        {loading && !plan ? (
          <div className={styles.emptyState}>
            <Spin />
          </div>
        ) : !plan ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>📋</div>
            <div>{t("plan.noPlan", "No active plan")}</div>
            <div className={styles.emptyHint}>
              {t("plan.noPlanHint", "Use /plan <description> to create a plan")}
            </div>
          </div>
        ) : (
          <>
            <div className={styles.planInfo}>
              <div className={styles.planName}>
                {plan.name}
                <span
                  className={`${styles.planState} ${
                    STATE_CLASS[plan.state] || ""
                  }`}
                >
                  {t(`plan.state.${plan.state}`, plan.state)}
                </span>
              </div>
              <div className={styles.planDesc}>{plan.description}</div>
            </div>

            <div className={styles.progressSection}>
              <div className={styles.progressLabel}>
                {t("plan.progress", "Progress")} — {doneCount}/{totalCount}
              </div>
              <Progress
                percent={percent}
                size="small"
                status={plan.state === "abandoned" ? "exception" : "active"}
                showInfo={false}
              />
            </div>

            <ul className={styles.subtaskList}>
              {plan.subtasks.map((subtask, idx) => (
                <li key={idx} className={styles.subtaskItem}>
                  <span className={styles.subtaskIcon}>
                    {STATE_ICONS[subtask.state] || "⬜"}
                  </span>
                  <div className={styles.subtaskBody}>
                    <div className={styles.subtaskName}>{subtask.name}</div>
                    <div className={styles.subtaskDesc}>
                      {subtask.description}
                    </div>
                    {subtask.outcome && (
                      <div className={styles.subtaskOutcome}>
                        ✓ {subtask.outcome}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            {plan.outcome && (
              <div className={styles.planOutcomeSection}>
                <strong>{t("plan.outcome", "Outcome")}:</strong> {plan.outcome}
              </div>
            )}
          </>
        )}
      </div>
    </Drawer>
  );
};

export default PlanPanel;
