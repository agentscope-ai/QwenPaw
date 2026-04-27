import React, { useCallback, useEffect, useRef, useState } from "react";
import { Drawer, Progress, Spin } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkOperateRightLine } from "@agentscope-ai/icons";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import {
  planApi,
  subscribePlanUpdates,
  type PlanStateResponse,
} from "../../api/modules/plan";
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

/**
 * Read the console channel session ID that the backend actually uses.
 * This differs from the chat-state `currentSessionId` (which is a
 * ChatSpec UUID), so we must read the window global that the
 * sessionApi keeps in sync.
 */
function getBackendSessionId(): string {
  return (window as any).currentSessionId || "";
}

const PlanPanel: React.FC<PlanPanelProps> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const { currentSessionId } = useChatAnywhereSessionsState();
  const [plan, setPlan] = useState<PlanStateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const unsubRef = useRef<(() => void) | null>(null);
  // Track the latest plan provided by SSE so polling cannot overwrite it
  // with a stale null response.
  const ssePlanRef = useRef<PlanStateResponse | null>(null);
  const prevBackendSidRef = useRef("");

  const fetchPlan = useCallback(async () => {
    const sid = getBackendSessionId();
    setLoading(true);
    try {
      const data = await planApi.getCurrentPlan(sid || undefined);
      // If SSE already provided a non-null plan but the poll returned null,
      // trust SSE — the cache may not have been populated for this session_id
      // yet, or a race condition caused a stale response.
      if (ssePlanRef.current !== null && data === null) return;
      setPlan(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [currentSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch plan when panel opens or backend session changes
  useEffect(() => {
    if (open) {
      const backendSid = getBackendSessionId();
      if (backendSid !== prevBackendSidRef.current) {
        prevBackendSidRef.current = backendSid;
      }
      // Drop any SSE snapshot from a previous open: while the drawer was
      // closed we were unsubscribed, so ssePlanRef may be stale while
      // GET /plan/current correctly returns null or a newer plan.
      ssePlanRef.current = null;
      fetchPlan();
    }
  }, [open, fetchPlan]);

  // Subscribe to SSE when panel is open
  useEffect(() => {
    if (!open) {
      unsubRef.current?.();
      unsubRef.current = null;
      return;
    }

    const unsub = subscribePlanUpdates((updatedPlan, eventSessionId) => {
      const mySid = getBackendSessionId();
      if (eventSessionId && mySid && eventSessionId !== mySid) return;
      ssePlanRef.current = updatedPlan;
      setPlan(updatedPlan);
    });
    unsubRef.current = unsub;

    return () => {
      unsub();
      unsubRef.current = null;
    };
  }, [open]);

  // Polling fallback every 5s when open
  useEffect(() => {
    if (!open) return;
    const interval = setInterval(fetchPlan, 5000);
    return () => clearInterval(interval);
  }, [open, fetchPlan]);

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
            <div style={{ fontSize: 12, marginTop: 8 }}>
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
              <div style={{ marginTop: 16, fontSize: 13 }}>
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
