import { useState } from "react";
import { Form, Card, Switch, InputNumber, Input } from "@agentscope-ai/design";
import {
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  Gauge,
  HeartPulse,
  ListTodo,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api";
import type { ReMeLightMemoryConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import styles from "../index.module.less";
import { useMemoryMaintenance } from "../memoryMaintenanceContext";
import { ReMeStatusModal } from "./ReMeStatusModal";

export function isValidDreamCronShape(value?: string) {
  if (!value?.trim()) {
    return false;
  }
  const fields = value.trim().split(/\s+/);
  if (
    fields.length !== 5 ||
    !fields.every((field) => /^[a-z0-9*/,-]+$/i.test(field))
  ) {
    return false;
  }

  // Catch numeric values outside the ranges accepted by APScheduler before
  // submitting the form. The backend remains authoritative for the complete
  // cron grammar (named months/weekdays, ranges, lists, and steps).
  const numericRanges = [
    [0, 59],
    [0, 23],
    [1, 31],
    [1, 12],
    [0, 6],
  ] as const;
  return fields.every((field, index) => {
    const [minimum, maximum] = numericRanges[index];
    return [...field.matchAll(/\d+/g)].every(({ 0: token }) => {
      const number = Number(token);
      return number >= minimum && number <= maximum;
    });
  });
}

export function ReMeLightMemoryCard() {
  const { t, i18n } = useTranslation();
  const { message, modal } = useAppMessage();
  const form = Form.useFormInstance();
  const { selectedAgent } = useAgentStore();
  const {
    reindexing,
    setReindexing,
    runtimeStatus,
    diagnosticsStatus,
    checkMemoryStatus,
  } = useMemoryMaintenance();
  const [statusView, setStatusView] = useState<"tasks" | "diagnostics" | null>(
    null,
  );
  const [dailyPaperExpanded, setDailyPaperExpanded] = useState(false);

  const rebuildMemoryIndex = () => {
    modal.confirm({
      title: t("agentConfig.rebuildBm25IndexConfirmTitle"),
      content: t("agentConfig.rebuildBm25IndexConfirm"),
      okText: t("agentConfig.rebuildBm25Index"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        setReindexing(true);
        try {
          await agentsApi.rebuildMemoryIndex(
            selectedAgent || "default",
            "bm25",
          );
          message.success(t("agentConfig.rebuildBm25IndexSuccess"));
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error);
          message.error(
            t("agentConfig.rebuildMemoryIndexFailed", { error: detail }),
          );
          throw error;
        } finally {
          setReindexing(false);
          void checkMemoryStatus();
        }
      },
    });
  };

  const inspectMemoryStatus = (view: "tasks" | "diagnostics") => {
    setStatusView(view);
    void checkMemoryStatus(view === "diagnostics");
  };
  const statusLoading = runtimeStatus.type === "checking";
  const runtime = runtimeStatus.type === "healthy" ? runtimeStatus.data : null;
  const diagnostics =
    diagnosticsStatus.type === "healthy" ? diagnosticsStatus.data : null;
  const statusError =
    runtimeStatus.type === "error" ? runtimeStatus.message : "";
  const diagnosticsError =
    diagnosticsStatus.type === "error" ? diagnosticsStatus.message : "";
  const backendStatus = runtime?.worker.status;
  const statusBadgeType =
    backendStatus === "error"
      ? "error"
      : backendStatus === "busy" ||
        backendStatus === "stopping" ||
        runtime?.reindexing
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
      : backendStatus === "busy" || runtime?.reindexing
      ? t("agentConfig.memoryStatusBusy")
      : backendStatus === "stopping"
      ? t("agentConfig.memoryStatusStopping")
      : statusBadge.label;

  const workerStatusLabel = backendStatus
    ? t(`agentConfig.memoryWorkerStatus.${backendStatus}`)
    : "—";
  const queueHint = runtime
    ? t("agentConfig.memoryQueueSummary", {
        running: runtime.worker.tasks_running,
        pending: runtime.worker.queue_pending,
      })
    : "—";
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
          </div>
        </div>
        <div className={styles.memoryOverviewGrid}>
          <div
            className={`${styles.memoryOverviewItem} ${styles.memoryServiceStatusItem}`}
          >
            <span className={styles.memoryOverviewLabel}>
              <HeartPulse size={14} aria-hidden="true" />
              {t("agentConfig.memoryRuntimeStatus")}
            </span>
            <div className={styles.memoryServiceStatusLine}>
              <strong
                className={`${styles.memoryStatusBadge} ${statusBadge.className}`}
              >
                <i />
                {statusBadgeLabel}
              </strong>
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

          <button
            type="button"
            className={`${styles.memoryOverviewItem} ${styles.memoryOverviewClickableItem}`}
            onClick={() => inspectMemoryStatus("tasks")}
          >
            <span className={styles.memoryOverviewLabel}>
              <ListTodo size={14} aria-hidden="true" />
              {t("agentConfig.memoryBackgroundTasks")}
            </span>
            <strong>{workerStatusLabel}</strong>
            <small>{queueHint}</small>
            <ChevronRight size={16} aria-hidden="true" />
          </button>

          <button
            type="button"
            className={`${styles.memoryOverviewItem} ${styles.memoryOverviewClickableItem}`}
            onClick={() => inspectMemoryStatus("diagnostics")}
          >
            <span className={styles.memoryOverviewLabel}>
              <Gauge size={14} aria-hidden="true" />
              {t("agentConfig.memoryDiagnostics")}
            </span>
            <div className={styles.memoryOverviewMetrics}>
              <div>
                <small>{t("agentConfig.memoryComponentsMetric")}</small>
                <strong>{diagnostics?.components_total ?? "—"}</strong>
              </div>
              <div>
                <small>{t("agentConfig.memoryProcessMetric")}</small>
                <strong>{diagnostics?.process_rss ?? "—"}</strong>
              </div>
            </div>
            <small>{t("agentConfig.memoryDiagnosticsHint")}</small>
            <ChevronRight size={16} aria-hidden="true" />
          </button>

          <button
            type="button"
            className={`${styles.memoryOverviewItem} ${styles.memoryOverviewClickableItem} ${styles.memoryOverviewMaintenance}`}
            onClick={rebuildMemoryIndex}
            disabled={reindexing}
            aria-busy={reindexing}
          >
            <div>
              <span>
                <AlertTriangle size={14} aria-hidden="true" />
                {t("agentConfig.memoryMaintenanceEyebrow")}
              </span>
              <strong>{t("agentConfig.rebuildBm25Index")}</strong>
              <small>{t("agentConfig.rebuildBm25IndexDescription")}</small>
            </div>
            <ChevronRight size={16} aria-hidden="true" />
          </button>
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
                  <ChevronRight size={18} />
                </span>
                <span>
                  <strong>{t("agentConfig.memoryDailyPaperTitle")}</strong>
                  <small>{t("agentConfig.memoryDailyPaperDescription")}</small>
                </span>
              </button>
              <div className={styles.memorySourceActions}>
                <a href={dailyPaperDocsUrl} target="_blank" rel="noreferrer">
                  {t("agentConfig.dailyPaperDocumentation")}
                  <ExternalLink size={14} aria-hidden="true" />
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

      <ReMeStatusModal
        view={statusView}
        loading={
          statusView === "diagnostics"
            ? diagnosticsStatus.type === "checking"
            : statusLoading
        }
        error={statusView === "diagnostics" ? diagnosticsError : statusError}
        runtime={runtime}
        diagnostics={diagnostics}
        statusBadge={statusBadge}
        statusBadgeLabel={statusBadgeLabel}
        onRefresh={() => void checkMemoryStatus(statusView === "diagnostics")}
        onClose={() => setStatusView(null)}
      />
    </Card>
  );
}
