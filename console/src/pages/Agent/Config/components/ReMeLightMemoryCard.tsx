import { useCallback, useEffect, useRef, useState } from "react";
import {
  Form,
  Card,
  Switch,
  InputNumber,
  Input,
  Alert,
  Button,
  Modal,
} from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api";
import type { ReMeMemoryStatusResponse } from "@/api/modules/agents";
import type { ReMeLightMemoryConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import styles from "../index.module.less";
import { useMemoryMaintenance } from "../memoryMaintenanceContext";

type RuntimeStatus =
  | { type: "unknown" }
  | { type: "checking" }
  | { type: "healthy"; data: ReMeMemoryStatusResponse }
  | { type: "error"; message: string };

export function isValidDreamCronShape(value?: string) {
  if (!value?.trim()) {
    return false;
  }
  const fields = value.trim().split(/\s+/);
  return (
    fields.length === 5 &&
    fields.every((field) => /^[a-z0-9*/,-]+$/i.test(field))
  );
}

export function ReMeLightMemoryCard() {
  const { t, i18n } = useTranslation();
  const { message, modal } = useAppMessage();
  const form = Form.useFormInstance();
  const { selectedAgent } = useAgentStore();
  const { setNeedsReindex } = useMemoryMaintenance();
  const [reindexing, setReindexing] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [dailyPaperExpanded, setDailyPaperExpanded] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>({
    type: "unknown",
  });
  const statusRequestRef = useRef<AbortController | null>(null);

  const rebuildMemoryIndex = () => {
    modal.confirm({
      title: t("agentConfig.rebuildMemoryIndexConfirmTitle"),
      content: t("agentConfig.rebuildMemoryIndexConfirm"),
      okText: t("agentConfig.rebuildMemoryIndex"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        setReindexing(true);
        try {
          await agentsApi.rebuildMemoryIndex(selectedAgent || "default");
          setNeedsReindex(false);
          message.success(t("agentConfig.rebuildMemoryIndexSuccess"));
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error);
          message.error(
            t("agentConfig.rebuildMemoryIndexFailed", { error: detail }),
          );
          throw error;
        } finally {
          setReindexing(false);
        }
      },
    });
  };

  const checkMemoryStatus = useCallback(
    async (openModal = false) => {
      if (openModal) setStatusOpen(true);

      statusRequestRef.current?.abort();
      const controller = new AbortController();
      statusRequestRef.current = controller;
      setRuntimeStatus({ type: "checking" });

      try {
        const status = await agentsApi.getMemoryStatus(
          selectedAgent || "default",
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setRuntimeStatus({ type: "healthy", data: status });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setRuntimeStatus({
            type: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      } finally {
        if (statusRequestRef.current === controller) {
          statusRequestRef.current = null;
        }
      }
    },
    [selectedAgent],
  );

  useEffect(() => {
    void checkMemoryStatus();
    return () => statusRequestRef.current?.abort();
  }, [checkMemoryStatus]);

  const inspectMemoryStatus = () => void checkMemoryStatus(true);
  const statusLoading = runtimeStatus.type === "checking";
  const memoryStatus =
    runtimeStatus.type === "healthy" ? runtimeStatus.data : null;
  const statusError =
    runtimeStatus.type === "error" ? runtimeStatus.message : "";
  const backendStatus = memoryStatus?.runtime.worker.status;
  const statusBadgeType =
    backendStatus === "error"
      ? "error"
      : backendStatus === "busy" ||
        backendStatus === "stopping" ||
        memoryStatus?.runtime.reindexing
      ? "checking"
      : runtimeStatus.type;
  const statusBadge = {
    unknown: {
      className: styles.memoryStatusUnknown,
      label: t("agentConfig.memoryStatusUnknown"),
    },
    checking: {
      className: styles.memoryStatusChecking,
      label: t("agentConfig.memoryStatusChecking"),
    },
    healthy: {
      className: styles.memoryStatusHealthy,
      label: t("agentConfig.memoryStatusRunning"),
    },
    error: {
      className: styles.memoryStatusError,
      label: t("agentConfig.memoryStatusCheckFailed"),
    },
  }[statusBadgeType];
  const statusBadgeLabel =
    backendStatus === "error"
      ? t("agentConfig.memoryStatusNeedsAttention")
      : backendStatus === "busy" || memoryStatus?.runtime.reindexing
      ? t("agentConfig.memoryStatusBusy")
      : backendStatus === "stopping"
      ? t("agentConfig.memoryStatusStopping")
      : statusBadge.label;

  const workerStatusLabel = backendStatus
    ? t(`agentConfig.memoryWorkerStatus.${backendStatus}`)
    : "—";
  const queueHint = memoryStatus
    ? t("agentConfig.memoryQueueSummary", {
        running: memoryStatus.runtime.worker.tasks_running,
        pending: memoryStatus.runtime.worker.queue_pending,
      })
    : "—";
  const autoMemoryStatus = memoryStatus?.runtime.auto_memory;
  const formatRuntimeTime = (value: string | null) =>
    value ? new Date(value).toLocaleString() : t("agentConfig.memoryNeverRun");

  const remeConfig = Form.useWatch(["reme_light_memory_config"], form) as
    | ReMeLightMemoryConfig
    | undefined;
  const autoMemoryInterval = Number(remeConfig?.auto_memory_interval ?? 0);
  const autoMemoryEnabled = autoMemoryInterval > 0;
  const dreamCronEnabled = remeConfig?.dream_cron_enabled ?? true;
  const dailyPaperCronEnabled = remeConfig?.daily_paper_cron_enabled ?? false;
  const autoSearchEnabled =
    remeConfig?.auto_memory_search_config?.enabled ?? false;
  const dailyPaperDocsUrl = (i18n?.resolvedLanguage || i18n?.language || "en")
    .toLowerCase()
    .startsWith("zh")
    ? "https://github.com/agentscope-ai/ReMe/blob/main/cookbook/daily_paper/README_ZH.md"
    : "https://github.com/agentscope-ai/ReMe/blob/main/cookbook/daily_paper/README.md";

  const toggleAutoMemory = (enabled: boolean) => {
    form.setFieldValue(
      ["reme_light_memory_config", "auto_memory_interval"],
      enabled ? Math.max(autoMemoryInterval, 1) : 0,
    );
  };

  return (
    <Card className={styles.formCard}>
      <section className={styles.memoryOverview}>
        <div className={styles.memoryOverviewHeader}>
          <div>
            <h3>{t("agentConfig.memoryOverviewTitle")}</h3>
            <p>{t("agentConfig.memoryPageDescription")}</p>
            <div className={styles.memoryReferences}>
              <span>{t("agentConfig.memoryPoweredBy")}</span>
              <a
                href="https://github.com/agentscope-ai/ReMe"
                target="_blank"
                rel="noreferrer"
              >
                ReMe
              </a>
              <i />
              <a
                href="https://qwenpaw.agentscope.io/docs/memory"
                target="_blank"
                rel="noreferrer"
              >
                {t("agentConfig.memoryDocumentation")}
              </a>
            </div>
          </div>
        </div>
        <div className={styles.memoryOverviewGrid}>
          <div
            className={`${styles.memoryOverviewItem} ${styles.memoryOverviewActionItem}`}
          >
            <div>
              <span>{t("agentConfig.memoryRuntimeStatus")}</span>
              <strong
                className={`${styles.memoryStatusBadge} ${statusBadge.className}`}
              >
                <i />
                {statusBadgeLabel}
              </strong>
            </div>
            <Button
              className={styles.memoryStatusButton}
              onClick={inspectMemoryStatus}
              loading={statusLoading}
            >
              {t("agentConfig.remeStatusView")}
            </Button>
          </div>
          <div className={styles.memoryOverviewItem}>
            <span>{t("agentConfig.memoryBackgroundTasks")}</span>
            <strong>{workerStatusLabel}</strong>
            <small>{queueHint}</small>
          </div>
          <div className={styles.memoryOverviewItem}>
            <span>{t("agentConfig.memoryPendingTurns")}</span>
            <strong>
              {autoMemoryStatus
                ? autoMemoryStatus.enabled
                  ? autoMemoryStatus.pending_turns
                  : t("agentConfig.memoryStatusDisabled")
                : "—"}
            </strong>
            <small>
              {autoMemoryStatus?.enabled
                ? t("agentConfig.memoryPendingTurnsHint", {
                    sessions: autoMemoryStatus.sessions_with_pending,
                    interval: autoMemoryStatus.interval,
                  })
                : t("agentConfig.memoryAutoRecordDisabledHint")}
            </small>
          </div>
          <div
            className={`${styles.memoryOverviewItem} ${styles.memoryOverviewMaintenance}`}
          >
            <div>
              <span>⚠️ {t("agentConfig.memoryMaintenanceEyebrow")}</span>
              <strong>{t("agentConfig.memoryMaintenanceTitle")}</strong>
              <small>{t("agentConfig.memoryMaintenanceDescription")}</small>
            </div>
            <Button onClick={rebuildMemoryIndex} loading={reindexing}>
              {t("agentConfig.rebuildMemoryIndex")}
            </Button>
          </div>
        </div>
      </section>

      <div className={styles.memoryConfigGrid}>
        <section className={styles.memoryConfigPanel}>
          <div className={styles.memorySectionHeader}>
            <div
              className={`${styles.memorySectionIcon} ${styles.memorySectionIconPrimary}`}
            >
              01
            </div>
            <div>
              <h3>{t("agentConfig.memoryJournalTitle")}</h3>
              <p>{t("agentConfig.memoryJournalDescription")}</p>
            </div>
          </div>

          <div className={styles.memoryCapabilityHeader}>
            <h4>{t("agentConfig.memoryConversationJournalTitle")}</h4>
            <code>auto-memory</code>
          </div>
          <div className={styles.memoryToggleRow}>
            <div>
              <strong>{t("agentConfig.memoryAutoRecordTitle")}</strong>
              <span>{t("agentConfig.memoryAutoRecordDescription")}</span>
            </div>
            <Switch checked={autoMemoryEnabled} onChange={toggleAutoMemory} />
          </div>

          <Form.Item
            label={t("agentConfig.memoryAutoRecordFrequency")}
            name={["reme_light_memory_config", "auto_memory_interval"]}
            rules={[
              {
                required: true,
                message: t("agentConfig.autoMemoryIntervalRequired"),
              },
              {
                type: "number",
                min: 0,
                message: t("agentConfig.autoMemoryIntervalMin"),
              },
            ]}
            tooltip={t("agentConfig.autoMemoryIntervalTooltip")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={autoMemoryEnabled ? 1 : 0}
              step={1}
              disabled={!autoMemoryEnabled}
              placeholder={t("agentConfig.autoMemoryIntervalPlaceholder")}
            />
          </Form.Item>

          <div className={styles.memoryToggleRow}>
            <div>
              <strong>{t("agentConfig.memoryNotifyTitle")}</strong>
              <span>{t("agentConfig.memoryNotifyDescription")}</span>
            </div>
            <Form.Item
              name={[
                "reme_light_memory_config",
                "auto_memory_inbox_push_enabled",
              ]}
              initialValue
              valuePropName="checked"
              noStyle
            >
              <Switch />
            </Form.Item>
          </div>

          <div className={styles.memoryCapabilityDivider} />
          <div className={styles.memoryCapabilityHeader}>
            <div className={styles.memoryCapabilityTitleRow}>
              <h4>{t("agentConfig.memoryExternalSourcesTitle")}</h4>
              <span className={styles.memoryDevelopingBadge}>
                {t("agentConfig.memoryExternalSourcesDevelopingLabel")}
              </span>
            </div>
          </div>

          <div className={styles.memorySourceCard}>
            <div className={styles.memorySourceHeader}>
              <button
                type="button"
                className={styles.memorySourceToggle}
                aria-expanded={dailyPaperExpanded}
                onClick={() => setDailyPaperExpanded((expanded) => !expanded)}
              >
                <span
                  className={`${styles.memorySourceChevron} ${
                    dailyPaperExpanded ? styles.memorySourceChevronExpanded : ""
                  }`}
                  aria-hidden="true"
                >
                  ›
                </span>
                <span>
                  <strong>{t("agentConfig.memoryDailyPaperTitle")}</strong>
                  <small>{t("agentConfig.memoryDailyPaperDescription")}</small>
                </span>
              </button>
              <div className={styles.memorySourceActions}>
                <a href={dailyPaperDocsUrl} target="_blank" rel="noreferrer">
                  {t("agentConfig.dailyPaperDocumentation")}
                  <span aria-hidden="true">↗</span>
                </a>
                <code>daily-paper</code>
                <Form.Item
                  name={[
                    "reme_light_memory_config",
                    "daily_paper_cron_enabled",
                  ]}
                  valuePropName="checked"
                  noStyle
                >
                  <Switch
                    onChange={(enabled) => {
                      if (enabled) setDailyPaperExpanded(true);
                    }}
                  />
                </Form.Item>
              </div>
            </div>

            {dailyPaperExpanded && (
              <div className={styles.memorySourceContent}>
                <Form.Item
                  label={t("agentConfig.dailyPaperCron")}
                  name={["reme_light_memory_config", "daily_paper_cron"]}
                  tooltip={t("agentConfig.dailyPaperCronTooltip")}
                  rules={
                    dailyPaperCronEnabled
                      ? [
                          {
                            required: true,
                            whitespace: true,
                            message: t("agentConfig.dailyPaperCronRequired"),
                          },
                          {
                            validator: (_, value?: string) => {
                              if (
                                !value?.trim() ||
                                isValidDreamCronShape(value)
                              ) {
                                return Promise.resolve();
                              }
                              return Promise.reject(
                                new Error(
                                  t("agentConfig.dailyPaperCronInvalid"),
                                ),
                              );
                            },
                          },
                        ]
                      : []
                  }
                >
                  <Input
                    disabled={!dailyPaperCronEnabled}
                    placeholder={t("agentConfig.dailyPaperCronPlaceholder")}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.dailyPaperTopics")}
                  name={["reme_light_memory_config", "daily_paper_topics"]}
                  tooltip={t("agentConfig.dailyPaperTopicsTooltip")}
                >
                  <Input
                    disabled={!dailyPaperCronEnabled}
                    placeholder={t("agentConfig.dailyPaperTopicsPlaceholder")}
                  />
                </Form.Item>

                <div className={styles.memoryToggleRow}>
                  <div>
                    <strong>{t("agentConfig.dailyPaperUseHfMirror")}</strong>
                    <span>
                      {t("agentConfig.dailyPaperUseHfMirrorDescription")}
                    </span>
                  </div>
                  <Form.Item
                    name={[
                      "reme_light_memory_config",
                      "daily_paper_use_hf_mirror",
                    ]}
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch disabled={!dailyPaperCronEnabled} />
                  </Form.Item>
                </div>

                <div className={styles.memoryToggleRow}>
                  <div>
                    <strong>{t("agentConfig.memoryNotifyTitle")}</strong>
                    <span>{t("agentConfig.dailyPaperNotifyDescription")}</span>
                  </div>
                  <Form.Item
                    name={[
                      "reme_light_memory_config",
                      "daily_paper_inbox_push_enabled",
                    ]}
                    initialValue
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch />
                  </Form.Item>
                </div>
              </div>
            )}
          </div>
        </section>

        <div className={styles.memoryConfigStack}>
          <section className={styles.memoryConfigPanel}>
            <div className={styles.memorySectionHeader}>
              <div
                className={`${styles.memorySectionIcon} ${styles.memorySectionIconSecondary}`}
              >
                02
              </div>
              <div>
                <h3>{t("agentConfig.memoryOrganizeSectionTitle")}</h3>
                <p>{t("agentConfig.memoryOrganizeSectionDescription")}</p>
              </div>
            </div>

            <div className={styles.memoryCapabilityHeader}>
              <h4>{t("agentConfig.memoryOrganizeTitle")}</h4>
              <code>auto-dream</code>
            </div>
            <div className={styles.memoryToggleRow}>
              <div>
                <strong>{t("agentConfig.memoryScheduledOrganizeTitle")}</strong>
                <span>
                  {t("agentConfig.memoryScheduledOrganizeDescription")}
                </span>
              </div>
              <Form.Item
                name={["reme_light_memory_config", "dream_cron_enabled"]}
                valuePropName="checked"
                noStyle
              >
                <Switch />
              </Form.Item>
            </div>
            <Form.Item
              label={t("agentConfig.dreamCron")}
              name={["reme_light_memory_config", "dream_cron"]}
              tooltip={t("agentConfig.dreamCronTooltip")}
              rules={
                dreamCronEnabled
                  ? [
                      {
                        required: true,
                        whitespace: true,
                        message: t("agentConfig.dreamCronRequired"),
                      },
                      {
                        validator: (_, value?: string) => {
                          if (!value?.trim() || isValidDreamCronShape(value)) {
                            return Promise.resolve();
                          }
                          return Promise.reject(
                            new Error(t("agentConfig.dreamCronInvalid")),
                          );
                        },
                      },
                    ]
                  : []
              }
            >
              <Input
                disabled={!dreamCronEnabled}
                placeholder={t("agentConfig.dreamCronPlaceholder")}
              />
            </Form.Item>
            <div className={styles.memoryToggleRow}>
              <div>
                <strong>{t("agentConfig.memoryNotifyTitle")}</strong>
                <span>{t("agentConfig.autoDreamNotifyDescription")}</span>
              </div>
              <Form.Item
                name={[
                  "reme_light_memory_config",
                  "auto_dream_inbox_push_enabled",
                ]}
                initialValue
                valuePropName="checked"
                noStyle
              >
                <Switch />
              </Form.Item>
            </div>
          </section>

          <section className={styles.memoryRecallPanel}>
            <div className={styles.memorySectionHeader}>
              <div
                className={`${styles.memorySectionIcon} ${styles.memorySectionIconTertiary}`}
              >
                03
              </div>
              <div>
                <h3>{t("agentConfig.memorySearchSectionTitle")}</h3>
                <p>{t("agentConfig.memorySearchSectionDescription")}</p>
              </div>
            </div>
            <div className={styles.memoryCapabilityHeader}>
              <h4>{t("agentConfig.memoryRecallTitle")}</h4>
              <code>memory-search</code>
            </div>
            <div className={styles.memoryToggleRow}>
              <div>
                <strong>{t("agentConfig.memorySearchToolTitle")}</strong>
                <span>{t("agentConfig.memorySearchToolDescription")}</span>
              </div>
              <Form.Item
                name={["reme_light_memory_config", "memory_search_enabled"]}
                initialValue
                valuePropName="checked"
                noStyle
              >
                <Switch />
              </Form.Item>
            </div>
            <div className={styles.memoryToggleRow}>
              <div>
                <strong>{t("agentConfig.memoryAutoRecallTitle")}</strong>
                <span>{t("agentConfig.memoryAutoRecallDescription")}</span>
              </div>
              <Form.Item
                name={[
                  "reme_light_memory_config",
                  "auto_memory_search_config",
                  "enabled",
                ]}
                initialValue={false}
                valuePropName="checked"
                noStyle
              >
                <Switch />
              </Form.Item>
            </div>
            <div className={styles.memorySettingRow}>
              <div>
                <strong>
                  {t("agentConfig.autoMaxResults")}
                  <span className={styles.memoryRequiredMark}>*</span>
                </strong>
                <span>{t("agentConfig.autoMaxResultsTooltip")}</span>
              </div>
              <Form.Item
                className={styles.memoryInlineField}
                name={[
                  "reme_light_memory_config",
                  "auto_memory_search_config",
                  "max_results",
                ]}
                rules={[
                  {
                    required: true,
                    message: t("agentConfig.autoMaxResultsRequired"),
                  },
                  {
                    type: "number",
                    min: 1,
                    message: t("agentConfig.autoMaxResultsMin"),
                  },
                ]}
              >
                <InputNumber
                  style={{ width: "100%" }}
                  min={1}
                  step={1}
                  disabled={!autoSearchEnabled}
                />
              </Form.Item>
            </div>
          </section>
        </div>
      </div>

      <Modal
        open={statusOpen}
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
        onCancel={() => setStatusOpen(false)}
        footer={
          <div className={styles.memoryStatusModalFooter}>
            <Button onClick={inspectMemoryStatus} loading={statusLoading}>
              {t("common.refresh")}
            </Button>
            <Button type="primary" onClick={() => setStatusOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        }
      >
        {statusLoading && !memoryStatus ? (
          <div className={styles.memoryStatusLoading}>
            <Spin />
            <span>{t("agentConfig.remeStatusLoading")}</span>
          </div>
        ) : statusError ? (
          <Alert
            type="error"
            showIcon
            message={t("agentConfig.remeStatusFailed")}
            description={statusError}
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
          </div>
        ) : null}
      </Modal>
    </Card>
  );
}
