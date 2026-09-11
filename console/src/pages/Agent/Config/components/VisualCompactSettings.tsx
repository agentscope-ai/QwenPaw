import { Form, Switch } from "@agentscope-ai/design";
import { Segmented, Typography } from "antd";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

type VisualCompactEffort = "low" | "medium" | "high";

const { Paragraph, Text } = Typography;
const effortDescriptionKey: Record<VisualCompactEffort, string> = {
  low: "agentConfig.visualCompactLowDescription",
  medium: "agentConfig.visualCompactMediumDescription",
  high: "agentConfig.visualCompactHighDescription",
};

export function VisualCompactSettings() {
  const { t } = useTranslation();
  const enabled = Boolean(
    Form.useWatch(["light_context_config", "visual_compact_config", "enabled"]),
  );
  const effort = (Form.useWatch([
    "light_context_config",
    "visual_compact_config",
    "effort",
  ]) ?? "low") as VisualCompactEffort;

  return (
    <>
      <Paragraph className={styles.visualCompactDescription} type="secondary">
        {t("agentConfig.visualCompactDescription")}
      </Paragraph>

      <Form.Item
        label={t("agentConfig.visualCompactEnabled")}
        name={["light_context_config", "visual_compact_config", "enabled"]}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>

      <Form.Item
        initialValue="low"
        label={t("agentConfig.visualCompactEffort")}
        name={["light_context_config", "visual_compact_config", "effort"]}
      >
        <Segmented
          aria-label={t("agentConfig.visualCompactEffort")}
          block
          className={styles.visualCompactEffortControl}
          disabled={!enabled}
          options={[
            {
              label: t("agentConfig.visualCompactLow"),
              value: "low",
            },
            {
              label: t("agentConfig.visualCompactMedium"),
              value: "medium",
            },
            {
              label: t("agentConfig.visualCompactHigh"),
              value: "high",
            },
          ]}
        />
      </Form.Item>

      <Text
        className={styles.visualCompactEffortDescription}
        disabled={!enabled}
        type="secondary"
      >
        {t(effortDescriptionKey[effort])}
      </Text>

      <Paragraph className={styles.visualCompactNote} type="secondary">
        {t("agentConfig.visualCompactCapabilityNote")}{" "}
        {t("agentConfig.visualCompactQualityNote")}
      </Paragraph>
    </>
  );
}
