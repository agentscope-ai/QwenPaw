import { NumberStepper as InputNumber } from "@/components/interaction/NumberStepper";
import { SettingsField } from "@/components/interaction/SettingsField";
import { Card, Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

const RL_PAUSE_FIELD = "llm_rate_limit_pause";
const RL_JITTER_FIELD = "llm_rate_limit_jitter";
const RL_MAX_QPM_FIELD = "llm_max_qpm";

export function LlmRateLimiterCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.llmRateLimiterTitle")}
    >
      <div className={styles.numericGrid}>
        <SettingsField
          label={t("agentConfig.llmMaxConcurrent")}
          name="llm_max_concurrent"
          rules={[
            {
              required: true,
              message: t("agentConfig.llmMaxConcurrentRequired"),
            },
            {
              type: "number",
              min: 1,
              message: t("agentConfig.llmMaxConcurrentRange"),
            },
          ]}
          tooltip={t("agentConfig.llmMaxConcurrentTooltip")}
        >
          <InputNumber
            style={{ width: "100%", maxWidth: 240 }}
            min={1}
            step={1}
            placeholder={t("agentConfig.llmMaxConcurrentPlaceholder")}
          />
        </SettingsField>

        <SettingsField
          label={t("agentConfig.llmMaxQpm")}
          name={RL_MAX_QPM_FIELD}
          rules={[
            {
              required: true,
              message: t("agentConfig.llmMaxQpmRequired"),
            },
            {
              type: "number",
              min: 0,
              message: t("agentConfig.llmMaxQpmRange"),
            },
          ]}
          tooltip={t("agentConfig.llmMaxQpmTooltip")}
        >
          <InputNumber
            style={{ width: "100%", maxWidth: 240 }}
            min={0}
            step={10}
            placeholder={t("agentConfig.llmMaxQpmPlaceholder")}
          />
        </SettingsField>

        <SettingsField
          label={t("agentConfig.llmRateLimitPause")}
          name="llm_rate_limit_pause"
          rules={[
            {
              required: true,
              message: t("agentConfig.llmRateLimitPauseRequired"),
            },
            {
              type: "number",
              min: 1.0,
              message: t("agentConfig.llmRateLimitPauseMin"),
            },
          ]}
          tooltip={t("agentConfig.llmRateLimitPauseTooltip")}
        >
          <InputNumber
            style={{ width: "100%", maxWidth: 240 }}
            step={0.5}
            placeholder={t("agentConfig.llmRateLimitPausePlaceholder")}
          />
        </SettingsField>

        <SettingsField
          label={t("agentConfig.llmRateLimitJitter")}
          name="llm_rate_limit_jitter"
          rules={[
            {
              required: true,
              message: t("agentConfig.llmRateLimitJitterRequired"),
            },
            {
              type: "number",
              min: 0.0,
              message: t("agentConfig.llmRateLimitJitterMin"),
            },
          ]}
          tooltip={t("agentConfig.llmRateLimitJitterTooltip")}
        >
          <InputNumber
            style={{ width: "100%", maxWidth: 240 }}
            step={0.5}
            placeholder={t("agentConfig.llmRateLimitJitterPlaceholder")}
          />
        </SettingsField>

        <SettingsField
          label={t("agentConfig.llmAcquireTimeout")}
          name="llm_acquire_timeout"
          dependencies={[RL_PAUSE_FIELD, RL_JITTER_FIELD]}
          rules={[
            {
              required: true,
              message: t("agentConfig.llmAcquireTimeoutRequired"),
            },
            {
              type: "number",
              min: 10.0,
              message: t("agentConfig.llmAcquireTimeoutMin"),
            },
            {
              validator: async (_, value) => {
                const pause = form.getFieldValue(RL_PAUSE_FIELD);
                const jitter = form.getFieldValue(RL_JITTER_FIELD);
                if (
                  typeof value !== "number" ||
                  typeof pause !== "number" ||
                  typeof jitter !== "number" ||
                  value > pause + jitter
                ) {
                  return;
                }
                throw new Error(
                  t("agentConfig.llmAcquireTimeoutGtPauseJitter"),
                );
              },
            },
          ]}
          tooltip={t("agentConfig.llmAcquireTimeoutTooltip")}
        >
          <InputNumber
            style={{ width: "100%", maxWidth: 240 }}
            step={10}
            placeholder={t("agentConfig.llmAcquireTimeoutPlaceholder")}
          />
        </SettingsField>
      </div>
    </Card>
  );
}
