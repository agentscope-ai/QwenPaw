import { useCallback, useEffect, useRef, useState } from "react";
import {
  Form,
  Card,
  Switch,
  InputNumber,
  Input,
  Alert,
  Select,
  Button,
  Modal,
} from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import { api, agentsApi } from "@/api";
import type { ReMeMemoryStatusResponse } from "@/api/modules/agents";
import type {
  EmbeddingModelConfig,
  ReMeLightMemoryConfig,
} from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import styles from "../index.module.less";

// Keep in sync with src/qwenpaw/agents/memory/reme_config.py
// _OPENAI_COMPAT_EMBEDDING_BACKENDS.
const OPENAI_COMPAT_EMBEDDING_BACKENDS = new Set([
  "openai",
  "dashscope",
  "dashscope_multimodal",
]);

const EMBEDDING_BACKEND_OPTIONS = [
  { value: "openai", label: "OpenAI" },
  { value: "dashscope", label: "DashScope" },
  { value: "dashscope_multimodal", label: "DashScope Multimodal" },
  { value: "gemini", label: "Gemini" },
  { value: "ollama", label: "Ollama" },
];

type RuntimeStatus =
  | { type: "unknown" }
  | { type: "checking" }
  | { type: "healthy"; data: ReMeMemoryStatusResponse }
  | { type: "error"; message: string };

export function isEmbeddingEnabled(config?: Partial<EmbeddingModelConfig>) {
  if (!config?.model_name?.trim()) {
    return false;
  }
  // Mirror reme_config.py::_is_embedding_enabled so the form previews the
  // same capability state that the backend will apply after saving.
  if (OPENAI_COMPAT_EMBEDDING_BACKENDS.has(config.backend || "")) {
    return !!config.api_key?.trim();
  }
  if (config.backend === "gemini") {
    return !!config.api_key?.trim();
  }
  return config.backend === "ollama";
}

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

export function getEmbeddingServiceFingerprint(
  config?: Partial<EmbeddingModelConfig>,
) {
  if (!config) return "";
  return JSON.stringify([
    config.backend || "",
    config.api_key || "",
    config.base_url?.trim().replace(/\/+$/, "") || "",
    config.model_name?.trim() || "",
    config.dimensions || 0,
    !!config.use_dimensions,
  ]);
}

