import { Alert, Button, Modal } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";

import type {
  ReMeMemoryRuntimeStatus,
  ReMeMemoryStatusResponse,
} from "@/api/modules/agents";
import styles from "../index.module.less";

interface ReMeStatusModalProps {
  view: "tasks" | "diagnostics" | null;
  loading: boolean;
  error: string;
  runtime: ReMeMemoryRuntimeStatus | null;
  diagnostics: ReMeMemoryStatusResponse | null;
  statusBadge: { className: string };
  statusBadgeLabel: string;
  onRefresh: () => void;
  onClose: () => void;
}

export function ReMeStatusModal({
  view,
  loading,
  error,
  runtime,
  diagnostics,
  statusBadge,
  statusBadgeLabel,
  onRefresh,
  onClose,
}: ReMeStatusModalProps) {
  const { t } = useTranslation();
  const formatRuntimeTime = (value: string | null) =>
    value ? new Date(value).toLocaleString() : t("agentConfig.memoryNeverRun");
  const worker = runtime?.worker;
  const autoMemory = runtime?.auto_memory;
  const tasks = runtime?.tasks;
  const recent = runtime?.recent;
  let queueSummary = "";
  if (worker) {
    queueSummary =
      worker.tasks_running === 0 && worker.queue_pending === 0
        ? t("agentConfig.memoryQueueIdleSummary")
        : t("agentConfig.memoryQueueSummary", {
            running: worker.tasks_running,
            pending: worker.queue_pending,
          });
  }

  return (
    <Modal
      open={view !== null}
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
      {loading && !(view === "tasks" ? runtime : diagnostics) ? (
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
      ) : runtime || diagnostics ? (
        <div className={styles.memoryStatusContent}>
          {view === "tasks" ? (
            <section className={styles.memoryTaskPanel}>
              <div className={styles.memoryTaskSummary}>
                <div>
                  <strong>{queueSummary}</strong>
                  <span>
                    {autoMemory?.enabled
                      ? t("agentConfig.memoryAutoMemoryEnabledSummary", {
                          interval: autoMemory.interval,
                        })
                      : t("agentConfig.memoryAutoRecordDisabledHint")}
                  </span>
                </div>
                <strong
                  className={`${styles.memoryStatusBadge} ${statusBadge.className}`}
                >
                  <i />
                  {statusBadgeLabel}
                </strong>
              </div>
              {recent?.last_error ? (
                <Alert
                  type="error"
                  showIcon
                  message={t("agentConfig.memoryLastError")}
                  description={recent.last_error}
                />
              ) : null}
              <div className={styles.memoryAutoMemoryHistory}>
                <div className={styles.memoryAutoMemoryHistoryHeader}>
                  <strong>{t("agentConfig.memoryRecentTasks")}</strong>
                </div>
                {tasks?.length ? (
                  <div className={styles.memoryAutoMemoryHistoryList}>
                    {tasks.map((run) => (
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
                  <strong>{diagnostics?.components_total}</strong>
                  <small>{t("agentConfig.remeStatusEstimated")}</small>
                </div>
                <div>
                  <span>{t("agentConfig.remeStatusProcessRss")}</span>
                  <strong>{diagnostics?.process_rss}</strong>
                  <small>{t("agentConfig.remeStatusProcessRssHint")}</small>
                </div>
              </div>

              <div className={styles.memoryStatusComponentSection}>
                <h4>{t("agentConfig.remeStatusComponents")}</h4>
                <div className={styles.memoryStatusComponentList}>
                  {Object.entries(diagnostics?.components ?? {}).flatMap(
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
