import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { BadgeCheck, ChevronRight, Cpu, Database, Power } from "lucide-react";

import { api, agentsApi } from "@/api";
import type { EmbeddingModelConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import {
  getEmbeddingConfigFingerprint,
  isEmbeddingEnabled,
} from "./embeddingUtils";
import styles from "../index.module.less";
import { useMemoryMaintenance } from "../memoryMaintenanceContext";
import { useEmbeddingVerification } from "./useEmbeddingVerification";

const EMBEDDING_BACKEND_OPTIONS = [
  { value: "openai", label: "OpenAI" },
  { value: "dashscope", label: "DashScope" },
  { value: "dashscope_multimodal", label: "DashScope Multimodal" },
  { value: "gemini", label: "Gemini" },
  { value: "ollama", label: "Ollama" },
];

export function EmbeddingModelCard() {
  const { t } = useTranslation();
  const { message, modal } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const form = Form.useFormInstance();
  const {
    needsReindex,
    setNeedsReindex,
    reindexing,
    setReindexing,
    persistedEmbeddingFingerprint,
    setPersistedEmbeddingFingerprint,
    runtimeStatus,
    checkMemoryStatus,
  } = useMemoryMaintenance();

  const embeddingConfig = Form.useWatch(
    ["reme_light_memory_config", "embedding_model_config"],
    form,
  ) as EmbeddingModelConfig | undefined;
  const backend = embeddingConfig?.backend ?? "openai";
  const modelName = embeddingConfig?.model_name ?? "";
  const apiKey = embeddingConfig?.api_key ?? "";
  const normalizedBackend = String(backend);
  const showApiKey = normalizedBackend !== "ollama";
  const showBaseUrl = normalizedBackend !== "gemini";
  const baseUrlIsHost = normalizedBackend === "ollama";
  const embeddingEnabled = isEmbeddingEnabled({
    backend,
    model_name: modelName,
    api_key: apiKey,
  });
  const {
    testingEmbedding,
    setTestingEmbedding,
    testedEmbedding,
    testedEmbeddingIsCurrent,
    markVerified,
    clearVerification,
  } = useEmbeddingVerification(embeddingConfig, embeddingEnabled);
  const embeddingCacheEnabled = embeddingConfig?.enable_cache ?? true;
  const hasUnsavedEmbeddingChanges =
    persistedEmbeddingFingerprint !== undefined &&
    getEmbeddingConfigFingerprint(embeddingConfig) !==
      persistedEmbeddingFingerprint;
  const undoEmbeddingAvailable =
    needsReindex &&
    runtimeStatus.type === "healthy" &&
    runtimeStatus.data.embedding_reindex_undo_available;

  const rebuildEmbeddingIndex = () => {
    modal.confirm({
      title: t("agentConfig.rebuildEmbeddingIndexConfirmTitle"),
      content: t("agentConfig.rebuildEmbeddingIndexConfirm"),
      okText: t("agentConfig.rebuildEmbeddingIndex"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        setReindexing(true);
        try {
          await agentsApi.rebuildMemoryIndex(
            selectedAgent || "default",
            "embedding",
          );
          setNeedsReindex(false);
          message.success(t("agentConfig.rebuildEmbeddingIndexSuccess"));
        } catch (error) {
          message.error(
            t("agentConfig.rebuildEmbeddingIndexFailed", {
              error: error instanceof Error ? error.message : String(error),
            }),
          );
          throw error;
        } finally {
          setReindexing(false);
          void checkMemoryStatus();
        }
      },
    });
  };

  const undoEmbeddingChange = () => {
    modal.confirm({
      title: t("agentConfig.undoEmbeddingChangeConfirmTitle"),
      content: t("agentConfig.undoEmbeddingChangeConfirm"),
      okText: t("agentConfig.undoEmbeddingChange"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        setReindexing(true);
        try {
          const result = await agentsApi.undoEmbeddingReindex(
            selectedAgent || "default",
          );
          form.setFieldValue(
            ["reme_light_memory_config", "embedding_model_config"],
            result,
          );
          setPersistedEmbeddingFingerprint?.(
            getEmbeddingConfigFingerprint(result),
          );
          setNeedsReindex(false);
          message.success(t("agentConfig.undoEmbeddingChangeSuccess"));
        } catch (error) {
          message.error(
            t("agentConfig.undoEmbeddingChangeFailed", {
              error: error instanceof Error ? error.message : String(error),
            }),
          );
          throw error;
        } finally {
          setReindexing(false);
          void checkMemoryStatus();
        }
      },
    });
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
        markVerified(
          result.actual_dimensions ?? config.dimensions,
          result.latency_ms,
        );
        modal.success({
          title: t("agentConfig.embeddingTestSuccess"),
          content: t("agentConfig.embeddingTestSuccessDetail", {
            dimensions: result.actual_dimensions,
            latency: result.latency_ms,
          }),
        });
      } else {
        clearVerification();
        modal.error({
          title: t("agentConfig.embeddingTestFailed"),
          content: result.message,
        });
      }
    } catch (error) {
      clearVerification();
      modal.error({
        title: t("agentConfig.embeddingTestFailed"),
        content: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setTestingEmbedding(false);
    }
  };

  return (
    <Card className={styles.formCard}>
      <section className={styles.memoryOverview}>
        <div className={styles.memoryOverviewHeader}>
          <div>
            <h3>{t("agentConfig.embeddingOverviewTitle")}</h3>
            <p>{t("agentConfig.embeddingStatusDescription")}</p>
          </div>
        </div>

        <div className={styles.memoryOverviewGrid}>
          <div className={styles.memoryOverviewItem}>
            <span className={styles.memoryOverviewLabel}>
              <Power size={14} aria-hidden="true" />
              {t("agentConfig.embeddingConfigStatus")}
            </span>
            <strong
              className={
                embeddingEnabled
                  ? styles.embeddingStatusValueEnabled
                  : styles.embeddingStatusValueDisabled
              }
            >
              <i />
              {t(
                embeddingEnabled
                  ? "agentConfig.embeddingCapabilityEnabled"
                  : "agentConfig.embeddingCapabilityDisabled",
              )}
            </strong>
            <small>
              {t(
                !embeddingEnabled
                  ? "agentConfig.embeddingSearchModeBm25"
                  : needsReindex
                  ? "agentConfig.embeddingSearchModeBm25Pending"
                  : "agentConfig.embeddingSearchModeHybrid",
              )}
            </small>
          </div>
          <div className={styles.memoryOverviewItem}>
            <span className={styles.memoryOverviewLabel}>
              <Cpu size={14} aria-hidden="true" />
              {t("agentConfig.embeddingCurrentModel")}
            </span>
            <strong title={modelName}>{modelName || "—"}</strong>
            <small>
              {normalizedBackend || "—"}
              {embeddingConfig?.dimensions
                ? ` · ${embeddingConfig.dimensions} ${t(
                    "agentConfig.embeddingDimensionsUnit",
                  )}`
                : ""}
            </small>
          </div>
          <button
            type="button"
            className={`${styles.memoryOverviewItem} ${styles.memoryOverviewClickableItem} ${styles.embeddingVerificationAction}`}
            onClick={testEmbedding}
            disabled={!embeddingEnabled || testingEmbedding}
            aria-busy={testingEmbedding}
            aria-label={t("agentConfig.embeddingTestConnection")}
          >
            <span className={styles.memoryOverviewLabel}>
              <BadgeCheck size={14} aria-hidden="true" />
              {t("agentConfig.embeddingVerificationStatus")}
            </span>
            {testedEmbeddingIsCurrent && testedEmbedding ? (
              <>
                <strong className={styles.embeddingStatusValueVerified}>
                  {t("agentConfig.embeddingVerified")}
                </strong>
                <small>
                  {t("agentConfig.embeddingVerificationMetrics", {
                    dimensions: testedEmbedding.dimensions,
                    latency: testedEmbedding.latency,
                  })}
                </small>
              </>
            ) : (
              <>
                <strong className={styles.embeddingStatusValuePending}>
                  {t("agentConfig.embeddingNotVerified")}
                </strong>
                <small>{t("agentConfig.embeddingVerificationHint")}</small>
              </>
            )}
            <ChevronRight size={16} aria-hidden="true" />
          </button>
          <div
            className={`${styles.embeddingIndexItem} ${
              !embeddingEnabled
                ? styles.embeddingIndexDisabled
                : reindexing || hasUnsavedEmbeddingChanges
                ? styles.embeddingIndexRebuildRequired
                : needsReindex
                ? styles.embeddingIndexRebuildRequired
                : styles.embeddingIndexReady
            }`}
          >
            <button
              type="button"
              className={`${styles.memoryOverviewItem} ${styles.memoryOverviewClickableItem} ${styles.embeddingIndexPrimaryAction}`}
              onClick={rebuildEmbeddingIndex}
              disabled={
                !embeddingEnabled || reindexing || hasUnsavedEmbeddingChanges
              }
              aria-busy={reindexing}
              aria-label={t("agentConfig.rebuildEmbeddingIndex")}
            >
              <span className={styles.memoryOverviewLabel}>
                <Database size={14} aria-hidden="true" />
                {t("agentConfig.embeddingIndexStatus")}
              </span>
              <strong
                className={
                  !embeddingEnabled
                    ? styles.embeddingStatusValueDisabled
                    : reindexing || hasUnsavedEmbeddingChanges
                    ? styles.embeddingStatusValuePending
                    : needsReindex
                    ? styles.embeddingStatusValuePending
                    : styles.embeddingStatusValueVerified
                }
              >
                {t(
                  !embeddingEnabled
                    ? "agentConfig.embeddingIndexDisabled"
                    : reindexing
                    ? "agentConfig.embeddingIndexRebuilding"
                    : hasUnsavedEmbeddingChanges
                    ? "agentConfig.embeddingIndexSaveFirst"
                    : needsReindex
                    ? "agentConfig.embeddingIndexNeedsRebuild"
                    : "agentConfig.embeddingIndexAvailable",
                )}
              </strong>
              <small
                title={t(
                  !embeddingEnabled
                    ? "agentConfig.embeddingIndexEnableFirst"
                    : reindexing
                    ? "agentConfig.embeddingIndexRebuildingHint"
                    : hasUnsavedEmbeddingChanges
                    ? "agentConfig.embeddingIndexUnsavedHint"
                    : needsReindex
                    ? "agentConfig.rebuildMemoryIndexRequired"
                    : "agentConfig.embeddingIndexReady",
                )}
              >
                {t(
                  !embeddingEnabled
                    ? "agentConfig.embeddingIndexEnableFirst"
                    : reindexing
                    ? "agentConfig.embeddingIndexRebuildingHint"
                    : hasUnsavedEmbeddingChanges
                    ? "agentConfig.embeddingIndexUnsavedHint"
                    : needsReindex
                    ? "agentConfig.embeddingIndexBm25Fallback"
                    : "agentConfig.embeddingIndexMatchesConfig",
                )}
              </small>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
            {undoEmbeddingAvailable && (
              <button
                type="button"
                className={styles.embeddingIndexUndoAction}
                disabled={reindexing}
                onClick={undoEmbeddingChange}
              >
                {t("agentConfig.undoEmbeddingChange")}
              </button>
            )}
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
              <h3>{t("agentConfig.embeddingServiceTitle")}</h3>
              <p>{t("agentConfig.embeddingServiceDescription")}</p>
            </div>
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
              disabled={reindexing}
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
                disabled={reindexing}
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
              disabled={reindexing}
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
                disabled={reindexing}
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
              <Switch disabled={reindexing || !embeddingEnabled} />
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
              disabled={reindexing || !embeddingEnabled}
            />
          </Form.Item>
        </section>

        <section className={styles.memoryConfigPanel}>
          <div className={styles.memorySectionHeader}>
            <div
              className={`${styles.memorySectionIcon} ${styles.memorySectionIconSecondary}`}
            >
              02
            </div>
            <div>
              <h3>{t("agentConfig.embeddingIndexTitle")}</h3>
              <p>{t("agentConfig.embeddingIndexDescription")}</p>
            </div>
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
            <Switch disabled={reindexing || !embeddingEnabled} />
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
              disabled={
                reindexing || !embeddingEnabled || !embeddingCacheEnabled
              }
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
              disabled={reindexing || !embeddingEnabled}
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
              disabled={reindexing || !embeddingEnabled}
            />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.embeddingHealthCheckTimeout")}
            name={[
              "reme_light_memory_config",
              "embedding_model_config",
              "health_check_timeout",
            ]}
            rules={[
              {
                required: true,
                message: t("agentConfig.embeddingHealthCheckTimeoutRequired"),
              },
            ]}
            tooltip={t("agentConfig.embeddingHealthCheckTimeoutTooltip")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={1}
              max={300}
              step={5}
              addonAfter="s"
              disabled={reindexing || !embeddingEnabled}
            />
          </Form.Item>
        </section>
      </div>
    </Card>
  );
}
