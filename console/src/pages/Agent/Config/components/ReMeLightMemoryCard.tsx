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
import { SliderWithValue } from "./SliderWithValue";
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
        label={t("agentConfig.summarizeInterval")}
        name={["reme_light_memory_config", "summarize_interval"]}
        tooltip={t("agentConfig.summarizeIntervalTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1}
          step={1}
          placeholder={t("agentConfig.summarizeIntervalPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.dreamCron")}
        name={["reme_light_memory_config", "dream_cron"]}
        tooltip={t("agentConfig.dreamCronTooltip")}
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
        label={t("agentConfig.recursiveFileWatcher")}
        name={["reme_light_memory_config", "recursive_file_watcher"]}
        valuePropName="checked"
        tooltip={t("agentConfig.recursiveFileWatcherTooltip")}
      >
        <Switch />
      </Form.Item>

      <Collapse
        items={[
          {
            key: "forceMemorySearch",
            label: t("agentConfig.forceMemorySearchCollapseLabel"),
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.forceMemorySearch")}
                  name={[
                    "reme_light_memory_config",
                    "force_memory_search_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.forceMemorySearchTooltip")}
                >
                  <Switch />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.forceMaxResults")}
                  name={[
                    "reme_light_memory_config",
                    "force_memory_search_config",
                    "max_results",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.forceMaxResultsRequired"),
                    },
                    {
                      type: "number",
                      min: 1,
                      message: t("agentConfig.forceMaxResultsMin"),
                    },
                  ]}
                  tooltip={t("agentConfig.forceMaxResultsTooltip")}
                >
                  <InputNumber style={{ width: "100%" }} min={1} step={1} />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.forceMinScore")}
                  name={[
                    "reme_light_memory_config",
                    "force_memory_search_config",
                    "min_score",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.forceMinScoreRequired"),
                    },
                  ]}
                  tooltip={t("agentConfig.forceMinScoreTooltip")}
                >
                  <SliderWithValue
                    min={0}
                    max={1}
                    step={0.05}
                    marks={{ 0: "0", 0.5: "0.5", 1: "1" }}
                  />
                </Form.Item>
              </>
            ),
          },
          {
            key: "embeddingConfig",
            label: t("agentConfig.embeddingConfigCollapseLabel"),
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