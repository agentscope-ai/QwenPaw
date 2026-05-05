import {
  Form,
  Card,
  Switch,
  Alert,
  Input,
  InputNumber,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

export function SemanticRoutingCard() {
  const { t } = useTranslation();
  const enabled = Form.useWatch(["semantic_routing", "enabled"]) ?? false;

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.semanticRoutingTitle")}
      style={{ marginTop: 16 }}
    >
      <Alert
        type="info"
        showIcon
        message={t("agentConfig.semanticRoutingHint")}
        style={{ marginBottom: 16 }}
      />

      <Form.Item
        label={t("agentConfig.semanticRoutingEnabled")}
        name={["semantic_routing", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.semanticRoutingEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      {enabled && (
        <>
          <Form.Item
            label={t("agentConfig.semanticRoutingTopK")}
            name={["semantic_routing", "top_k"]}
            tooltip={t("agentConfig.semanticRoutingTopKTooltip")}
          >
            <SliderWithValue min={1} max={50} />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.semanticRoutingMinScore")}
            name={["semantic_routing", "min_score"]}
            tooltip={t("agentConfig.semanticRoutingMinScoreTooltip")}
          >
            <SliderWithValue min={0} max={1} step={0.05} />
          </Form.Item>

          <div style={{ margin: "16px 0 8px", fontWeight: 500 }}>
            {t("agentConfig.semanticRoutingEmbeddingTitle")}
          </div>

          <Alert
            type="info"
            showIcon
            message={t("agentConfig.semanticRoutingEmbeddingHint")}
            style={{ marginBottom: 16 }}
          />

          <Form.Item
            label={t("agentConfig.semanticRoutingEmbeddingBaseUrl")}
            name={[
              "semantic_routing",
              "embedding_model_config",
              "base_url",
            ]}
            tooltip={t("agentConfig.semanticRoutingEmbeddingBaseUrlTooltip")}
          >
            <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.semanticRoutingEmbeddingModelName")}
            name={[
              "semantic_routing",
              "embedding_model_config",
              "model_name",
            ]}
            tooltip={t("agentConfig.semanticRoutingEmbeddingModelNameTooltip")}
          >
            <Input placeholder="text-embedding-v3" />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.semanticRoutingEmbeddingApiKey")}
            name={[
              "semantic_routing",
              "embedding_model_config",
              "api_key",
            ]}
            tooltip={t("agentConfig.semanticRoutingEmbeddingApiKeyTooltip")}
          >
            <Input.Password placeholder={t("agentConfig.semanticRoutingEmbeddingApiKeyPlaceholder")} />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.semanticRoutingEmbeddingDimensions")}
            name={[
              "semantic_routing",
              "embedding_model_config",
              "dimensions",
            ]}
            tooltip={t("agentConfig.semanticRoutingEmbeddingDimensionsTooltip")}
          >
            <InputNumber min={1} max={4096} style={{ width: "100%" }} />
          </Form.Item>
        </>
      )}
    </Card>
  );
}
