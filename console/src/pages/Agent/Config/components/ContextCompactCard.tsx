import { Form, Card, Switch, Input } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

interface ContextCompactCardProps {
  maxInputLength: number;
}

export function ContextCompactCard({
  maxInputLength,
}: ContextCompactCardProps) {
  const { t } = useTranslation();

  const memoryCompactRatio = Form.useWatch([
    "context_compact",
    "memory_compact_ratio",
  ]);
  const memoryReserveRatio = Form.useWatch([
    "context_compact",
    "memory_reserve_ratio",
  ]);

  const contextCompactThreshold = Math.floor(
    (maxInputLength ?? 0) * (memoryCompactRatio ?? 0),
  );
  const contextCompactReserveThreshold = Math.floor(
    (maxInputLength ?? 0) * (memoryReserveRatio ?? 0),
  );

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.contextCompactTitle")}
    >
      <Form.Item
        label={t("agentConfig.contextCompactEnabled")}
        name={["context_compact", "context_compact_enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.contextCompactEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.tokenCountEstimateDivisor")}
        name={["context_compact", "token_count_estimate_divisor"]}
        rules={[
          {
            required: true,
            message: t("agentConfig.tokenCountEstimateDivisorRequired"),
          },
        ]}
        tooltip={t("agentConfig.tokenCountEstimateDivisorTooltip")}
      >
        <SliderWithValue
          min={2}
          max={5}
          step={0.25}
          marks={{ 2: "2", 3: "3", 4: "4", 5: "5" }}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.contextCompactRatio")}
        name={["context_compact", "memory_compact_ratio"]}
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
        name={["context_compact", "memory_reserve_ratio"]}
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
        label={t("agentConfig.compactWithThinkingBlock")}
        name={["context_compact", "compact_with_thinking_block"]}
        valuePropName="checked"
        tooltip={t("agentConfig.compactWithThinkingBlockTooltip")}
      >
        <Switch />
      </Form.Item>
    </Card>
  );
}
