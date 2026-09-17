import React, { useMemo, useState } from "react";
import { Button, Progress } from "antd";
import {
  CheckCircle2,
  Circle,
  Clock3,
  LoaderCircle,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useCurrentPlan } from "../PlanPanel/useCurrentPlan";
import styles from "./index.module.less";

interface ChatPlanPanelProps {
  enabled: boolean;
}

const STATE_CLASS: Record<string, string> = {
  todo: styles.stateTodo,
  in_progress: styles.stateInProgress,
  done: styles.stateDone,
  abandoned: styles.stateAbandoned,
};

const STATE_ICON: Record<string, React.ReactNode> = {
  todo: <Circle size={13} strokeWidth={2} />,
  in_progress: <LoaderCircle size={13} strokeWidth={2} />,
  done: <CheckCircle2 size={13} strokeWidth={2} />,
  abandoned: <XCircle size={13} strokeWidth={2} />,
};

function StatePill({
  state,
  label,
  compact = false,
}: {
  state: string;
  label: string;
  compact?: boolean;
}) {
  return (
    <span
      className={`${compact ? styles.subtaskState : styles.state} ${
        STATE_CLASS[state] || ""
      }`}
      title={label}
      aria-label={label}
    >
      <span className={styles.stateIcon}>
        {STATE_ICON[state] || <Clock3 size={13} strokeWidth={2} />}
      </span>
      <span className={styles.stateLabel}>{label}</span>
    </span>
  );
}

const ChatPlanPanel: React.FC<ChatPlanPanelProps> = ({ enabled }) => {
  const { t } = useTranslation();
  const { plan } = useCurrentPlan(enabled);
  const [expanded, setExpanded] = useState(true);

  const stats = useMemo(() => {
    const subtasks = plan?.subtasks ?? [];
    const doneCount = subtasks.filter(
      (item) => item.state === "done" || item.state === "abandoned",
    ).length;
    const current =
      subtasks.find((item) => item.state === "in_progress") ??
      subtasks.find((item) => item.state === "todo") ??
      null;
    const percent =
      subtasks.length > 0 ? Math.round((doneCount / subtasks.length) * 100) : 0;
    return { doneCount, totalCount: subtasks.length, current, percent };
  }, [plan]);

  if (!enabled || !plan) return null;

  return (
    <section className={styles.panel} data-testid="chat-plan-panel">
      <div className={styles.summary}>
        <div className={styles.main}>
          <div className={styles.titleRow}>
            <span className={styles.title}>{plan.name}</span>
            <StatePill
              state={plan.state}
              label={t(`plan.state.${plan.state}`, plan.state)}
            />
          </div>
          <div className={styles.description}>{plan.description}</div>
          {stats.current && (
            <div className={styles.current}>
              {t("plan.currentTask", "Current")}: {stats.current.name}
            </div>
          )}
          {plan.outcome && (
            <div className={styles.current}>
              {t("plan.outcome", "Outcome")}: {plan.outcome}
            </div>
          )}
        </div>

        <div className={styles.progressBox}>
          <div className={styles.progressText}>
            {stats.doneCount}/{stats.totalCount}
          </div>
          <Progress
            percent={stats.percent}
            size="small"
            status={plan.state === "abandoned" ? "exception" : "active"}
            strokeColor={plan.state === "abandoned" ? "#dc2626" : "#4f46e5"}
            trailColor="rgba(15, 23, 42, 0.08)"
            showInfo={false}
          />
          <Button
            size="small"
            type="text"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded
              ? t("common.collapse", "Collapse")
              : t("common.expand", "Expand")}
          </Button>
        </div>
      </div>

      {expanded && (
        <ol className={styles.subtasks}>
          {plan.subtasks.map((subtask, index) => (
            <li key={`${subtask.name}-${index}`} className={styles.subtask}>
              <StatePill
                compact
                state={subtask.state}
                label={t(`plan.state.${subtask.state}`, subtask.state)}
              />
              <div className={styles.subtaskBody}>
                <div className={styles.subtaskName}>{subtask.name}</div>
                <div className={styles.subtaskDesc}>
                  {subtask.description}
                </div>
                {subtask.outcome && (
                  <div className={styles.subtaskOutcome}>
                    {subtask.outcome}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
};

export default ChatPlanPanel;
