import { Form, Card, Switch, InputNumber } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

export function ToolResultCompactCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.toolResultCompactTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.toolResultCompactEnabled")}
        name={["tool_result_compact", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.toolResultCompactEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.toolResultCompactRecentN")}
        name={["tool_result_compact", "recent_n"]}
        rules={[
          {
            required: true,
            message: t("agentConfig.toolResultCompactRecentNRequired"),
          },
        ]}
        tooltip={t("agentConfig.toolResultCompactRecentNTooltip")}
      >
        <SliderWithValue
          min={1}
          max={10}
          step={1}
          marks={{ 1: "1", 5: "5", 10: "10" }}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.toolResultCompactOldThreshold")}
        name={["tool_result_compact", "old_max_bytes"]}
        rules={[
          {
            required: true,
            message: t("agentConfig.toolResultCompactOldThresholdRequired"),
          },
        ]}
        tooltip={t("agentConfig.toolResultCompactOldThresholdTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={100}
          step={100}
          placeholder={t(
            "agentConfig.toolResultCompactOldThresholdPlaceholder",
          )}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.toolResultCompactRecentThreshold")}
        name={["tool_result_compact", "recent_max_bytes"]}
        dependencies={[["tool_result_compact", "old_max_bytes"]]}
        rules={[
          {
            required: true,
            message: t("agentConfig.toolResultCompactRecentThresholdRequired"),
          },
          {
            validator: async (_, value) => {
              const oldMaxBytes = form.getFieldValue([
                "tool_result_compact",
                "old_max_bytes",
              ]);
              if (
                typeof value !== "number" ||
                typeof oldMaxBytes !== "number" ||
                value > oldMaxBytes
              ) {
                return;
              }
              throw new Error(t("agentConfig.toolResultCompactRecentGtOld"));
            },
          },
        ]}
        tooltip={t("agentConfig.toolResultCompactRecentThresholdTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1000}
          step={1000}
          placeholder={t(
            "agentConfig.toolResultCompactRecentThresholdPlaceholder",
          )}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.toolResultCompactRetentionDays")}
        name={["tool_result_compact", "retention_days"]}
        rules={[
          {
            required: true,
            message: t("agentConfig.toolResultCompactRetentionDaysRequired"),
          },
        ]}
        tooltip={t("agentConfig.toolResultCompactRetentionDaysTooltip")}
      >
        <SliderWithValue
          min={1}
          max={10}
          step={1}
          marks={{ 1: "1", 5: "5", 10: "10" }}
        />
      </Form.Item>
    </Card>
  );
}
