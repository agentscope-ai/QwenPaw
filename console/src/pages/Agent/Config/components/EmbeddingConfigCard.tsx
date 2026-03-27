import {
  Form,
  Card,
  Switch,
  InputNumber,
  Input,
  Alert,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function EmbeddingConfigCard() {
  const { t } = useTranslation();

  const baseUrl = Form.useWatch(["embedding_config", "base_url"]);
  const modelName = Form.useWatch(["embedding_config", "model_name"]);
  const embeddingEnabled = !!(baseUrl?.trim() && modelName?.trim());

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.embeddingConfigTitle")}
      style={{ marginTop: 16 }}
    >
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
        name={["embedding_config", "base_url"]}
        tooltip={t("agentConfig.embeddingBaseUrlTooltip")}
      >
        <Input placeholder={t("agentConfig.embeddingBaseUrlPlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingModelName")}
        name={["embedding_config", "model_name"]}
        tooltip={t("agentConfig.embeddingModelNameTooltip")}
      >
        <Input placeholder={t("agentConfig.embeddingModelNamePlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingApiKey")}
        name={["embedding_config", "api_key"]}
        tooltip={t("agentConfig.embeddingApiKeyTooltip")}
      >
        <Input.Password
          placeholder={t("agentConfig.embeddingApiKeyPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingDimensions")}
        name={["embedding_config", "dimensions"]}
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
        name={["embedding_config", "enable_cache"]}
        valuePropName="checked"
        tooltip={t("agentConfig.embeddingEnableCacheTooltip")}
      >
        <Switch disabled={!embeddingEnabled} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.embeddingMaxCacheSize")}
        name={["embedding_config", "max_cache_size"]}
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
        name={["embedding_config", "max_input_length"]}
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
        name={["embedding_config", "max_batch_size"]}
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
    </Card>
  );
}
