import { Card, Form, InputNumber, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface LlmRetryCardProps {
  llmRetryEnabled?: boolean;
}

export function LlmRetryCard({ llmRetryEnabled = true }: LlmRetryCardProps) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.llmRetryTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        name="llm_retry_enabled"
        label={t("agentConfig.llmRetryEnabled")}
        valuePropName="checked"
        tooltip={t("agentConfig.llmRetryEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <div className={styles.llmRetryRow}>
        <Form.Item
          label={t("agentConfig.llmMaxRetries")}
          name="llm_max_retries"
          rules={[
            {
              required: true,
              message: t("agentConfig.llmMaxRetriesRequired"),
            },
            {
              type: "number",
              min: 1,
              message: t("agentConfig.llmMaxRetriesMin"),
            },
          ]}
          tooltip={t("agentConfig.llmMaxRetriesTooltip")}
          className={styles.llmRetryField}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={1}
            disabled={!llmRetryEnabled}
            placeholder={t("agentConfig.llmMaxRetriesPlaceholder")}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.llmBackoffBase")}
          name="llm_backoff_base"
          rules={[
            {
              required: true,
              message: t("agentConfig.llmBackoffBaseRequired"),
            },
            {
              type: "number",
              min: 0.1,
              message: t("agentConfig.llmBackoffBaseMin"),
            },
          ]}
          tooltip={t("agentConfig.llmBackoffBaseTooltip")}
          className={styles.llmRetryField}
        >
          <InputNumber
            style={{ width: "100%" }}
            step={0.1}
            disabled={!llmRetryEnabled}
            placeholder={t("agentConfig.llmBackoffBasePlaceholder")}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.llmBackoffCap")}
          name="llm_backoff_cap"
          dependencies={["llm_backoff_base"]}
          rules={[
            {
              required: true,
              message: t("agentConfig.llmBackoffCapRequired"),
            },
            {
              type: "number",
              min: 0.5,
              message: t("agentConfig.llmBackoffCapMin"),
            },
            {
              validator: async (_, value) => {
                const backoffBase = form.getFieldValue("llm_backoff_base");
                if (
                  typeof value !== "number" ||
                  typeof backoffBase !== "number" ||
                  value >= backoffBase
                ) {
                  return;
                }
                throw new Error(t("agentConfig.llmBackoffCapGteBase"));
              },
            },
          ]}
          tooltip={t("agentConfig.llmBackoffCapTooltip")}
          className={styles.llmRetryField}
        >
          <InputNumber
            style={{ width: "100%" }}
            step={0.5}
            disabled={!llmRetryEnabled}
            placeholder={t("agentConfig.llmBackoffCapPlaceholder")}
          />
        </Form.Item>
      </div>
    </Card>
  );
}
