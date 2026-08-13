import { Alert, Button, Modal } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";

import type { ReMeMemoryStatusResponse } from "@/api/modules/agents";
import styles from "../index.module.less";

interface ReMeStatusModalProps {
  open: boolean;
  view: "tasks" | "diagnostics";
  loading: boolean;
  error: string;
  memoryStatus: ReMeMemoryStatusResponse | null;
  statusBadge: { className: string };
  statusBadgeLabel: string;
  onRefresh: () => void;
  onClose: () => void;
}

export function ReMeStatusModal({
  open,
  view,
  loading,
  error,
  memoryStatus,
  statusBadge,
  statusBadgeLabel,
  onRefresh,
  onClose,
}: ReMeStatusModalProps) {
  const { t } = useTranslation();
  const formatRuntimeTime = (value: string | null) =>
    value ? new Date(value).toLocaleString() : t("agentConfig.memoryNeverRun");

  return (
    <Modal
      open={open}
      width={680}
      title={
        <div className={styles.memoryStatusModalTitle}>
          <strong>
            {t(
              view === "tasks"
                ? "agentConfig.memoryBackgroundTasks"
                : "agentConfig.memoryDiagnostics",
            )}
          </strong>
          <span>
            {t(
              view === "tasks"
                ? "agentConfig.memoryRuntimeActivityDescription"
                : "agentConfig.memoryResourceUsageDescription",
            )}
          </span>
        </div>
      }
      onCancel={onClose}
      footer={
        <div className={styles.memoryStatusModalFooter}>
          <Button onClick={onRefresh} loading={loading}>
            {t("common.refresh")}
          </Button>
          <Button type="primary" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      }
    >
      {loading && !memoryStatus ? (
        <div className={styles.memoryStatusLoading}>
          <Spin />
          <span>{t("agentConfig.remeStatusLoading")}</span>
        </div>
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message={t("agentConfig.remeStatusFailed")}
          description={error}
        />
      ) : memoryStatus ? (
        <div className={styles.memoryStatusContent}>
          {view === "tasks" ? (
            <section className={styles.memoryTaskPanel}>
              <div className={styles.memoryTaskSummary}>
                <div>
                  <strong>
                    {memoryStatus.runtime.worker.tasks_running === 0 &&
                    memoryStatus.runtime.worker.queue_pending === 0
                      ? t("agentConfig.memoryQueueIdleSummary")
                      : t("agentConfig.memoryQueueSummary", {
                          running: memoryStatus.runtime.worker.tasks_running,
                          pending: memoryStatus.runtime.worker.queue_pending,
                        })}
                  </strong>
                  <span>
                    {memoryStatus.runtime.auto_memory.enabled
                      ? t("agentConfig.memoryAutoMemoryEnabledSummary", {
                          interval: memoryStatus.runtime.auto_memory.interval,
                        })
                      : t("agentConfig.memoryAutoRecordDisabledHint")}
                  </span>
                  {memoryStatus.runtime.auto_memory.pending_turns > 0 ? (
                    <span>
                      {t("agentConfig.memoryPendingSummary", {
                        sessions:
                          memoryStatus.runtime.auto_memory
                            .sessions_with_pending,
                        turns: memoryStatus.runtime.auto_memory.pending_turns,
                      })}
                    </span>
                  ) : null}
                </div>
                <strong
                  className={`${styles.memoryStatusBadge} ${statusBadge.className}`}
                >
                  <i />
                  {statusBadgeLabel}
                </strong>
              </div>
              {memoryStatus.runtime.recent.last_error ? (
                <Alert
                  type="error"
                  showIcon
                  message={t("agentConfig.memoryLastError")}
                  description={memoryStatus.runtime.recent.last_error}
                />
              ) : null}
              <div className={styles.memoryAutoMemoryHistory}>
                <div className={styles.memoryAutoMemoryHistoryHeader}>
                  <strong>{t("agentConfig.memoryRecentTasks")}</strong>
                </div>
                {memoryStatus.runtime.auto_memory.history.length ? (
                  <div className={styles.memoryAutoMemoryHistoryList}>
                    {memoryStatus.runtime.auto_memory.history.map((run) => (
                      <details key={run.task_id}>
                        <summary>
                          <span>
                            {t(`agentConfig.memoryTaskStatus.${run.status}`)}
                          </span>
                          <strong>
                            {formatRuntimeTime(
                              run.finished_at ?? run.queued_at,
                            )}
                          </strong>
                          <small>
                            {t("agentConfig.memoryTaskMessages", {
                              count: run.message_count,
                            })}
                          </small>
                        </summary>
                        <pre>
                          {run.result ??
                            run.error ??
                            t("agentConfig.memoryTaskNoResult")}
                        </pre>
                      </details>
                    ))}
                  </div>
                ) : (
                  <p className={styles.memoryAutoMemoryHistoryEmpty}>
                    {t("agentConfig.memoryRecentTasksEmpty")}
                  </p>
                )}
              </div>
            </section>
          ) : null}

          {view === "diagnostics" ? (
            <>
              <div className={styles.memoryStatusMetrics}>
                <div>
                  <span>{t("agentConfig.remeStatusComponentsTotal")}</span>
                  <strong>{memoryStatus.components_total}</strong>
                  <small>{t("agentConfig.remeStatusEstimated")}</small>
                </div>
                <div>
                  <span>{t("agentConfig.remeStatusProcessRss")}</span>
                  <strong>{memoryStatus.process_rss}</strong>
                  <small>{t("agentConfig.remeStatusProcessRssHint")}</small>
                </div>
              </div>

              <div className={styles.memoryStatusComponentSection}>
                <h4>{t("agentConfig.remeStatusComponents")}</h4>
                <div className={styles.memoryStatusComponentList}>
                  {Object.entries(memoryStatus.components).flatMap(
                    ([componentType, components]) =>
                      Object.entries(components).map(([name, usage]) => (
                        <div
                          className={styles.memoryStatusComponentRow}
                          key={`${componentType}:${name}`}
                        >
                          <span>
                            {t(
                              `agentConfig.remeStatusComponent.${componentType}`,
                              { defaultValue: componentType },
                            )}
                          </span>
                          <code>{name}</code>
                          <strong>{usage.human}</strong>
                        </div>
                      )),
                  )}
                </div>
              </div>

              <div className={styles.memoryStatusNote}>
                <span>i</span>
                <p>{t("agentConfig.remeStatusEstimateNote")}</p>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}
