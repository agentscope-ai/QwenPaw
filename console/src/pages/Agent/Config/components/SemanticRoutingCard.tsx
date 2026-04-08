import { Form, Card, Switch, Alert } from "@agentscope-ai/design";
import { Slider } from "antd";
import { useTranslation } from "react-i18next";
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
            <Slider min={1} max={50} />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.semanticRoutingMinScore")}
            name={["semantic_routing", "min_score"]}
            tooltip={t("agentConfig.semanticRoutingMinScoreTooltip")}
          >
            <Slider min={0} max={1} step={0.05} />
          </Form.Item>
        </>
      )}
    </Card>
  );
}
