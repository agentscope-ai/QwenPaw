import { NumberStepper } from "@/components/interaction/NumberStepper";
import { SettingsField } from "@/components/interaction/SettingsField";
import { Form, Switch, Collapse } from "@agentscope-ai/design";
import { Typography } from "antd";
import { useTranslation } from "react-i18next";

const fields = [
  { name: "drop_threshold", value: 0.1, min: 0, max: 1, step: 0.01 },
  { name: "preserve_recent_messages", value: 6, min: 0 },
  { name: "preview_chars", value: 300, min: 0 },
  { name: "total_timeout_seconds", value: 30, min: 0.1, max: 300, step: 1 },
] as const;
const advancedFields = [
  { name: "max_state_tokens", value: 25000, min: 1 },
  { name: "max_request_tokens", value: 30000, min: 1 },
  { name: "evidence_chars", value: 2000, min: 1 },
  { name: "max_concurrency", value: 4, min: 1, max: 32 },
] as const;

type NumericField = {
  name: string;
  value: number;
  min: number;
  max?: number;
  step?: number;
};

export function DecisionCompactSettings() {
  const { t } = useTranslation();
  const enabled = Boolean(
    Form.useWatch([
      "light_context_config",
      "decision_compact_config",
      "enabled",
    ]),
  );
  const renderField = (field: NumericField) => (
    <SettingsField
      key={field.name}
      name={["light_context_config", "decision_compact_config", field.name]}
      initialValue={field.value}
      label={t(`agentConfig.decisionCompact_${field.name}`)}
      tooltip={t(`agentConfig.decisionCompact_${field.name}Help`)}
      rules={[
        { required: enabled, type: "number", min: field.min, max: field.max },
      ]}
    >
      <NumberStepper
        disabled={!enabled}
        min={field.min}
        max={field.max}
        step={field.step ?? 1}
        precision={
          field.name === "drop_threshold"
            ? 2
            : field.name === "total_timeout_seconds"
            ? 1
            : 0
        }
        style={{ width: "100%" }}
      />
    </SettingsField>
  );
  return (
    <>
      <Typography.Paragraph type="secondary">
        {t("agentConfig.decisionCompactDescription")}
      </Typography.Paragraph>
      <SettingsField
        name={["light_context_config", "decision_compact_config", "enabled"]}
        initialValue={false}
        label={t("agentConfig.decisionCompactEnabled")}
        valuePropName="checked"
      >
        <Switch />
      </SettingsField>
      {fields.map(renderField)}
      <Collapse
        ghost
        items={[
          {
            key: "advanced",
            label: t("agentConfig.decisionCompactAdvanced"),
            children: advancedFields.map(renderField),
          },
        ]}
      />
    </>
  );
}
