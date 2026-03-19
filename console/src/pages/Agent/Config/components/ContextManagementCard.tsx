import { Form, InputNumber, Input, Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

interface ContextManagementCardProps {
  contextCompactThreshold: number;
  contextCompactReserveThreshold: number;
}

export function ContextManagementCard({
  contextCompactThreshold,
  contextCompactReserveThreshold,
}: ContextManagementCardProps) {
  const { t } = useTranslation();
  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.contextManagementTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.maxInputLength")}
        name="max_input_length"
        rules={[
          {
            required: true,
            message: t("agentConfig.maxInputLengthRequired"),
          },
          {
            type: "number",
            min: 1000,
            message: t("agentConfig.maxInputLengthMin"),
          },
        ]}
        tooltip={t("agentConfig.maxInputLengthTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1000}
          step={1024}
          placeholder={t("agentConfig.maxInputLengthPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.contextCompactRatio")}
        name="memory_compact_ratio"
        rules={[
          {
            required: true,
            message: t("agentConfig.contextCompactRatioRequired"),
          },
        ]}
        tooltip={t("agentConfig.contextCompactRatioTooltip")}
      >
        <SliderWithValue
          min={0.3}
          max={0.9}
          step={0.01}
          marks={{ 0.3: "0.3", 0.6: "0.6", 0.9: "0.9" }}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.contextCompactThreshold")}
        tooltip={t("agentConfig.contextCompactThresholdTooltip")}
      >
        <Input
          disabled
          value={
            contextCompactThreshold > 0
              ? contextCompactThreshold.toLocaleString()
              : ""
          }
          placeholder={t("agentConfig.contextCompactThresholdPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.contextCompactReserveRatio")}
        name="memory_reserve_ratio"
        rules={[
          {
            required: true,
            message: t("agentConfig.contextCompactReserveRatioRequired"),
          },
        ]}
        tooltip={t("agentConfig.contextCompactReserveRatioTooltip")}
      >
        <SliderWithValue
          min={0.05}
          max={0.3}
          step={0.01}
          marks={{ 0.05: "0.05", 0.15: "0.15", 0.3: "0.3" }}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.contextCompactReserveThreshold")}
        tooltip={t("agentConfig.contextCompactReserveThresholdTooltip")}
      >
        <Input
          disabled
          value={
            contextCompactReserveThreshold > 0
              ? contextCompactReserveThreshold.toLocaleString()
              : ""
          }
          placeholder={t(
            "agentConfig.contextCompactReserveThresholdPlaceholder",
          )}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.toolResultCompactRecentN")}
        name="tool_result_compact_recent_n"
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
        name="tool_result_compact_old_threshold"
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
        name="tool_result_compact_recent_threshold"
        rules={[
          {
            required: true,
            message: t("agentConfig.toolResultCompactRecentThresholdRequired"),
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
        name="tool_result_compact_retention_days"
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
          max={30}
          step={1}
          marks={{ 1: "1", 7: "7", 14: "14", 30: "30" }}
        />
      </Form.Item>
    </Card>
  );
}
