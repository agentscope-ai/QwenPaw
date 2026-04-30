import { Alert, Form, Input, InputNumber, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

type EmbeddingModelConfigFieldsProps = {
  showRestartAlert?: boolean;
  namePath?: string[];
};

export function EmbeddingModelConfigFields({
  showRestartAlert = true,
  namePath = ["reme_light_memory_config", "embedding_model_config"],
}: EmbeddingModelConfigFieldsProps) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();

  const baseUrl = Form.useWatch([...namePath, "base_url"], form);
  const modelName = Form.useWatch([...namePath, "model_name"], form);
  const embeddingEnabled = !!(baseUrl?.trim() && modelName?.trim());

  return (
    <>
      {showRestartAlert ? (
        <Alert
          type="warning"
          showIcon
          message={`${t("agentConfig.embeddingEnableHint")} ${t(
            "agentConfig.embeddingRestartWarning",
          )}`}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Form.Item
        label={t("agentConfig.embeddingBaseUrl")}
        name={[...namePath, "base_url"]}
        tooltip={t("agentConfig.embeddingBaseUrlTooltip")}
      >
        <Input placeholder={t("agentConfig.embeddingBaseUrlPlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingModelName")}
        name={[...namePath, "model_name"]}
        tooltip={t("agentConfig.embeddingModelNameTooltip")}
      >
        <Input placeholder={t("agentConfig.embeddingModelNamePlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingApiKey")}
        name={[...namePath, "api_key"]}
        tooltip={t("agentConfig.embeddingApiKeyTooltip")}
      >
        <Form.Item noStyle shouldUpdate>
          {({ getFieldValue }) => {
            const apiKeyConfigured = !!getFieldValue([...namePath, "api_key_configured"]);
            if (apiKeyConfigured) {
              return (
                <Input
                  type="password"
                  autoComplete="new-password"
                  placeholder={t("agentConfig.embeddingApiKeyConfiguredPlaceholder")}
                />
              );
            }
            return <Input.Password placeholder={t("agentConfig.embeddingApiKeyPlaceholder")} />;
          }}
        </Form.Item>
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingDimensions")}
        name={[...namePath, "dimensions"]}
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
        name={[...namePath, "enable_cache"]}
        valuePropName="checked"
        tooltip={t("agentConfig.embeddingEnableCacheTooltip")}
      >
        <Switch disabled={!embeddingEnabled} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingMaxCacheSize")}
        name={[...namePath, "max_cache_size"]}
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
        name={[...namePath, "max_input_length"]}
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
        name={[...namePath, "max_batch_size"]}
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
  );
}