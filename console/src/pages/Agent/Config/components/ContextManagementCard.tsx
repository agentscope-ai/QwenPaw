import { Form, InputNumber, Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function ContextManagementCard() {
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
          { required: true, message: t("agentConfig.maxInputLengthRequired") },
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
        label={t("agentConfig.historyMaxLength")}
        name="history_max_length"
        rules={[
          {
            required: true,
            message: t("agentConfig.historyMaxLengthRequired"),
          },
          {
            type: "number",
            min: 1000,
            message: t("agentConfig.historyMaxLengthMin"),
          },
        ]}
        tooltip={t("agentConfig.historyMaxLengthTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1000}
          step={1000}
          placeholder={t("agentConfig.historyMaxLengthPlaceholder")}
        />
      </Form.Item>
    </Card>
  );
}
