import {
  Form,
  Card,
  Switch,
  InputNumber,
  Input,
  Collapse,
  Alert,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function ReMeLightMemoryCard() {
  const { t } = useTranslation();

  const baseUrl = Form.useWatch([
    "reme_light_memory_config",
    "embedding_model_config",
    "base_url",
  ]);
  const modelName = Form.useWatch([
    "reme_light_memory_config",
    "embedding_model_config",
    "model_name",
  ]);
  const embeddingEnabled = !!(baseUrl?.trim() && modelName?.trim());

  const rerankerEnabled = Form.useWatch([
    "reme_light_memory_config",
    "reranker_config",
    "enabled",
  ]);

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.remeLightMemoryTitle")}
    >
      <Form.Item
        label={t("agentConfig.summarizeWhenCompact")}
        name={["reme_light_memory_config", "summarize_when_compact"]}
        valuePropName="checked"
        tooltip={t("agentConfig.summarizeWhenCompactTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoMemoryInterval")}
        name={["reme_light_memory_config", "auto_memory_interval"]}
        tooltip={t("agentConfig.autoMemoryIntervalTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1}
          step={1}
          placeholder={t("agentConfig.autoMemoryIntervalPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.dreamCron")}
        name={["reme_light_memory_config", "dream_cron"]}
        tooltip={t("agentConfig.dreamCronTooltip")}
        normalize={(value) => value ?? ""}
      >
        <Input placeholder={t("agentConfig.dreamCronPlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.rebuildMemoryIndexOnStart")}
        name={["reme_light_memory_config", "rebuild_memory_index_on_start"]}
        valuePropName="checked"
        tooltip={t("agentConfig.rebuildMemoryIndexOnStartTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.enableSearchRawLog")}
        name={["reme_light_memory_config", "enable_search_raw_log"]}
        valuePropName="checked"
        tooltip={t("agentConfig.enableSearchRawLogTooltip")}
      >
        <Switch />
      </Form.Item>

      <Collapse
        items={[
          {
            key: "autoMemorySearch",
            label: t("agentConfig.autoMemorySearchCollapseLabel"),
            forceRender: true,
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.autoMemorySearch")}
                  name={[
                    "reme_light_memory_config",
                    "auto_memory_search_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.autoMemorySearchTooltip")}
                >
                  <Switch />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.autoMaxResults")}
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
                  tooltip={t("agentConfig.autoMaxResultsTooltip")}
                >
                  <InputNumber style={{ width: "100%" }} min={1} step={1} />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.autoMemorySearchPersistToContext")}
                  name={[
                    "reme_light_memory_config",
                    "auto_memory_search_config",
                    "persist_to_context",
                  ]}
                  valuePropName="checked"
                  tooltip={t(
                    "agentConfig.autoMemorySearchPersistToContextTooltip",
                  )}
                >
                  <Switch />
                </Form.Item>
              </>
            ),
          },
          {
            key: "rerankerConfig",
            label: t("agentConfig.rerankerConfigCollapseLabel"),
            forceRender: true,
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.rerankerEnabled")}
                  name={[
                    "reme_light_memory_config",
                    "reranker_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.rerankerEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>

                {rerankerEnabled && (
                  <>
                    <Form.Item
                      label={t("agentConfig.rerankerModelName")}
                      name={[
                        "reme_light_memory_config",
                        "reranker_config",
                        "model_name",
                      ]}
                      tooltip={t("agentConfig.rerankerModelNameTooltip")}
                    >
                      <Input
                        placeholder={t(
                          "agentConfig.rerankerModelNamePlaceholder",
                        )}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.rerankerBaseUrl")}
                      name={[
                        "reme_light_memory_config",
                        "reranker_config",
                        "base_url",
                      ]}
                      tooltip={t("agentConfig.rerankerBaseUrlTooltip")}
                    >
                      <Input
                        placeholder={t(
                          "agentConfig.rerankerBaseUrlPlaceholder",
                        )}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.rerankerApiKey")}
                      name={[
                        "reme_light_memory_config",
                        "reranker_config",
                        "api_key",
                      ]}
                      tooltip={t("agentConfig.rerankerApiKeyTooltip")}
                    >
                      <Input.Password
                        placeholder={t("agentConfig.rerankerApiKeyPlaceholder")}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.rerankerTemperature")}
                      name={[
                        "reme_light_memory_config",
                        "reranker_config",
                        "temperature",
                      ]}
                      tooltip={t("agentConfig.rerankerTemperatureTooltip")}
                    >
                      <InputNumber
                        style={{ width: "100%" }}
                        min={0}
                        max={2}
                        step={0.1}
                        placeholder={t(
                          "agentConfig.rerankerTemperaturePlaceholder",
                        )}
                      />
                    </Form.Item>

                    <Alert
                      type="info"
                      showIcon
                      message={t("agentConfig.rerankerInfoHint")}
                    />
                  </>
                )}
              </>
            ),
          },
          {
            key: "embeddingConfig",
            label: t("agentConfig.embeddingConfigCollapseLabel"),
            forceRender: true,
            children: (
              <>
                <Alert
                  type="warning"
                  showIcon
                  message={`${t("agentConfig.embeddingEnableHint")} ${t(
                    "agentConfig.embeddingRestartWarning",
                  )}`}
                  style={{ marginBottom: 16 }}
                />

                <Form.Item
                  label={t("agentConfig.embeddingBaseUrl")}
                  name={[
                    "reme_light_memory_config",
                    "embedding_model_config",
                    "base_url",
                  ]}
                  tooltip={t("agentConfig.embeddingBaseUrlTooltip")}
                >
                  <Input
                    placeholder={t("agentConfig.embeddingBaseUrlPlaceholder")}
                  />
                </Form.Item>

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
                    disabled={!embeddingEnabled}
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
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
