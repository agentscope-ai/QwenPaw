import {
  Form,
  Card,
  Switch,
  InputNumber,
  Input,
  Collapse,
  Alert,
  Select,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
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

export function isEmbeddingEnabled(
  backend: string,
  modelName?: string,
  apiKey?: string,
) {
  if (!modelName?.trim()) {
    return false;
  }
  // Keep enablement aligned with AgentScope credential requirements.
  if (OPENAI_COMPAT_EMBEDDING_BACKENDS.has(backend)) {
    return !!apiKey?.trim();
  }
  if (backend === "gemini") {
    return !!apiKey?.trim();
  }
  return backend === "ollama";
}

export function ReMeLightMemoryCard() {
  const { t } = useTranslation();

  const backend =
    Form.useWatch([
      "reme_light_memory_config",
      "embedding_model_config",
      "backend",
    ]) || "openai";
  const apiKey = Form.useWatch([
    "reme_light_memory_config",
    "embedding_model_config",
    "api_key",
  ]);
  const modelName = Form.useWatch([
    "reme_light_memory_config",
    "embedding_model_config",
    "model_name",
  ]);
  const normalizedBackend = String(backend);
  const showApiKey = normalizedBackend !== "ollama";
  const showBaseUrl = normalizedBackend !== "gemini";
  const baseUrlIsHost = normalizedBackend === "ollama";
  const embeddingEnabled = isEmbeddingEnabled(
    normalizedBackend,
    modelName,
    apiKey,
  );

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
          min={0}
          step={1}
          placeholder={t("agentConfig.autoMemoryIntervalPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.rebuildMemoryIndexOnStart")}
        name={["reme_light_memory_config", "rebuild_memory_index_on_start"]}
        valuePropName="checked"
        tooltip={t("agentConfig.rebuildMemoryIndexOnStartTooltip")}
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
