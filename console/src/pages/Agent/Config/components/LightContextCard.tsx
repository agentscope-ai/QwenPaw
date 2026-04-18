import { Form, Card, Switch, Input, Collapse, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

interface LightContextCardProps {
  maxInputLength: number;
}

export function LightContextCard({ maxInputLength }: LightContextCardProps) {
  const { t } = useTranslation();

  const compactThresholdRatio = Form.useWatch([
    "light_context_config",
    "context_compact_config",
    "compact_threshold_ratio",
  ]);
  const reserveThresholdRatio = Form.useWatch([
    "light_context_config",
    "context_compact_config",
    "reserve_threshold_ratio",
  ]);

  const compactThreshold = Math.floor(
    (maxInputLength ?? 0) * (compactThresholdRatio ?? 0.8),
  );
  const reserveThreshold = Math.floor(
    (maxInputLength ?? 0) * (reserveThresholdRatio ?? 0.1),
  );

  return (
    <Card className={styles.formCard} title={t("agentConfig.lightContextTitle")}>
      <Form.Item
        label={t("agentConfig.dialogPath")}
        name={["light_context_config", "dialog_path"]}
        tooltip={t("agentConfig.dialogPathTooltip")}
      >
        <Input placeholder={t("agentConfig.dialogPathPlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.tokenCountEstimateDivisor")}
        name={["light_context_config", "token_count_estimate_divisor"]}
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

      <Collapse
        items={[
          {
            key: "contextCompact",
            label: t("agentConfig.contextCompactCollapseLabel"),
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.contextCompactEnabled")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.contextCompactEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactRatio")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "compact_threshold_ratio",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.contextCompactRatioRequired"),
                    },
                  ]}
                  tooltip={t("agentConfig.contextCompactRatioTooltip")}
                >
                  <SliderWithValue
                    min={0.1}
                    max={0.9}
                    step={0.01}
                    marks={{ 0.1: "0.1", 0.5: "0.5", 0.9: "0.9" }}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactThreshold")}
                  tooltip={t("agentConfig.contextCompactThresholdTooltip")}
                >
                  <Input
                    disabled
                    value={
                      compactThreshold > 0
                        ? compactThreshold.toLocaleString()
                        : ""
                    }
                    placeholder={t("agentConfig.contextCompactThresholdPlaceholder")}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactReserveRatio")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "reserve_threshold_ratio",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.contextCompactReserveRatioRequired"),
                    },
                  ]}
                  tooltip={t("agentConfig.contextCompactReserveRatioTooltip")}
                >
                  <SliderWithValue
                    min={0}
                    max={0.3}
                    step={0.01}
                    marks={{ 0: "0", 0.15: "0.15", 0.3: "0.3" }}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactReserveThreshold")}
                  tooltip={t("agentConfig.contextCompactReserveThresholdTooltip")}
                >
                  <Input
                    disabled
                    value={
                      reserveThreshold > 0
                        ? reserveThreshold.toLocaleString()
                        : ""
                    }
                    placeholder={t(
                      "agentConfig.contextCompactReserveThresholdPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.compactWithThinkingBlock")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "compact_with_thinking_block",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.compactWithThinkingBlockTooltip")}
                >
                  <Switch />
                </Form.Item>
              </>
            ),
          },
          {
            key: "toolResultPruning",
            label: t("agentConfig.toolResultPruningCollapseLabel"),
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.toolResultCompactEnabled")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.toolResultCompactEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.toolResultCompactRecentN")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "pruning_recent_n",
                  ]}
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
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "pruning_old_msg_max_bytes",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.toolResultCompactOldThresholdRequired"),
                    },
                  ]}
                  tooltip={t("agentConfig.toolResultCompactOldThresholdTooltip")}
                >
                  <Input
                    placeholder={t(
                      "agentConfig.toolResultCompactOldThresholdPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.toolResultCompactRecentThreshold")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "pruning_recent_msg_max_bytes",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.toolResultCompactRecentThresholdRequired"),
                    },
                  ]}
                  tooltip={t("agentConfig.toolResultCompactRecentThresholdTooltip")}
                >
                  <Input
                    placeholder={t(
                      "agentConfig.toolResultCompactRecentThresholdPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.toolResultCompactRetentionDays")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "offload_retention_days",
                  ]}
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

                <Form.Item
                  label={t("agentConfig.exemptFileExtensions")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "exempt_file_extensions",
                  ]}
                  tooltip={t("agentConfig.exemptFileExtensionsTooltip")}
                >
                  <Select
                    mode="tags"
                    placeholder={t("agentConfig.exemptFileExtensionsPlaceholder")}
                    tokenSeparators={[",", " "]}
                    style={{ width: "100%" }}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.exemptToolNames")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "exempt_tool_names",
                  ]}
                  tooltip={t("agentConfig.exemptToolNamesTooltip")}
                >
                  <Select
                    mode="tags"
                    placeholder={t("agentConfig.exemptToolNamesPlaceholder")}
                    tokenSeparators={[",", " "]}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}