export function getDailyCronTime(value?: string) {
  const match = value?.trim().match(/^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$/);
  if (!match) return null;
  const minute = Number(match[1]);
  const hour = Number(match[2]);
  if (minute > 59 || hour > 23) return null;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function ReMeLightMemoryCard() {
  const { t } = useTranslation();
  const { message, modal } = useAppMessage();
  const form = Form.useFormInstance();
  const { selectedAgent } = useAgentStore();
  const [reindexing, setReindexing] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>({
    type: "unknown",
  });
  const statusRequestRef = useRef<AbortController | null>(null);
  const [testingEmbedding, setTestingEmbedding] = useState(false);
  const [testedEmbedding, setTestedEmbedding] = useState<{
    fingerprint: string;
    dimensions: number;
    latency: number;
  } | null>(null);

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
      if (openModal) {
        setStatusOpen(true);
      }

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
  }[runtimeStatus.type];

  const remeConfig = Form.useWatch(["reme_light_memory_config"], form) as
    | ReMeLightMemoryConfig
    | undefined;
  const embeddingConfig = remeConfig?.embedding_model_config;
  const watchedEmbeddingBackend = Form.useWatch(
    ["reme_light_memory_config", "embedding_model_config", "backend"],
    form,
  ) as string | undefined;
  const watchedEmbeddingModelName = Form.useWatch(
    ["reme_light_memory_config", "embedding_model_config", "model_name"],
    form,
  ) as string | undefined;
  const watchedEmbeddingApiKey = Form.useWatch(
    ["reme_light_memory_config", "embedding_model_config", "api_key"],
    form,
  ) as string | undefined;
  const backend =
    watchedEmbeddingBackend ?? embeddingConfig?.backend ?? "openai";
  const modelName =
    watchedEmbeddingModelName ?? embeddingConfig?.model_name ?? "";
  const apiKey = watchedEmbeddingApiKey ?? embeddingConfig?.api_key ?? "";
  const autoMemoryInterval = Number(remeConfig?.auto_memory_interval ?? 0);
  const autoMemoryEnabled = autoMemoryInterval > 0;
  const dreamCronEnabled = remeConfig?.dream_cron_enabled ?? true;
  const dreamCron = remeConfig?.dream_cron || "";
  const autoSearchEnabled =
    remeConfig?.auto_memory_search_config?.enabled ?? false;
  const autoSearchMaxResults =
    remeConfig?.auto_memory_search_config?.max_results ?? 0;
  const normalizedBackend = String(backend);
  const showApiKey = normalizedBackend !== "ollama";
  const showBaseUrl = normalizedBackend !== "gemini";
  const baseUrlIsHost = normalizedBackend === "ollama";
  const embeddingEnabled = isEmbeddingEnabled({
    backend,
    model_name: modelName,
    api_key: apiKey,
  });
  const embeddingCacheEnabled = embeddingConfig?.enable_cache ?? true;
  const testedEmbeddingIsCurrent =
    testedEmbedding?.fingerprint ===
    getEmbeddingServiceFingerprint(embeddingConfig);
  const dailyDreamTime = getDailyCronTime(dreamCron);
  const dreamScheduleSummary = !dreamCronEnabled
    ? t("agentConfig.memoryStatusDisabled")
    : dailyDreamTime
    ? t("agentConfig.memoryStatusDailyAt", { time: dailyDreamTime })
    : dreamCron;
  const embeddingStatusSummary = embeddingEnabled
    ? t("agentConfig.memoryStatusEmbeddingEnabled", {
        model: modelName,
        dimensions: embeddingConfig?.dimensions,
      })
    : t("agentConfig.memoryStatusEmbeddingDisabled");

  const toggleAutoMemory = (enabled: boolean) => {
    form.setFieldValue(
      ["reme_light_memory_config", "auto_memory_interval"],
      enabled ? Math.max(autoMemoryInterval, 1) : 0,
    );
  };

  const testEmbedding = async () => {
    const config = form.getFieldValue([
      "reme_light_memory_config",
      "embedding_model_config",
    ]) as EmbeddingModelConfig | undefined;
    if (
      !config ||
      !isEmbeddingEnabled(config) ||
      !Number.isInteger(config.dimensions) ||
      config.dimensions < 1
    ) {
      modal.error({
        title: t("agentConfig.embeddingTestFailed"),
        content: t("agentConfig.embeddingTestIncomplete"),
      });
      return;
    }

    setTestingEmbedding(true);
    try {
      const result = await api.testEmbedding(config);
      if (result.success) {
        setTestedEmbedding({
          fingerprint: getEmbeddingServiceFingerprint(config),
          dimensions: result.actual_dimensions ?? config.dimensions,
          latency: result.latency_ms,
        });
        modal.success({
          title: t("agentConfig.embeddingTestSuccess"),
          content: t("agentConfig.embeddingTestSuccessDetail", {
            dimensions: result.actual_dimensions,
            latency: result.latency_ms,
          }),
        });
      } else {
        setTestedEmbedding(null);
        modal.error({
          title: t("agentConfig.embeddingTestFailed"),
          content: result.message,
        });
      }
    } catch (error) {
      setTestedEmbedding(null);
      modal.error({
        title: t("agentConfig.embeddingTestFailed"),
        content: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setTestingEmbedding(false);
    }
  };

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.remeLightMemoryTitle")}
    >
      <p className={styles.memoryPageDescription}>
        {t("agentConfig.memoryPageDescription")}
      </p>
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

      <section className={styles.memoryOverview}>
        <div className={styles.memoryOverviewHeader}>
          <div>
            <span className={styles.memoryOverviewEyebrow}>
              {t("agentConfig.memoryOverviewEyebrow")}
            </span>
            <h3>{t("agentConfig.memoryOverviewTitle")}</h3>
          </div>
          <div className={styles.memoryOverviewActions}>
            <span
              className={`${styles.memoryStatusBadge} ${statusBadge.className}`}
            >
              <span />
              {statusBadge.label}
            </span>
            <Button
              className={styles.memoryStatusButton}
              onClick={inspectMemoryStatus}
              loading={statusLoading}
            >
              {t("agentConfig.remeStatusView")}
            </Button>
          </div>
        </div>
        <div className={styles.memoryOverviewGrid}>
          <div className={styles.memoryOverviewItem}>
            <span>{t("agentConfig.memoryStatusAutoRecord")}</span>
            <strong>
              {autoMemoryEnabled
                ? t("agentConfig.memoryStatusEveryTurns", {
                    count: autoMemoryInterval,
                  })
                : t("agentConfig.memoryStatusDisabled")}
            </strong>
          </div>
          <div className={styles.memoryOverviewItem}>
            <span>{t("agentConfig.memoryStatusScheduled")}</span>
            <strong>{dreamScheduleSummary}</strong>
          </div>
          <div className={styles.memoryOverviewItem}>
            <span>{t("agentConfig.memoryStatusRecall")}</span>
            <strong>
              {autoSearchEnabled
                ? t("agentConfig.memoryStatusMaxResults", {
                    count: autoSearchMaxResults,
                  })
                : t("agentConfig.memoryStatusDisabled")}
            </strong>
          </div>
          <div className={styles.memoryOverviewItem}>
            <span>{t("agentConfig.memoryStatusSemantic")}</span>
            <strong>{embeddingStatusSummary}</strong>
          </div>
        </div>
      </section>

      <div className={styles.memoryConfigGrid}>
        <section className={styles.memoryConfigPanel}>
          <div className={styles.memorySectionHeader}>
            <div className={styles.memorySectionIcon}>01</div>
            <div>
              <h3>{t("agentConfig.memoryGenerationTitle")}</h3>
              <p>{t("agentConfig.memoryGenerationDescription")}</p>
            </div>
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
              <strong>{t("agentConfig.memoryCompactExtractTitle")}</strong>
              <span>{t("agentConfig.memoryCompactExtractDescription")}</span>
            </div>
            <Form.Item
              name={["reme_light_memory_config", "summarize_when_compact"]}
              valuePropName="checked"
              noStyle
            >
              <Switch />
            </Form.Item>
          </div>

          <div className={styles.memoryToggleRow}>
            <div>
              <strong>{t("agentConfig.memoryNotifyTitle")}</strong>
              <span>{t("agentConfig.memoryNotifyDescription")}</span>
            </div>
            <Form.Item
              name={["reme_light_memory_config", "inbox_push_enabled"]}
              valuePropName="checked"
              noStyle
            >
              <Switch />
            </Form.Item>
          </div>
        </section>

        <div className={styles.memoryConfigStack}>
          <section className={styles.memoryConfigPanel}>
            <div className={styles.memorySectionHeader}>
              <div className={styles.memorySectionIcon}>02</div>
              <div>
                <h3>{t("agentConfig.memoryOrganizeTitle")}</h3>
                <p>{t("agentConfig.memoryOrganizeDescription")}</p>
              </div>
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
              className={styles.memoryCronField}
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
          </section>

          <section className={styles.memoryRecallPanel}>
            <div className={styles.memorySectionHeader}>
              <div className={styles.memorySectionIcon}>03</div>
              <div>
                <h3>{t("agentConfig.memoryRecallTitle")}</h3>
                <p>{t("agentConfig.memoryRecallDescription")}</p>
              </div>
            </div>
            <div className={styles.memoryRecallControls}>
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
            </div>
          </section>
        </div>
      </div>

      <section className={styles.memoryEmbeddingSection}>
        <div className={styles.memoryEmbeddingHeader}>
          <div className={styles.memorySectionHeader}>
            <div className={styles.memorySectionIcon}>04</div>
            <div>
              <h3>
                {t("agentConfig.embeddingConfigCollapseLabel")}
                <span className={styles.memoryOptionalBadge}>
                  {t("agentConfig.memoryOptional")}
                </span>
              </h3>
              <p>{t("agentConfig.memoryEmbeddingDescription")}</p>
            </div>
          </div>
          <span
            className={
              embeddingEnabled
                ? styles.memorySearchModeActive
                : styles.memorySearchModeInactive
            }
          >
            <i /> {embeddingStatusSummary}
          </span>
        </div>
        <Alert
          type="info"
          showIcon
          message={`${t("agentConfig.embeddingEnableHint")} ${t(
            "agentConfig.embeddingRestartWarning",
          )}`}
          className={styles.embeddingNotice}
        />
        <div className={styles.embeddingGrid}>
          <section className={styles.embeddingPanel}>
            <div className={styles.embeddingPanelHeader}>
              <div>
                <h4>{t("agentConfig.embeddingServiceTitle")}</h4>
                <p>{t("agentConfig.embeddingServiceDescription")}</p>
              </div>
              <span
                className={`${styles.embeddingPanelBadge} ${
                  embeddingEnabled
                    ? styles.embeddingCapabilityEnabled
                    : styles.embeddingCapabilityDisabled
                }`}
              >
                {t(
                  embeddingEnabled
                    ? "agentConfig.embeddingCapabilityEnabled"
                    : "agentConfig.embeddingCapabilityDisabled",
                )}
              </span>
            </div>

            <Form.Item
              label={t("agentConfig.embeddingBackend")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "backend",
              ]}
              tooltip={t("agentConfig.embeddingBackendTooltip")}
            >
              <Select
                options={EMBEDDING_BACKEND_OPTIONS}
                placeholder={t("agentConfig.embeddingBackendPlaceholder")}
                style={{ width: "100%" }}
              />
            </Form.Item>

            {showBaseUrl && (
              <Form.Item
                label={
                  baseUrlIsHost
                    ? t("agentConfig.embeddingHost")
                    : t("agentConfig.embeddingBaseUrl")
                }
                name={[
                  "reme_light_memory_config",
                  "embedding_model_config",
                  "base_url",
                ]}
                tooltip={
                  baseUrlIsHost
                    ? t("agentConfig.embeddingHostTooltip")
                    : t("agentConfig.embeddingBaseUrlTooltip")
                }
              >
                <Input
                  placeholder={
                    baseUrlIsHost
                      ? t("agentConfig.embeddingHostPlaceholder")
                      : t("agentConfig.embeddingBaseUrlPlaceholder")
                  }
                />
              </Form.Item>
            )}

            <Form.Item
              label={t("agentConfig.embeddingModelName")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "model_name",
              ]}
              tooltip={t("agentConfig.embeddingModelNameTooltip")}
            >
              <Input
                placeholder={t("agentConfig.embeddingModelNamePlaceholder")}
              />
            </Form.Item>

            {showApiKey && (
              <Form.Item
                label={t("agentConfig.embeddingApiKey")}
                name={[
                  "reme_light_memory_config",
                  "embedding_model_config",
                  "api_key",
                ]}
                tooltip={t("agentConfig.embeddingApiKeyTooltip")}
              >
                <Input.Password
                  placeholder={t("agentConfig.embeddingApiKeyPlaceholder")}
                />
              </Form.Item>
            )}

            {normalizedBackend === "openai" && (
              <Form.Item
                label={t("agentConfig.embeddingUseDimensions")}
                name={[
                  "reme_light_memory_config",
                  "embedding_model_config",
                  "use_dimensions",
                ]}
                valuePropName="checked"
                tooltip={t("agentConfig.embeddingUseDimensionsTooltip")}
              >
                <Switch disabled={!embeddingEnabled} />
              </Form.Item>
            )}

            <Form.Item
              label={t("agentConfig.embeddingDimensions")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "dimensions",
              ]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.embeddingDimensionsRequired"),
                },
                {
                  type: "number",
                  min: 1,
                  message: t("agentConfig.embeddingDimensionsMin"),
                },
              ]}
              tooltip={t("agentConfig.embeddingDimensionsTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                step={256}
                disabled={!embeddingEnabled}
              />
            </Form.Item>

            <div className={styles.embeddingTestRow}>
              <Button onClick={testEmbedding} loading={testingEmbedding}>
                {t("agentConfig.embeddingTestConnection")}
              </Button>
              {testedEmbeddingIsCurrent && testedEmbedding && (
                <span className={styles.embeddingVerified}>
                  <span className={styles.embeddingVerifiedDot} />
                  {t("agentConfig.embeddingTestVerified", {
                    dimensions: testedEmbedding.dimensions,
                    latency: testedEmbedding.latency,
                  })}
                </span>
              )}
            </div>
          </section>

          <section className={styles.embeddingPanel}>
            <div className={styles.embeddingPanelHeader}>
              <div>
                <h4>{t("agentConfig.embeddingIndexTitle")}</h4>
                <p>{t("agentConfig.embeddingIndexDescription")}</p>
              </div>
              <span
                className={`${styles.embeddingPanelBadge} ${styles.embeddingAdvancedBadge}`}
              >
                {t("agentConfig.embeddingAdvancedBadge")}
              </span>
            </div>

            <Form.Item
              label={t("agentConfig.embeddingEnableCache")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "enable_cache",
              ]}
              valuePropName="checked"
              tooltip={t("agentConfig.embeddingEnableCacheTooltip")}
            >
              <Switch disabled={!embeddingEnabled} />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.embeddingMaxCacheSize")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "max_cache_size",
              ]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.embeddingMaxCacheSizeRequired"),
                },
              ]}
              tooltip={t("agentConfig.embeddingMaxCacheSizeTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                step={100}
                disabled={!embeddingEnabled || !embeddingCacheEnabled}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.embeddingMaxInputLength")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "max_input_length",
              ]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.embeddingMaxInputLengthRequired"),
                },
              ]}
              tooltip={t("agentConfig.embeddingMaxInputLengthTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                step={1024}
                disabled={!embeddingEnabled}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.embeddingMaxBatchSize")}
              name={[
                "reme_light_memory_config",
                "embedding_model_config",
                "max_batch_size",
              ]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.embeddingMaxBatchSizeRequired"),
                },
              ]}
              tooltip={t("agentConfig.embeddingMaxBatchSizeTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                step={1}
                disabled={!embeddingEnabled}
              />
            </Form.Item>
          </section>
        </div>
      </section>

      <section className={styles.memoryMaintenancePanel}>
        <div>
          <span className={styles.memoryMaintenanceEyebrow}>
            {t("agentConfig.memoryMaintenanceEyebrow")}
          </span>
          <h3>{t("agentConfig.memoryMaintenanceTitle")}</h3>
          <p>{t("agentConfig.memoryMaintenanceDescription")}</p>
        </div>
        <Button onClick={rebuildMemoryIndex} loading={reindexing}>
          {t("agentConfig.rebuildMemoryIndex")}
        </Button>
      </section>

      <Modal
        open={statusOpen}
        width={680}
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
