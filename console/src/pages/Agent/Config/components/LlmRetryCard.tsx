import { RetryTimeline } from "./RuntimeVisuals";
import { NumberStepper as InputNumber } from "@/components/interaction/NumberStepper";
import { SettingsField } from "@/components/interaction/SettingsField";
import { Card, Form, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface LlmRetryCardProps {
  llmRetryEnabled?: boolean;
}

export function LlmRetryCard({ llmRetryEnabled = true }: LlmRetryCardProps) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();

  return (
    <Card className={styles.formCard} title={t("agentConfig.llmRetryTitle")}>
      <SettingsField
        name="llm_retry_enabled"
        label={t("agentConfig.llmRetryEnabled")}
        valuePropName="checked"
        tooltip={t("agentConfig.llmRetryEnabledTooltip")}
      >
        <Switch />
      </SettingsField>

      <RetryTimeline enabled={llmRetryEnabled} />
      <div className={styles.llmRetryRow}>
        <SettingsField
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
            style={{ width: "100%", maxWidth: 240 }}
            min={1}
            step={1}
            disabled={!llmRetryEnabled}
            placeholder={t("agentConfig.llmMaxRetriesPlaceholder")}
          />
        </SettingsField>

        <SettingsField
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
            style={{ width: "100%", maxWidth: 240 }}
            step={0.1}
            disabled={!llmRetryEnabled}
            placeholder={t("agentConfig.llmBackoffBasePlaceholder")}
          />
        </SettingsField>

        <SettingsField
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
            style={{ width: "100%", maxWidth: 240 }}
            step={0.5}
            disabled={!llmRetryEnabled}
            placeholder={t("agentConfig.llmBackoffCapPlaceholder")}
          />
        </SettingsField>
      </div>
    </Card>
  );
}
