import { Alert, Button, Modal } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";

import type { ReMeMemoryStatusResponse } from "@/api/modules/agents";
import styles from "../index.module.less";

interface ReMeStatusModalProps {
  open: boolean;
  loading: boolean;
  error: string;
  memoryStatus: ReMeMemoryStatusResponse | null;
  statusBadge: { className: string };
  statusBadgeLabel: string;
  workerStatusLabel: string;
  queueHint: string;
  onRefresh: () => void;
  onClose: () => void;
}

export function ReMeStatusModal({
  open,
  loading,
  error,
  memoryStatus,
  statusBadge,
  statusBadgeLabel,
  workerStatusLabel,
  queueHint,
  onRefresh,
  onClose,
}: ReMeStatusModalProps) {
  const { t } = useTranslation();
  const formatRuntimeTime = (value: string | null) =>
    value ? new Date(value).toLocaleString() : t("agentConfig.memoryNeverRun");

  return (
    <Modal
      open={open}
      width={740}
      title={
        <div className={styles.memoryStatusModalTitle}>
          <span className={styles.memoryStatusModalIcon}>R</span>
          <div>
            <strong>{t("agentConfig.remeStatusTitle")}</strong>
            <span>{t("agentConfig.remeStatusDescription")}</span>
          </div>
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
          <section className={styles.memoryRuntimeSection}>
            <div className={styles.memoryRuntimeSectionHeader}>
              <div>
                <h4>{t("agentConfig.memoryRuntimeActivity")}</h4>
                <p>{t("agentConfig.memoryRuntimeActivityDescription")}</p>
              </div>
              <strong
                className={`${styles.memoryStatusBadge} ${statusBadge.className}`}
              >
                <i />
                {statusBadgeLabel}
              </strong>
            </div>
            <div className={styles.memoryRuntimeGrid}>
              <div>
                <span>{t("agentConfig.memoryWorker")}</span>
                <strong>{workerStatusLabel}</strong>
                <small>{queueHint}</small>
              </div>
              <div>
                <span>{t("agentConfig.memoryQueue")}</span>
                <strong>{memoryStatus.runtime.worker.queue_pending}</strong>
                <small>{t("agentConfig.memoryQueuePendingHint")}</small>
              </div>
              <div>
                <span>{t("agentConfig.memoryPendingTurns")}</span>
                <strong>
                  {memoryStatus.runtime.auto_memory.enabled
                    ? memoryStatus.runtime.auto_memory.pending_turns
                    : "—"}
                </strong>
                <small>
                  {memoryStatus.runtime.auto_memory.enabled
                    ? t("agentConfig.memoryActiveSessionsHint", {
                        sessions:
                          memoryStatus.runtime.auto_memory.active_sessions,
                      })
                    : t("agentConfig.memoryAutoRecordDisabledHint")}
                </small>
              </div>
            </div>
            <div className={styles.memoryRecentActivity}>
              <div>
                <span>{t("agentConfig.memoryLastCompleted")}</span>
                <strong>
                  {formatRuntimeTime(
                    memoryStatus.runtime.recent.last_completed_at,
                  )}
                </strong>
              </div>
              <div>
                <span>{t("agentConfig.memoryLastFailed")}</span>
                <strong>
                  {formatRuntimeTime(
                    memoryStatus.runtime.recent.last_failed_at,
                  )}
                </strong>
              </div>
            </div>
            {memoryStatus.runtime.recent.last_error ? (
              <Alert
                type="error"
                showIcon
                message={t("agentConfig.memoryLastError")}
                description={memoryStatus.runtime.recent.last_error}
              />
            ) : null}
          </section>

          <div className={styles.memoryResourceHeading}>
            <h4>{t("agentConfig.memoryResourceUsage")}</h4>
            <p>{t("agentConfig.memoryResourceUsageDescription")}</p>
          </div>
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
                        {t(`agentConfig.remeStatusComponent.${componentType}`, {
                          defaultValue: componentType,
                        })}
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
        </div>
      ) : null}
    </Modal>
  );
}
